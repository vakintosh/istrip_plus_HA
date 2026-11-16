"""Standalone brightness command: wire format, mode preservation and failures."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.istrip.const import KNOWN_CHAR_UUIDS
from custom_components.istrip.controls import MUSIC_EFFECT
from custom_components.istrip.light import IstripLight
from custom_components.istrip.payload_generator import CommandType, PayloadGenerator
from test_controls import TestLight as FakeLight


@pytest.mark.parametrize("level", [0, 1, 10, 20, 64, 100])
def test_light_command_layout(level):
    pg = PayloadGenerator()
    frame = pg.decrypt_payload(bytes.fromhex(pg.get_brightness_payload(level)))
    assert frame == bytes([0x54, 0x52, 0, 0x57, 7, 1, level] + [0] * 9)
    assert pg.parse_state(frame) == {
        "command_type": CommandType.LIGHT,
        "brightness": int(level * 255 / 100),
    }


@pytest.mark.parametrize("level", [-1, 101, True, 1.5, "20"])
def test_invalid_device_brightness(level):
    with pytest.raises(ValueError):
        PayloadGenerator().get_brightness_payload(level)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["static", "sound", "effect"])
async def test_brightness_only_preserves_mode_and_colour(mode):
    light = FakeLight()
    if mode == "sound":
        light.settings.experimental_music = True
        await light.async_set_control("microphone", True)
    elif mode == "effect":
        await light.set_effect("7-Color Fade")
    before = (light._music_active, light.effect, light.rgb_color, light.is_on)
    light.frames.clear()
    await light.async_turn_on(brightness=25)
    assert [frame[4] for frame in light.frames] == [CommandType.LIGHT]
    assert light.frames[0][6] == 9
    assert light.brightness == 25
    assert (light._music_active, light.effect, light.rgb_color, light.is_on) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["colour", "off", "effect"])
async def test_combined_or_power_on_applies_standalone_brightness(case):
    light = FakeLight()
    kwargs = {"brightness": 51}
    if case == "colour":
        kwargs["rgb_color"] = (12, 34, 56)
    elif case == "off":
        light._attr_is_on = False
    else:
        kwargs["effect"] = "7-Color Fade"
    await light.async_turn_on(**kwargs)
    assert [frame[4] for frame in light.frames] == [CommandType.RGB, CommandType.LIGHT]
    assert light.frames[-1][6] == 20
    assert light.is_on and light.brightness == 51


@pytest.mark.asyncio
async def test_failed_brightness_does_not_claim_success_or_change_mode():
    light = FakeLight()
    light._music_active = True
    light._attr_effect = MUSIC_EFFECT
    light._send_payload = AsyncMock(side_effect=ConnectionError("disconnected"))
    with pytest.raises(ConnectionError):
        await light.async_turn_on(brightness=25)
    assert light.brightness == 51 and light._music_active
    assert light.effect == MUSIC_EFFECT


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [-1, 256, True, 25.5])
async def test_invalid_brightness_does_not_cancel_timer(value):
    light = FakeLight()
    light.journal.begin(1000, {"is_on": True})
    light._timed_ownership = True
    with pytest.raises(ValueError):
        await light.async_turn_on(brightness=value)
    assert light.journal.active and light._timed_ownership and not light.frames


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmed", [True, False])
async def test_real_send_light_preserves_but_never_invents_static_confirmation(
    confirmed,
):
    light = IstripLight("AA:BB:CC:DD:EE:FF", KNOWN_CHAR_UUIDS[0], "Test", "entry")
    light._ensure_connected = AsyncMock()
    light._client = SimpleNamespace(is_connected=True, write_gatt_char=AsyncMock())
    light._confirmed_static = confirmed
    await light._send_payload(light._pg.get_brightness_payload(10), retries=1)
    assert light._confirmed_static is confirmed


@pytest.mark.asyncio
@pytest.mark.parametrize("sound", [False, True])
async def test_foreign_light_notification_only_changes_brightness_and_revokes_timer(
    sound,
):
    light = FakeLight()
    light._music_active = sound
    light._attr_effect = MUSIC_EFFECT if sound else None
    light._controls_changed = Mock()
    light.journal.begin(1000, {"is_on": True})
    light._timed_ownership = True
    frame = bytes.fromhex(light._pg.get_brightness_payload(10))
    before = (light.is_on, light.rgb_color, light.effect, light._music_active)
    light._handle_notification(0, bytearray(frame))
    assert light.brightness == 25
    assert (light.is_on, light.rgb_color, light.effect, light._music_active) == before
    assert not light._timed_ownership
    assert light.journal.record["status"] == "reconciliation_required"
    assert light._controls_changed.call_count == 2
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_own_brightness_echo_is_ignored():
    light = FakeLight()
    payload = light._pg.get_brightness_payload(10)
    light._remember_echo(payload)
    light._handle_notification(0, bytearray.fromhex(payload))
    assert light.brightness == 51


@pytest.mark.asyncio
async def test_brightness_failure_preserves_uncertain_timer_record():
    light = FakeLight()
    light.journal.begin(1000, {"is_on": True})
    light._timed_ownership = True
    light._send_payload = AsyncMock(side_effect=ConnectionError("disconnected"))
    with pytest.raises(ConnectionError):
        await light.async_turn_on(brightness=25)
    assert not light._timed_ownership
    assert light.journal.record["status"] == "reconciliation_required"
    assert light.brightness == 51
