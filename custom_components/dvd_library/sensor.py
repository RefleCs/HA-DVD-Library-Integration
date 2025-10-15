
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback, HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, SIGNAL_LIBRARY_UPDATED

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities) -> None:
    """Set up the DVD Library sensor for a config entry."""
    lib = hass.data[DOMAIN][entry.entry_id]["lib"]
    async_add_entities([DvdLibrarySensor(lib, entry)], True)

class DvdLibrarySensor(SensorEntity):
    """Shows the number of DVDs and exposes the collection as an attribute."""

    _attr_name = "DVD Library"
    _attr_icon = "mdi:filmstrip-box"
    _attr_should_poll = False
    _attr_unique_id = "dvd_library_count"  # stable unique_id

    def __init__(self, library, entry: ConfigEntry) -> None:
        self.library = library
        self._attr_native_value = 0
        self._attr_extra_state_attributes = {"items": []}
        self._entry_id = entry.entry_id
        self._unsub = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name="DVD Library",
            manufacturer="Custom",
            model="Library",
        )

    async def async_added_to_hass(self) -> None:
        @callback
        def _updated() -> None:
            self._attr_native_value = len(self.library.items)
            self._attr_extra_state_attributes = {"items": self.library.items}
            self.async_write_ha_state()

        self._unsub = async_dispatcher_connect(self.hass, SIGNAL_LIBRARY_UPDATED, _updated)
        _updated()

    async def async_will_remove_from_hass(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
