from __future__ import annotations

from typing import Final, Optional

import json
import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    STORAGE_VERSION,
    STORAGE_KEY,
    CONF_OMDB_API_KEY,
    SIGNAL_LIBRARY_UPDATED,
)
from .omdb import fetch_omdb

_LOGGER = logging.getLogger(__name__)

PLATFORMS: Final = [Platform.SENSOR]


# ---------------------------- Core library model ---------------------------- #

class DvdLibrary:
    """In-memory + persisted collection with optional OMDb enrichment."""

    def __init__(self, hass: HomeAssistant, api_key: Optional[str]) -> None:
        self.hass = hass
        self.api_key = api_key
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.items: list[dict] = []

    async def async_load(self) -> None:
        data = await self.store.async_load() or {}
        self.items = data.get("items", [])
        _LOGGER.debug("DVD Library loaded %d items", len(self.items))

    async def _async_save_and_signal(self) -> None:
        await self.store.async_save({"items": self.items})
        async_dispatcher_send(self.hass, SIGNAL_LIBRARY_UPDATED)

    def _find_index(self, key: str, value: str) -> Optional[int]:
        for idx, it in enumerate(self.items):
            if it.get(key) and it.get(key) == value:
                return idx
        return None

    # --- helpers ------------------------------------------------------------ #

    @staticmethod
    def _is_empty_item(it: dict) -> bool:
        def empty(v):
            return v is None or (isinstance(v, str) and v.strip() == "")

        keys = ("title", "year", "barcode", "imdb_id")
        return all(empty(it.get(k)) for k in keys)

    async def purge_nulls(self) -> int:
        """Remove items where title/year/barcode/imdb_id are all empty/null."""
        before = len(self.items)
        self.items = [it for it in self.items if not self._is_empty_item(it)]
        removed = before - len(self.items)
        await self._async_save_and_signal()
        return removed

    async def remove_index(self, index: int) -> None:
        if not isinstance(index, int):
            raise ValueError("Index must be an integer")
        if index < 0 or index >= len(self.items):
            raise ValueError("Index out of range")
        removed = self.items.pop(index)
        _LOGGER.debug(
            "Removed by index %s: %s",
            index,
            removed.get("title") or removed.get("imdb_id") or removed.get("barcode"),
        )
        await self._async_save_and_signal()

    # --- main ops ----------------------------------------------------------- #

    async def add_item(self, data: dict) -> None:
        """Add or merge a DVD item; enrich via OMDb if possible."""
        item = {
            "title": data.get("title"),
            "year": str(data.get("year")) if data.get("year") else None,
            "barcode": data.get("barcode"),
            "imdb_id": data.get("imdb_id"),
            "added_by": data.get("added_by"),
        }

        # Enrich with OMDb (if key present)
        try:
            meta = (
                await self.hass.async_add_executor_job(
                    fetch_omdb,
                    self.api_key,
                    item.get("title"),
                    item.get("imdb_id"),
                    item.get("year"),
                )
                if self.api_key
                else None
            )
            if meta:
                item.update(meta)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("OMDb lookup failed: %s", e)

        # Guard against empty adds
        if not any(
            [item.get("imdb_id"), item.get("barcode"), (item.get("title") or "").strip()]
        ):
            _LOGGER.warning(
                "Skipping add: no imdb_id/barcode/title (no usable metadata matched)"
            )
            return

        # Dedup logic
        idx: Optional[int] = None
        if item.get("imdb_id"):
            idx = self._find_index("imdb_id", item["imdb_id"])
        if idx is None and item.get("barcode"):
            idx = self._find_index("barcode", item["barcode"])
        if idx is None and item.get("title"):
            for i, it in enumerate(self.items):
                if it.get("title") == item["title"] and (
                    not item.get("year") or it.get("year") == item.get("year")
                ):
                    idx = i
                    break

        if idx is not None:
            self.items[idx].update(item)
            _LOGGER.debug(
                "Updated existing item at %s: %s",
                idx,
                item.get("title") or item.get("imdb_id") or item.get("barcode"),
            )
        else:
            self.items.append(item)
            _LOGGER.debug(
                "Added new item: %s",
                item.get("title") or item.get("imdb_id") or item.get("barcode"),
            )

        await self._async_save_and_signal()

    async def update_item(self, selector: dict, updates: dict) -> None:
        idx: Optional[int] = None
        for key in ("imdb_id", "barcode", "title"):
            if selector.get(key):
                idx = self._find_index(key, selector[key])
            if idx is not None:
                break
        if idx is None:
            raise ValueError("Item not found for selector")

        self.items[idx].update(updates)

        # Re-enrich if relevant fields changed
        if any(k in updates for k in ("title", "year", "imdb_id")) and self.api_key:
            meta = await self.hass.async_add_executor_job(
                fetch_omdb,
                self.api_key,
                self.items[idx].get("title"),
                self.items[idx].get("imdb_id"),
                self.items[idx].get("year"),
            )
            if meta:
                self.items[idx].update(meta)

        await self._async_save_and_signal()

    async def remove_item(self, selector: dict) -> None:
        key = next((k for k in ("imdb_id", "barcode", "title") if selector.get(k)), None)
        if not key:
            raise ValueError("Provide imdb_id, barcode or title")
        idx = self._find_index(key, selector[key])
        if idx is None:
            raise ValueError("Item not found")

        removed = self.items.pop(idx)
        _LOGGER.debug(
            "Removed item by %s=%s: %s",
            key,
            selector[key],
            removed.get("title") or removed.get("imdb_id") or removed.get("barcode"),
        )
        await self._async_save_and_signal()

    async def refresh_metadata(self, selector: dict | None = None) -> None:
        targets: list[int] = []
        if selector:
            key = next(
                (k for k in ("imdb_id", "barcode", "title") if selector.get(k)), None
            )
            if key:
                idx = self._find_index(key, selector[key])
                if idx is not None:
                    targets = [idx]
        if not targets:
            targets = list(range(len(self.items)))
        if not self.api_key:
            return  # nothing to do

        for idx in targets:
            it = self.items[idx]
            meta = await self.hass.async_add_executor_job(
                fetch_omdb,
                self.api_key,
                it.get("title"),
                it.get("imdb_id"),
                it.get("year"),
            )
            if meta:
                self.items[idx].update(meta)

        await self._async_save_and_signal()


# -------------------------- HA integration scaffolding ---------------------- #

async def async_setup(hass: HomeAssistant, config) -> bool:
    """Legacy setup hook (no YAML config handled here)."""
    return True


def _get_lib_from_call(hass: HomeAssistant, call: ServiceCall) -> DvdLibrary:
    """Resolve target library for a service call.

    If service data includes 'entry_id', that instance is used; otherwise first loaded.
    """
    domain_data: dict = hass.data.get(DOMAIN) or {}
    entry_id = call.data.get("entry_id")
    if entry_id and entry_id in domain_data:
        return domain_data[entry_id]["lib"]

    for key, val in domain_data.items():
        if key != "services_registered":
            return val["lib"]

    raise HomeAssistantError("No DVD Library instances are loaded.")


def _register_services_once(hass: HomeAssistant) -> None:
    """Register domain services once (shared across all instances)."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("services_registered"):
        return

    def wrap(handler):
        async def _inner(call: ServiceCall):
            try:
                lib = _get_lib_from_call(hass, call)
                await handler(lib, call)
            except (ValueError, PermissionError) as e:
                raise HomeAssistantError(str(e)) from e
            except Exception as e:  # noqa: BLE001
                _LOGGER.exception(
                    "Unexpected error in dvd_library service %s", handler.__name__
                )
                raise HomeAssistantError(
                    "Unexpected error; see logs for details."
                ) from e

        return _inner

    # --- services (domain-level) ------------------------------------------ #

    async def s_add(lib: DvdLibrary, call: ServiceCall) -> None:
        await lib.add_item(call.data)

    async def s_update(lib: DvdLibrary, call: ServiceCall) -> None:
        await lib.update_item(
            call.data.get("selector", {}), call.data.get("updates", {})
        )

    async def s_remove(lib: DvdLibrary, call: ServiceCall) -> None:
        await lib.remove_item(call.data)

    async def s_remove_index(lib: DvdLibrary, call: ServiceCall) -> None:
        index = call.data.get("index")
        if index is None:
            raise ValueError("Provide 'index'")
        await lib.remove_index(int(index))

    async def s_refresh(lib: DvdLibrary, call: ServiceCall) -> None:
        await lib.refresh_metadata(call.data or {})

    async def s_import_json(lib: DvdLibrary, call: ServiceCall) -> None:
        path = call.data.get("path")
        if not path:
            raise ValueError("Provide 'path' to a JSON file in /config")
        full = lib.hass.config.path(path)
        if not os.path.exists(full):
            raise ValueError(f"File not found: {path}")
        with open(full, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("items", [])
        for item in items:
            await lib.add_item(item)

    async def s_purge(lib: DvdLibrary, call: ServiceCall) -> None:
        removed = await lib.purge_nulls()
        _LOGGER.info("Purged %s empty items from DVD library", removed)

    # Register services under the domain
    hass.services.async_register(DOMAIN, "add_item", wrap(s_add))
    hass.services.async_register(DOMAIN, "update_item", wrap(s_update))
    hass.services.async_register(DOMAIN, "remove_item", wrap(s_remove))
    hass.services.async_register(DOMAIN, "remove_index", wrap(s_remove_index))
    hass.services.async_register(DOMAIN, "refresh_metadata", wrap(s_refresh))
    hass.services.async_register(DOMAIN, "import_json", wrap(s_import_json))
    hass.services.async_register(DOMAIN, "purge_nulls", wrap(s_purge))

    domain_data["services_registered"] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a DVD Library instance from a config entry."""
    api_key = (entry.data.get(CONF_OMDB_API_KEY) or entry.options.get(CONF_OMDB_API_KEY) or "").strip() or None

    lib = DvdLibrary(hass, api_key)
    await lib.async_load()

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = {"lib": lib}

    _register_services_once(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a DVD Library instance."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        domain_data: dict = hass.data.get(DOMAIN, {})
        domain_data.pop(entry.entry_id, None)

        # If last one removed, also remove services
        has_instances = any(k for k in domain_data.keys() if k != "services_registered")
        if not has_instances:
            for srv in (
                "add_item",
                "update_item",
                "remove_item",
                "remove_index",
                "refresh_metadata",
                "import_json",
                "purge_nulls",
            ):
                hass.services.async_remove(DOMAIN, srv)
            hass.data.pop(DOMAIN, None)

    return unload_ok


# Options flow hook
async def async_get_options_flow(config_entry: ConfigEntry):
    from .config_flow import OptionsFlowHandler  # local import to avoid circular
    return OptionsFlowHandler(config_entry)
