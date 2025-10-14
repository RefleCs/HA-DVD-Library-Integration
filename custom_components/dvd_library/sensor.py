from homeassistant.components.sensor import SensorEntity
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DOMAIN, SIGNAL_LIBRARY_UPDATED

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    lib = hass.data.get(DOMAIN)
    if not lib:
        return
    sensor = DvdLibrarySensor(lib)
    async_add_entities([sensor], True)

class DvdLibrarySensor(SensorEntity):
    _attr_name = "DVD Library"
    _attr_icon = "mdi:filmstrip-box"
    _attr_unique_id = "dvd_library_count"

    def __init__(self, library):
        self.library = library
        self._attr_native_value = 0
        self._attr_extra_state_attributes = {"items": []}
        self._unsub = None

    async def async_added_to_hass(self):
        @callback
        def _updated():
            self._attr_native_value = len(self.library.items)
            self._attr_extra_state_attributes = {"items": self.library.items}
            self.async_write_ha_state()

        self._unsub = async_dispatcher_connect(self.hass, SIGNAL_LIBRARY_UPDATED, _updated)
        # Push initial state
        _updated()

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()
            self._unsub = None