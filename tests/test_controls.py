"""Offline protocol/control tests: no radios, credentials or live HA writes."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.istrip.const import CONTROL_SERVICE_UUID, KNOWN_CHAR_UUIDS
from custom_components.istrip.ble_helpers import find_notify_char
from custom_components.istrip.config_flow import IstripConfigFlow
from custom_components.istrip.controls import (
    MUSIC_EFFECT,
    MUSIC_STYLES,
    RGB_ORDERS,
    ControlSettings,
    ReturnJournal,
    map_rgb,
)
from custom_components.istrip.light import IstripLight
from custom_components.istrip.number import IstripNumber
from custom_components.istrip.payload_generator import CommandType, PayloadGenerator
from custom_components.istrip.select import IstripSelect
from custom_components.istrip.switch import IstripSwitch

ADDRESS = "AA:BB:CC:DD:EE:FF"


class MemoryStore:
    def __init__(self):
        self.saved = None

    async def async_save(self, value):
        self.saved = deepcopy(value)


class TestLight(IstripLight):
    """Exercise real light/control methods with only the BLE transport replaced."""

    __test__ = False

    def __init__(self):
        super().__init__(ADDRESS, KNOWN_CHAR_UUIDS[0], "Test strip", "test_entry")
        self.frames = []
        self._store = MemoryStore()
        self._controls_changed = Mock()
        self.hass = SimpleNamespace(async_create_task=asyncio.create_task)
        self._confirmed_static = True
        self._attr_brightness = 51
        self._attr_is_on = True
        self._attr_rgb_color = (0, 0, 255)

    async def _send_payload(self, payload, **kwargs):
        self.frames.append(self._pg.decrypt_payload(bytes.fromhex(payload)))
        self._confirmed_static = self.frames[-1][4:7] == bytes([2, 1, 0])


@pytest.fixture
def light():
    return TestLight()


@pytest.mark.parametrize("style,status", MUSIC_STYLES.items())
@pytest.mark.parametrize("sensitivity", [0, 1, 50, 100])
def test_microphone_frame(style, status, sensitivity):
    pg = PayloadGenerator()
    frame = pg.decrypt_payload(
        bytes.fromhex(pg.get_microphone_payload(style, sensitivity))
    )
    assert frame == bytes([0x54, 0x52, 0, 0x57, 3, 1, status, 0, sensitivity] + [0] * 7)


@pytest.mark.parametrize("value", [-1, 101, True, 1.5, "50"])
def test_invalid_sensitivity(value):
    with pytest.raises(ValueError):
        PayloadGenerator().get_microphone_payload("Soft", value)


def test_invalid_style():
    with pytest.raises(ValueError):
        PayloadGenerator().get_microphone_payload("Phone microphone", 100)


def test_soft_ciphertext_vector():
    # Independently generated with OpenSSL AES-128-ECB, no padding.
    assert (
        PayloadGenerator().get_microphone_payload("Soft", 100)
        == "003bd25c12bd2774693d5a47552185b2"
    )


@pytest.mark.parametrize("order", RGB_ORDERS)
def test_rgb_order_roundtrip(order):
    rgb = (12, 34, 56)
    assert map_rgb(map_rgb(rgb, order), order, inverse=True) == rgb


def test_settings_validate_storage():
    settings = ControlSettings.from_dict(
        {
            "sensitivity": -1,
            "experimental_music": "true",
            "music_style": "bad",
            "rgb_order": "bad",
        }
    )
    assert settings == ControlSettings()
    assert not settings.experimental_music
    assert ControlSettings.from_dict(
        ControlSettings(True, 50, "Classic", "BGR").as_dict()
    ) == ControlSettings(True, 50, "Classic", "BGR")


@pytest.mark.parametrize("status", ["active", "restoring", "reconciliation_required"])
def test_restart_never_recovers_ownership(status):
    journal = ReturnJournal()
    journal.load({"status": status, "deadline": 1000, "snapshot": {"is_on": True}})
    assert not journal.active
    assert journal.record["status"] == "reconciliation_required"


@pytest.mark.asyncio
async def test_music_opt_in_and_static_return(light):
    with pytest.raises(ValueError):
        await light.async_set_control("microphone", True)
    assert not light.frames
    await light.async_set_control("experimental_music", True)
    assert not light.frames
    await light.async_set_control("microphone", True)
    assert [frame[4] for frame in light.frames] == [CommandType.RGB, CommandType.RHYTHM]
    assert light.effect == MUSIC_EFFECT
    await light.async_set_control("microphone", False)
    assert light.frames[-1][4] == CommandType.RGB
    assert not light._music_active and light.effect is None
    assert light.rgb_color == (0, 0, 255)


@pytest.mark.asyncio
async def test_direct_rgb_exits_music(light):
    light.settings.experimental_music = True
    await light.async_set_control("microphone", True)
    await light.async_turn_on(rgb_color=(1, 2, 3), brightness=40)
    assert not light._music_active and light.effect is None
    assert light.frames[-1][7:10] == bytes([1, 2, 3])


@pytest.mark.asyncio
async def test_sensitivity_live_and_opt_out(light):
    light.settings.experimental_music = True
    await light.async_set_control("microphone", True)
    await light.async_set_control("sensitivity", 40)
    assert light.frames[-1][8] == 40
    await light.async_set_control("experimental_music", False)
    assert light.frames[-1][4] == CommandType.RGB
    assert not light._music_active


@pytest.mark.asyncio
async def test_rgb_permutation_and_advanced_entity(light):
    await light.async_set_control("rgb_order", "BGR")
    await light.async_turn_on(rgb_color=(1, 2, 3))
    assert light.frames[-1][7:10] == bytes([3, 2, 1])
    entity = IstripSelect(light, "rgb_order", "RGB order")
    assert not entity.entity_registry_enabled_default
    assert entity.current_option == "BGR"


@pytest.mark.asyncio
async def test_speed_pending_and_debounced_callback_no_deadlock(light):
    await light.set_speed(30)
    assert light._pending_speed == 30
    await light.set_effect("7-Color Fade")
    assert light._speed_for("7-Color Fade") == 30
    light._speed_debouncer = SimpleNamespace(async_call=light._async_send_active_effect)
    await asyncio.wait_for(light.set_speed(40), 1)
    assert light.frames[-1][11] == 40


@pytest.mark.asyncio
async def test_native_controls_use_same_light(light):
    number = IstripNumber(light, "sensitivity", "Sensitivity")
    switch = IstripSwitch(light, "experimental_music", "Experimental")
    select = IstripSelect(light, "music_style", "Music")
    await number.async_set_native_value(55.0)
    await select.async_select_option("Classic")
    await switch.async_turn_on()
    assert number.native_value == 55 and select.current_option == "Classic"
    assert switch.is_on and not light.frames
    assert number.device_info == light.device_info
    assert number.unique_id == f"{light.unique_id}_sensitivity"


@pytest.fixture
def timer():
    with patch("custom_components.istrip.controller.async_call_later") as timer:
        yield timer


@pytest.mark.asyncio
async def test_timed_return_success(light, timer):
    light.settings.experimental_music = True
    before = light.rgb_color
    await light.async_start_timed_music(10)
    assert light.journal.active
    assert light._store.saved["return"]["snapshot"]["rgb"] == [0, 0, 255]
    timer.assert_called_once()
    await light._return_due(None)
    assert light.journal.record is None and not light._music_active
    assert light.rgb_color == before and light.brightness == 51


@pytest.mark.asyncio
async def test_timer_from_off_restores_off(light, timer):
    light.settings.experimental_music = True
    await light.async_turn_off()
    await light.async_start_timed_music(1)
    await light._return_due(None)
    assert not light.is_on
    assert light.frames[-1][10] == 0


@pytest.mark.asyncio
async def test_manual_override_cancels_without_restore(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    await light.async_turn_on(rgb_color=(255, 0, 0))
    writes = len(light.frames)
    await light._return_due(None)
    assert light.rgb_color == (255, 0, 0)
    assert len(light.frames) == writes and not light.journal.record


@pytest.mark.asyncio
async def test_failed_manual_override_keeps_evidence(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    light._send_payload = AsyncMock(side_effect=ConnectionError("ambiguous write"))
    with pytest.raises(ConnectionError):
        await light.async_turn_on(rgb_color=(255, 0, 0))
    assert light.journal.record["status"] == "reconciliation_required"


@pytest.mark.asyncio
async def test_foreign_notification_revokes_timer(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    light._foreign_notification()
    await asyncio.sleep(0)
    writes = len(light.frames)
    await light._return_due(None)
    assert len(light.frames) == writes
    assert light.journal.record["status"] == "reconciliation_required"


@pytest.mark.asyncio
async def test_timer_failed_start_and_return_preserve_journal(light, timer):
    light.settings.experimental_music = True
    light._send_payload = AsyncMock(side_effect=ConnectionError("lost"))
    with pytest.raises(ConnectionError):
        await light.async_start_timed_music(10)
    assert light.journal.record["status"] == "reconciliation_required"
    light._send_payload.assert_awaited_once()
    timer.assert_not_called()


@pytest.mark.asyncio
async def test_failed_return_has_no_retry(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    light._send_payload = AsyncMock(side_effect=ConnectionError("lost"))
    await light._return_due(None)
    assert light.journal.record["status"] == "reconciliation_required"
    light._send_payload.assert_awaited_once()


@pytest.mark.asyncio
async def test_reload_retains_record_without_rescheduling(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    await light._unload_controls()
    assert light._store.saved["return"]["status"] == "reconciliation_required"
    new_journal = ReturnJournal()
    new_journal.load(light._store.saved["return"])
    assert not new_journal.active


@pytest.mark.parametrize("duration", [0, -1, 86401, True, 1.5])
@pytest.mark.asyncio
async def test_invalid_timer(light, duration):
    with pytest.raises(ValueError):
        await light.async_start_timed_music(duration)
    assert not light.frames


@pytest.mark.asyncio
async def test_restore_state_is_not_hardware_confirmation(light):
    light.settings.experimental_music = True
    light._confirmed_static = False
    with pytest.raises(ValueError, match="explicit static"):
        await light.async_start_timed_music(10)


@pytest.mark.asyncio
async def test_concurrent_commands_are_serial(light):
    light.settings.experimental_music = True
    await asyncio.gather(
        light.async_set_control("microphone", True),
        light.async_turn_on(rgb_color=(255, 0, 0)),
    )
    assert [f[4] for f in light.frames] == [2, 3, 2]
    assert light.rgb_color == (255, 0, 0) and not light._music_active


def test_control_only_discovery_and_stored_uuid():
    light = IstripLight(ADDRESS, "0000ae01-0000-1000-8000-00805f9b34fb", "Test", "id")
    assert light._char_uuid is None
    writable = SimpleNamespace(
        uuid=KNOWN_CHAR_UUIDS[0], properties=["write-without-response"]
    )
    light._client = SimpleNamespace(
        is_connected=True,
        services=[
            SimpleNamespace(
                uuid="0000ae00-0000-1000-8000-00805f9b34fb", characteristics=[writable]
            )
        ],
    )
    assert light._discover_char_uuid_from_services() is None
    light._client.services.append(
        SimpleNamespace(uuid=CONTROL_SERVICE_UUID, characteristics=[writable])
    )
    assert light._discover_char_uuid_from_services() == KNOWN_CHAR_UUIDS[0]


@pytest.mark.asyncio
async def test_write_boundary_rejects_unknown_characteristic():
    light = IstripLight(ADDRESS, None, "Test", "id")
    light._ensure_connected = AsyncMock()
    light._client = SimpleNamespace(is_connected=True, write_gatt_char=AsyncMock())
    light._char_uuid = "unknown"
    with pytest.raises(ValueError):
        await light._send_payload(light._pg.send_led_off(), retries=1)
    light._client.write_gatt_char.assert_not_awaited()


@pytest.mark.asyncio
async def test_automatic_return_cannot_reconnect():
    light = IstripLight(ADDRESS, KNOWN_CHAR_UUIDS[0], "Test", "id")
    light._restoring = True
    light._ensure_connected = AsyncMock()
    with pytest.raises(ConnectionError):
        await light._send_payload(light._pg.send_led_off())
    light._ensure_connected.assert_not_awaited()


def test_notify_never_uses_ota_or_unknown():
    ota = SimpleNamespace(
        uuid="0000ae02-0000-1000-8000-00805f9b34fb", properties=["notify"]
    )
    write = SimpleNamespace(
        uuid=KNOWN_CHAR_UUIDS[0], properties=["write-without-response"]
    )
    service = SimpleNamespace(uuid=CONTROL_SERVICE_UUID, characteristics=[write, ota])
    client = SimpleNamespace(services=[service])
    assert find_notify_char(client, KNOWN_CHAR_UUIDS[0]) is None
    service.characteristics.append(
        SimpleNamespace(
            uuid="0000ac51-1212-efde-1523-785fedbeda25", properties=["notify"]
        )
    )
    assert (
        find_notify_char(client, KNOWN_CHAR_UUIDS[0])
        == "0000ac51-1212-efde-1523-785fedbeda25"
    )
    assert find_notify_char(client, ota.uuid) is None


@pytest.mark.asyncio
async def test_config_flow_never_probes_ota():
    flow = IstripConfigFlow()
    flow.hass = Mock()
    client = SimpleNamespace(
        services=[
            SimpleNamespace(
                uuid="0000ae00-0000-1000-8000-00805f9b34fb",
                characteristics=[
                    SimpleNamespace(
                        uuid="0000ae01-0000-1000-8000-00805f9b34fb",
                        properties=["write"],
                    )
                ],
            )
        ],
        disconnect=AsyncMock(),
    )
    flow._probe_for_write_char = AsyncMock()
    with (
        patch(
            "custom_components.istrip.config_flow.async_ble_device_from_address",
            return_value=Mock(),
        ),
        patch(
            "custom_components.istrip.config_flow.establish_connection",
            new=AsyncMock(return_value=client),
        ),
    ):
        assert await flow._discover_char_uuid(ADDRESS) is None
    flow._probe_for_write_char.assert_not_awaited()
    client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_join_failure_never_marks_connected():
    light = IstripLight(ADDRESS, KNOWN_CHAR_UUIDS[0], "Test", "id")
    light.hass = Mock()
    write = SimpleNamespace(
        uuid=KNOWN_CHAR_UUIDS[0], properties=["write-without-response"]
    )
    client = SimpleNamespace(
        is_connected=True,
        services=[SimpleNamespace(uuid=CONTROL_SERVICE_UUID, characteristics=[write])],
        write_gatt_char=AsyncMock(side_effect=ConnectionError("join failed")),
        disconnect=AsyncMock(),
    )
    light._persist_char_uuid = Mock()
    with (
        patch(
            "custom_components.istrip.light.async_ble_device_from_address",
            return_value=Mock(),
        ),
        patch(
            "custom_components.istrip.light.establish_connection",
            new=AsyncMock(return_value=client),
        ),
    ):
        await light._ensure_connected()
    assert not light._connected and not light.available
    client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_notification_mapping_echo_and_foreign_timer(light, timer):
    light.schedule_update_ha_state = Mock()
    light.settings.rgb_order = "BGR"
    frame = light._pg.get_rgb_payload(3, 2, 1, 20)
    light._handle_notification(0, bytearray.fromhex(frame))
    assert light.rgb_color == (1, 2, 3)
    light._remember_echo(frame)
    light._attr_rgb_color = (4, 5, 6)
    light._handle_notification(0, bytearray.fromhex(frame))
    assert light.rgb_color == (4, 5, 6)
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)
    foreign = light._pg.get_rgb_payload(4, 3, 2, 20)
    light._handle_notification(0, bytearray.fromhex(foreign))
    await asyncio.sleep(0)
    assert not light.journal.active
    assert light.rgb_color == (2, 3, 4) and not light._music_active


@pytest.mark.asyncio
async def test_cancel_discards_recovery_without_hardware_write(light):
    light.journal.load(
        {"deadline": 1, "snapshot": {"is_on": False}, "status": "active"}
    )
    await light.async_cancel_timed_return()
    assert light.journal.record is None and not light.frames


@pytest.mark.asyncio
async def test_restore_save_happens_before_first_write(light, timer):
    light.settings.experimental_music = True
    send = light._send_payload

    async def checked(payload):
        assert light._store.saved["return"]["snapshot"]["rgb"] == [0, 0, 255]
        await send(payload)

    light._send_payload = checked
    await light.async_start_timed_music(10)
    assert light.journal.active


@pytest.mark.asyncio
async def test_timer_lost_ownership_during_expiry_does_not_retry(light, timer):
    light.settings.experimental_music = True
    await light.async_start_timed_music(10)

    async def ambiguous(_payload):
        light._foreign_notification()

    light._send_payload = AsyncMock(side_effect=ambiguous)
    await light._return_due(None)
    await asyncio.sleep(0)
    assert light.journal.record["status"] == "reconciliation_required"
    light._send_payload.assert_awaited_once()


@pytest.mark.asyncio
async def test_storage_reload_never_schedules_or_writes(light, timer):
    record = {"status": "active", "deadline": 10, "snapshot": {"is_on": False}}
    store = SimpleNamespace(
        async_load=AsyncMock(
            return_value={
                "settings": ControlSettings(True, 40, "Classic", "BGR").as_dict(),
                "return": record,
            }
        ),
        async_save=AsyncMock(),
    )
    with patch("custom_components.istrip.controller.Store", return_value=store):
        await light._load_controls()
    assert light.settings.sensitivity == 40 and light.settings.rgb_order == "BGR"
    assert light.journal.record["status"] == "reconciliation_required"
    store.async_save.assert_awaited_once()
    timer.assert_not_called()
    assert not light.frames and not light._music_active


def test_external_music_is_never_reported_as_static(light):
    frame = light._pg.get_microphone_payload("Soft", 100)
    light._handle_notification(0, bytearray.fromhex(frame))
    assert light.effect == MUSIC_EFFECT and light._music_active
    assert not light._confirmed_static
