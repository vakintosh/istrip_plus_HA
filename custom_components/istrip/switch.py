"""One operating switch for controller-local sound response."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .control_entity import ControlEntity


async def async_setup_entry(hass, entry, async_add_entities):
    light = entry.runtime_data["light"]
    # Permission now lives in Configure, backed by the same persisted setting.
    # Remove only our obsolete permission entity, never the light or another entry.
    registry = er.async_get(hass)
    legacy = registry.async_get_entity_id(
        "switch", DOMAIN, f"{light.unique_id}_experimental_music"
    )
    if legacy and registry.async_get(legacy).config_entry_id == entry.entry_id:
        registry.async_remove(legacy)
    async_add_entities(
        [
            IstripSwitch(light, "microphone", "Sound reactive"),
        ]
    )


class IstripSwitch(ControlEntity, SwitchEntity):
    """Music cannot start without an explicit per-device opt-in."""

    def __init__(self, light, key, name):
        super().__init__(light, key, name)
        self._attr_icon = "mdi:microphone"

    @property
    def available(self):
        """Do not offer activation before opt-in; always allow an active mode off."""
        return self.light.settings.experimental_music or self.light._music_active

    @property
    def is_on(self):
        if self.key == "microphone":
            return self.light._music_active
        return self.light.settings.experimental_music

    async def async_turn_on(self, **kwargs):
        await self.light.async_set_control(self.key, True)

    async def async_turn_off(self, **kwargs):
        await self.light.async_set_control(self.key, False)
