"""Native control creation, identity and dispatcher lifecycle in real HA."""

from types import MethodType, SimpleNamespace
from unittest.mock import Mock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.istrip import number, select, switch
from custom_components.istrip.controller import ControllerMixin
from test_controls import TestLight as FakeLight


@pytest.mark.asyncio
async def test_native_setup_changes_and_unsubscription(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    light = FakeLight()
    light.hass = hass
    light.async_write_ha_state = Mock()
    light._controls_changed = MethodType(ControllerMixin._controls_changed, light)
    entry = SimpleNamespace(runtime_data={"light": light})
    entities = []
    for module in (number, select, switch):
        await module.async_setup_entry(hass, entry, entities.extend)
    assert {entity.key for entity in entities} == {
        "speed",
        "sensitivity",
        "music_style",
        "rgb_order",
        "microphone",
        "experimental_music",
    }
    assert len({entity.unique_id for entity in entities}) == 6
    for entity in entities:
        assert entity.device_info == light.device_info
        assert entity.available and not entity.should_poll
        entity.hass = hass
        entity.async_write_ha_state = Mock()
        entity.async_on_remove = Mock()
        await entity.async_added_to_hass()

    by_key = {entity.key: entity for entity in entities}
    assert by_key["speed"].native_min_value == 1
    assert by_key["sensitivity"].native_min_value == 0
    assert by_key["speed"].native_value == 100
    assert not by_key["microphone"].is_on
    await by_key["sensitivity"].async_set_native_value(42.0)
    await hass.async_block_till_done()
    assert by_key["sensitivity"].native_value == 42
    for entity in entities:
        entity.async_write_ha_state.assert_called_once()
        entity.async_on_remove.call_args.args[0]()
        entity.async_write_ha_state.reset_mock()

    # Once removed, old controls must not receive changes from the light.
    light._controls_changed()
    await hass.async_block_till_done()
    for entity in entities:
        entity.async_write_ha_state.assert_not_called()


@pytest.mark.asyncio
async def test_native_slider_validation_and_microphone_commands():
    light = FakeLight()
    speed = number.IstripNumber(light, "speed", "Effect speed")
    with pytest.raises(ValueError):
        await speed.async_set_native_value(4.5)
    await speed.async_set_native_value(33)
    assert speed.native_value == 33 and not light.frames
    mic = switch.IstripSwitch(light, "microphone", "Microphone")
    light.settings.experimental_music = True
    await mic.async_turn_on()
    assert mic.is_on
    await mic.async_turn_off()
    assert not mic.is_on and light.is_on
    assert light.frames[-1][4:7] == bytes([2, 1, 0])
