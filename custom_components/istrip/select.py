"""Experimental music style and advanced host-side RGB order."""

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory

from .control_entity import ControlEntity
from .controls import MUSIC_STYLES, RGB_ORDERS


async def async_setup_entry(hass, entry, async_add_entities):
    light = entry.runtime_data["light"]
    async_add_entities(
        [
            IstripSelect(light, "music_style", "Sound style"),
            IstripSelect(light, "rgb_order", "RGB channel order"),
        ]
    )


class IstripSelect(ControlEntity, SelectEntity):
    """Persist a validated selection; never guess device opcode 5."""

    def __init__(self, light, key, name):
        super().__init__(light, key, name)
        self._attr_options = list(MUSIC_STYLES if key == "music_style" else RGB_ORDERS)
        if key == "rgb_order":
            self._attr_entity_category = EntityCategory.CONFIG
            self._attr_entity_registry_enabled_default = False

    @property
    def current_option(self):
        return getattr(self.light.settings, self.key)

    async def async_select_option(self, option):
        await self.light.async_set_control(self.key, option)
