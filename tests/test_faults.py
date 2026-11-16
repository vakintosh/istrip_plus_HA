"""Fault injection for control transitions; never uses a live radio or HA box."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.istrip.controls import MUSIC_EFFECT
from custom_components.istrip.light import RestoreEntity
from custom_components.istrip.const import KNOWN_CHAR_UUIDS
from custom_components.istrip.light import IstripLight
from test_controls import TestLight as FakeLight


@pytest.fixture
def light():
    return FakeLight()


@pytest.fixture
def timer():
    with patch("custom_components.istrip.controller.async_call_later") as timer:
        yield timer


@pytest.mark.asyncio
async def test_microphone_off_does_not_power_on_an_off_strip(light):
    await light.async_turn_off()
    count = len(light.frames)
    await light.async_set_control("microphone", False)
    assert not light.is_on
    assert len(light.frames) == count


@pytest.mark.asyncio
async def test_microphone_off_after_ambiguous_write_sends_static(light):
    light._music_active = False
    light._confirmed_static = False
    await light.async_set_control("microphone", False)
    assert light.frames[-1][4:7] == bytes([2, 1, 0])


@pytest.mark.asyncio
async def test_experimental_opt_out_preserves_off_state(light):
    light._attr_is_on = False
    light._music_active = True
    await light.async_set_control("experimental_music", False)
    assert not light.is_on
    assert light.frames[-1][10] == 0


@pytest.mark.asyncio
async def test_start_storage_failure_keeps_uncertain_record_without_write(light, timer):
    light.settings.experimental_music = True
    light._store.async_save = AsyncMock(side_effect=OSError("disk full"))
    with pytest.raises(OSError):
        await light.async_start_timed_music(10)
    assert not light.frames and not light._timed_ownership
    assert light.journal.record["status"] == "reconciliation_required"
    timer.assert_not_called()


@pytest.mark.asyncio
async def test_manual_notification_during_initial_save_prevents_music(light, timer):
    light.settings.experimental_music = True
    save = light._store.async_save
    first = True

    async def interrupted(value):
        nonlocal first
        if first:
            first = False
            light._foreign_notification()
        await save(value)

    light._store.async_save = interrupted
    with pytest.raises(ConnectionError, match="changed"):
        await light.async_start_timed_music(10)
    await asyncio.sleep(0)
    assert not light.frames and not light._timed_ownership
    assert light.journal.record["status"] == "reconciliation_required"
    timer.assert_not_called()


@pytest.mark.asyncio
async def test_expiry_storage_failure_prevents_restore_and_revokes_owner(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    count = len(light.frames)
    light._store.async_save = AsyncMock(side_effect=OSError("disk full"))
    await light._return_due(None)
    assert len(light.frames) == count
    assert light.journal.record["status"] == "reconciliation_required"
    assert not light._timed_ownership and not light._restoring


@pytest.mark.asyncio
async def test_expiry_journal_clear_failure_keeps_snapshot(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    light._store.async_save = AsyncMock(side_effect=[None, OSError("disk full"), None])
    await light._return_due(None)
    assert not light._music_active
    assert light.journal.record["status"] == "reconciliation_required"
    assert light.journal.record["snapshot"]["rgb"] == [0, 0, 255]
    assert not light._timed_ownership


@pytest.mark.asyncio
async def test_cancelled_expiry_keeps_uncertain_record_and_propagates(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    light._send_payload = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await light._return_due(None)
    assert light.journal.record["status"] == "reconciliation_required"
    assert not light._timed_ownership and not light._restoring


@pytest.mark.asyncio
async def test_manual_clear_storage_failure_preserves_recovery(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    light._store.async_save = AsyncMock(side_effect=[None, OSError("disk full")])
    with pytest.raises(OSError):
        await light.async_turn_on(rgb_color=(20, 30, 40))
    assert light.journal.record["status"] == "reconciliation_required"
    assert not light._timed_ownership


@pytest.mark.asyncio
async def test_restored_music_stays_marked_dynamic_without_restart_command(light):
    light._confirmed_static = False
    light.async_get_last_state = AsyncMock(
        return_value=SimpleNamespace(
            state="on",
            attributes={
                "rgb_color": [0, 0, 255],
                "brightness": 51,
                "effect": MUSIC_EFFECT,
            },
        )
    )
    light.async_get_last_extra_data = AsyncMock(return_value=None)
    light._load_controls = AsyncMock()
    light._ensure_connected = AsyncMock()
    with (
        patch.object(RestoreEntity, "async_added_to_hass", new=AsyncMock()),
        patch("custom_components.istrip.light.Debouncer", return_value=Mock()),
        patch(
            "custom_components.istrip.light.async_register_callback",
            return_value=lambda: None,
        ),
    ):
        await light.async_added_to_hass()
    assert not light.frames
    assert light.effect == MUSIC_EFFECT
    assert light._music_active and not light._confirmed_static


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_frame", [1, 2])
async def test_real_send_path_handles_partial_microphone_failure(fail_frame):
    light = IstripLight("AA:BB:CC:DD:EE:FF", KNOWN_CHAR_UUIDS[0], "Test", "test_entry")
    light.settings.experimental_music = True
    light._attr_is_on = True
    light._attr_brightness = 51
    light._attr_rgb_color = (0, 0, 255)
    light._controls_changed = Mock()
    light._ensure_connected = AsyncMock()
    frames = []

    async def write(_characteristic, payload, **_kwargs):
        frames.append(light._pg.decrypt_payload(payload))
        if len(frames) >= fail_frame:
            raise ConnectionError("simulated BLE disconnect")

    light._client = SimpleNamespace(is_connected=True, write_gatt_char=write)
    with patch("custom_components.istrip.light.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(ConnectionError):
            await light.async_set_control("microphone", True)
    assert not light.available and not light._music_active
    assert not light._confirmed_static
    assert len(frames) == fail_frame + 1  # two transport attempts on failed frame
    assert all(frame[4] in (2, 3) for frame in frames)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,value",
    [
        ("sensitivity", -1),
        ("sensitivity", 101),
        ("sensitivity", True),
        ("music_style", "unknown"),
        ("rgb_order", "XYZ"),
        ("microphone", 1),
        ("experimental_music", "yes"),
        ("unknown", True),
    ],
)
async def test_invalid_control_does_not_cancel_timed_ownership(
    light, timer, key, value
):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    count = len(light.frames)
    with pytest.raises(ValueError):
        await light.async_set_control(key, value)
    assert light.journal.active and light._timed_ownership
    assert len(light.frames) == count


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["turn_on", "set_effect"])
async def test_rejected_effect_does_not_cancel_timed_ownership(light, timer, command):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    with pytest.raises(ValueError):
        if command == "turn_on":
            await light.async_turn_on(effect="unknown")
        else:
            await light.set_effect("unknown")
    assert light.journal.active and light._timed_ownership


@pytest.mark.asyncio
async def test_foreign_change_during_expiry_save_prevents_restore(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    save = light._store.async_save
    first = True

    async def interrupted(value):
        nonlocal first
        if first:
            first = False
            light._foreign_notification()
        await save(value)

    count = len(light.frames)
    light._store.async_save = interrupted
    await light._return_due(None)
    await asyncio.sleep(0)
    assert len(light.frames) == count
    assert light.journal.record["status"] == "reconciliation_required"
    assert not light._timed_ownership
