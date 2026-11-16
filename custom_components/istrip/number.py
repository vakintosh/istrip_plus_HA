"""Effect-speed and controller-microphone sensitivity sliders."""

from homeassistant.components.number import NumberEntity, NumberMode

from .control_entity import ControlEntity


async def async_setup_entry(hass, entry, async_add_entities):
    light = entry.runtime_data["light"]
    async_add_entities(
        [
            IstripNumber(light, "speed", "Effect speed"),
            IstripNumber(light, "sensitivity", "Sound sensitivity"),
        ]
    )


class IstripNumber(ControlEntity, NumberEntity):
    """Native slider operating the existing light."""

    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    @property
    def native_min_value(self):
        return 1 if self.key == "speed" else 0

    @property
    def native_value(self):
        if self.key == "speed":
            return self.light._pending_speed or self.light._speed_for(self.light.effect)
        return self.light.settings.sensitivity

    async def async_set_native_value(self, value):
        if not float(value).is_integer():
            raise ValueError("Expected whole number")
        if self.key == "speed":
            await self.light.set_speed(int(value))
        else:
            await self.light.async_set_control(self.key, int(value))
