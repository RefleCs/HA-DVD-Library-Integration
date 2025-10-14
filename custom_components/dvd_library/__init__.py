import logging
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import HomeAssistantError  # <-- friendlier errors to UI

from .const import (
    DOMAIN,
    STORAGE_VERSION,
    STORAGE_KEY,
    CONF_OMDB_API_KEY,
    SIGNAL_LIBRARY_UPDATED,
)
from .omdb import fetch_omdb

_LOGGER = logging.getLogger(__name__)


class DvdLibrary:
    def __init__(self, hass: HomeAssistant, api_key: str | None):
        self.hass = hass
        self.api_key = api_key
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.items: list[dict] = []

    async def async_load(self):
        data = await self.store.async_load() or {}
        self.items = data.get("items", [])
        _LOGGER.debug("DVD Library loaded %d items", len(self.items))

    async def _async_save_and_signal(self):
        await self.store.async_save({"items": self.items})
        async_dispatcher_send(self.hass, SIGNAL_LIBRARY_UPDATED)

    def _find_index(self, key: str, value: str):
        for idx, it in enumerate(self.items):
            if it.get(key) and it.get(key) == value:
                return idx
        return None

    # ---------- Helpers ----------
    def _is_empty_item(self, it: dict) -> bool:
        def empty(v):
            return v is None or (isinstance(v, str) and v.strip() == "")
        keys = ("title", "year", "barcode", "imdb_id")
        return all(empty(it.get(k)) for k in keys)

    async def purge_nulls(self) -> int:
        """Remove items where title, year, barcode, and imdb_id are all empty/null."""
        before = len(self.items)
        self.items = [it for it in self.items if not self._is_empty_item(it)]
        removed = before - len(self.items)
        await self._async_save_and_signal()
        return removed

    async def remove_index(self, index: int):
        if not isinstance(index, int):
            raise ValueError("Index must be an integer")
        if index < 0 or index >= len(self.items):
            raise ValueError("Index out of range")
        removed = self.items.pop(index)
        _LOGGER.debug("Removed by index %s: %s", index, removed.get("title") or removed.get("imdb_id") or removed.get("barcode"))
        await self._async_save_and_signal()
    # -----------------------------

    async def add_item(self, data: dict):
        item = {
            "title": data.get("title"),
            "year": str(data.get("year")) if data.get("year") else None,
            "barcode": data.get("barcode"),
            "imdb_id": data.get("imdb_id"),
            "added_by": data.get("added_by"),
        }

        # Enrich via OMDb (if available)
        try:
            meta = await self.hass.async_add_executor_job(
                fetch_omdb, self.api_key, item.get("title"), item.get("imdb_id"), item.get("year")
            ) if self.api_key else None
            if meta:
                item.update(meta)
        except Exception as e:
            _LOGGER.warning("OMDb lookup failed: %s", e)

        # Guard against empty adds
        if not any([item.get("imdb_id"), item.get("barcode"), (item.get("title") or "").strip()]):
            _LOGGER.warning("Skipping add: no imdb_id/barcode/title (no usable metadata matched)")
            return

        # Deduplicate logic
        idx = None
        if item.get("imdb_id"):
            idx = self._find_index("imdb_id", item["imdb_id"])
        if idx is None and item.get("barcode"):
            idx = self._find_index("barcode", item["barcode"])
        if idx is None and item.get("title"):
            for i, it in enumerate(self.items):
                if it.get("title") == item["title"] and (not item.get("year") or it.get("year") == item.get("year")):
                    idx = i
                    break

        if idx is not None:
            self.items[idx].update(item)
            _LOGGER.debug("Updated existing item at %s: %s", idx, item.get("title") or item.get("imdb_id") or item.get("barcode"))
        else:
            self.items.append(item)
            _LOGGER.debug("Added new item: %s", item.get("title") or item.get("imdb_id") or item.get("barcode"))

        await self._async_save_and_signal()

    async def update_item(self, selector: dict, updates: dict):
        idx = None
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
                fetch_omdb, self.api_key, self.items[idx].get("title"), self.items[idx].get("imdb_id"), self.items[idx].get("year")
            )
            if meta:
                self.items[idx].update(meta)

        await self._async_save_and_signal()

    async def remove_item(self, selector: dict):
        key = next((k for k in ("imdb_id", "barcode", "title") if selector.get(k)), None)
        if not key:
            raise ValueError("Provide imdb_id, barcode or title")
        idx = self._find_index(key, selector[key])
        if idx is None:
            raise ValueError("Item not found")
        removed = self.items.pop(idx)
        _LOGGER.debug("Removed item by %s=%s: %s", key, selector[key], removed.get("title") or removed.get("imdb_id") or removed.get("barcode"))
        await self._async_save_and_signal()

    async def refresh_metadata(self, selector: dict | None = None):
        targets = []
        if selector:
            key = next((k for k in ("imdb_id", "barcode", "title") if selector.get(k)), None)
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
                fetch_omdb, self.api_key, it.get("title"), it.get("imdb_id"), it.get("year")
            )
            if meta:
                self.items[idx].update(meta)
        await self._async_save_and_signal()


async def async_setup(hass: HomeAssistant, config: ConfigType):
    conf = config.get(DOMAIN, {})
    api_key = conf.get(CONF_OMDB_API_KEY)
    if isinstance(api_key, str):
        api_key = api_key.strip()

    # Create and load the library
    lib = DvdLibrary(hass, api_key)
    await lib.async_load()
    hass.data[DOMAIN] = lib

    # --- Owner/Admin check helper (properly awaits) ---
    async def ensure_privileged(call: ServiceCall):
        """Raise if caller is not admin or owner."""
        user = None
        if call.context and call.context.user_id:
            # Some HA builds expose async_get_user; await it if present
            getter = getattr(hass.auth, "async_get_user", None)
            if callable(getter):
                user = await getter(call.context.user_id)
            else:
                # Very old fallback (unlikely)
                user = hass.auth.get_user(call.context.user_id)
        if not user or not (getattr(user, "is_admin", False) or getattr(user, "is_owner", False)):
            raise PermissionError("This service requires an administrator or owner.")
    # --------------------------------------------------

    # Wrap service calls to surface clean errors to the UI
    def _wrap(handler):
        async def _inner(call: ServiceCall):
            try:
                await ensure_privileged(call)
                await handler(call)
            except (ValueError, PermissionError) as e:
                # Bubble up a clean message
                raise HomeAssistantError(str(e)) from e
            except Exception as e:
                _LOGGER.exception("Unexpected error in dvd_library service %s", handler.__name__)
                raise HomeAssistantError("Unexpected error; see logs for details.") from e
        return _inner

    # Services (owner/admin-only)
    async def _add(call: ServiceCall):
        await lib.add_item(call.data)

    async def _update(call: ServiceCall):
        await lib.update_item(call.data.get("selector", {}), call.data.get("updates", {}))

    async def _remove(call: ServiceCall):
        await lib.remove_item(call.data)

    async def _remove_index(call: ServiceCall):
        index = call.data.get("index")
        if index is None:
            raise ValueError("Provide 'index'")
        await lib.remove_index(int(index))

    async def _refresh(call: ServiceCall):
        await lib.refresh_metadata(call.data or {})

    async def _import_json(call: ServiceCall):
        path = call.data.get("path")
        if not path:
            raise ValueError("Provide 'path' to a JSON file in /config")
        import json, os
        full = hass.config.path(path)
        if not os.path.exists(full):
            raise ValueError(f"File not found: {path}")
        with open(full, "r", encoding="utf-8") as f:
            data = json.load(f)
        items = data if isinstance(data, list) else data.get("items", [])
        for item in items:
            await lib.add_item(item)

    async def _purge_nulls(call: ServiceCall):
        removed = await lib.purge_nulls()
        _LOGGER.info("Purged %s empty items from DVD library", removed)

    from homeassistant.helpers.discovery import async_load_platform
    hass.services.async_register(DOMAIN, "add_item", _wrap(_add))
    hass.services.async_register(DOMAIN, "update_item", _wrap(_update))
    hass.services.async_register(DOMAIN, "remove_item", _wrap(_remove))
    hass.services.async_register(DOMAIN, "remove_index", _wrap(_remove_index))
    hass.services.async_register(DOMAIN, "refresh_metadata", _wrap(_refresh))
    hass.services.async_register(DOMAIN, "import_json", _wrap(_import_json))
    hass.services.async_register(DOMAIN, "purge_nulls", _wrap(_purge_nulls))

    # Load the sensor platform for this domain
    hass.async_create_task(async_load_platform(hass, "sensor", DOMAIN, {}, config))

    return True