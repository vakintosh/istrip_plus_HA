"""Explicit experimental opt-in and controller-local microphone switch."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory

from .control_entity import ControlEntity


async def async_setup_entry(hass, entry, async_add_entities):
    light = entry.runtime_data["light"]
    async_add_entities(
        [
            IstripSwitch(light, "microphone", "Controller microphone (experimental)"),
            IstripSwitch(light, "experimental_music", "Experimental music protocol"),
        ]
    )


class IstripSwitch(ControlEntity, SwitchEntity):
    """Music cannot start without an explicit per-device opt-in."""

    def __init__(self, light, key, name):
        super().__init__(light, key, name)
        if key == "experimental_music":
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self):
        if self.key == "microphone":
            return self.light._music_active
        return self.light.settings.experimental_music

    async def async_turn_on(self, **kwargs):
        await self.light.async_set_control(self.key, True)

    async def async_turn_off(self, **kwargs):
        await self.light.async_set_control(self.key, False)
