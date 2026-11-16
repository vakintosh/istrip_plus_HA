"""Shared native control entity behavior, without a BLE client."""

from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN


class ControlEntity(Entity):
    """Reference the existing light and refresh when it changes."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, light, key, name):
        self.light = light
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{light.unique_id}_{key}"
        self._attr_device_info = light.device_info

    @property
    def available(self):
        """Preferences remain accessible even when BLE is unavailable."""
        return True

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"{DOMAIN}_{self.light._entry_id}_controls", self._refresh
            )
        )

    @callback
    def _refresh(self):
        self.async_write_ha_state()
