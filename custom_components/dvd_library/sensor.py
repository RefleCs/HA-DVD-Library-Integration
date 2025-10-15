from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback, HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, SIGNAL_LIBRARY_UPDATED


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up the DVD Library sensor for a config entry."""
    lib = hass.data[DOMAIN][entry.entry_id]["lib"]
    unique_id = f"dvd_library_{entry.entry_id}_count"
    async_add_entities([DvdLibrarySensor(lib, unique_id)], True)


class DvdLibrarySensor(SensorEntity):
    """Sensor showing the number of items and exposing the collection as an attribute."""

    _attr_name = "DVD Library"
    _attr_icon = "mdi:filmstrip-box"

    def __init__(self, library, unique_id: str) -> None:
        self.library = library
        self._attr_native_value = 0
        self._attr_extra_state_attributes = {"items": []}
        self._attr_unique_id = unique_id
        self._unsub = None

    async def async_added_to_hass(self) -> None:
        @callback
        def _updated() -> None:
            self._attr_native_value = len(self.library.items)
            self._attr_extra_state_attributes = {"items": self.library.items}
            self.async_write_ha_state()

        self._unsub = async_dispatcher_connect(
            self.hass, SIGNAL_LIBRARY_UPDATED, _updated
        )
        _updated()  # push initial state

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
