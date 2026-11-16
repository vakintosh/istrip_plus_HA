"""Permission is configuration, not a second sound-response switch."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.exceptions import ServiceValidationError

from custom_components.istrip.config_flow import IstripConfigFlow
from custom_components.istrip.options_flow import IstripOptionsFlow
from custom_components.istrip.switch import IstripSwitch, async_setup_entry
from test_controls import TestLight as FakeLight


def flow_for(light):
    flow = IstripConfigFlow.async_get_options_flow(None)
    flow.handler = "test_entry"
    entry = SimpleNamespace(runtime_data={"light": light}, options={"preserved": 1})
    flow.hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_get_known_entry=lambda key: entry)
    )
    return flow


@pytest.mark.asyncio
async def test_options_enable_persists_without_starting_music():
    light = FakeLight()
    flow = flow_for(light)
    assert isinstance(flow, IstripOptionsFlow)
    form = await flow.async_step_init()
    assert form["type"] == "form" and form["step_id"] == "init"
    result = await flow.async_step_init({"experimental_music": True})
    assert result["type"] == "create_entry"
    assert result["data"] == {"preserved": 1}
    assert light._store.saved["settings"]["experimental_music"]
    assert light.settings.experimental_music and not light._music_active
    assert not light.frames


@pytest.mark.asyncio
async def test_noop_options_does_not_cancel_timed_owner():
    light = FakeLight()
    light.settings.experimental_music = True
    light.journal.begin(1000, {"is_on": True})
    light._timed_ownership = True
    result = await flow_for(light).async_step_init({"experimental_music": True})
    assert result["type"] == "create_entry"
    assert light.journal.active and light._timed_ownership
    assert not light.frames


@pytest.mark.asyncio
async def test_options_disable_stops_music_without_powering_on_off_strip():
    light = FakeLight()
    light.settings.experimental_music = True
    await light.async_set_control("microphone", True)
    light._attr_is_on = False
    result = await flow_for(light).async_step_init({"experimental_music": False})
    assert result["type"] == "create_entry"
    assert not light._music_active and not light.settings.experimental_music
    assert not light.is_on
    assert light.frames[-1][4:7] == bytes([2, 1, 0])


@pytest.mark.asyncio
async def test_failed_optin_does_not_grant_permission():
    light = FakeLight()
    light._store.async_save = AsyncMock(side_effect=OSError("disk full"))
    result = await flow_for(light).async_step_init({"experimental_music": True})
    assert result["errors"] == {"base": "cannot_update"}
    assert not light.settings.experimental_music and not light.frames


@pytest.mark.asyncio
async def test_failed_optout_save_can_be_retried():
    light = FakeLight()
    light.settings.experimental_music = True
    await light.async_set_control("microphone", True)
    save = light._store.async_save
    light._store.async_save = AsyncMock(side_effect=OSError("disk full"))
    flow = flow_for(light)
    result = await flow.async_step_init({"experimental_music": False})
    assert result["errors"] == {"base": "cannot_update"}
    assert light.settings.experimental_music and light._music_active
    light._store.async_save = save
    result = await flow.async_step_init({"experimental_music": False})
    assert result["type"] == "create_entry"
    assert not light.settings.experimental_music and not light._music_active


@pytest.mark.asyncio
async def test_failed_optout_write_can_be_retried_even_when_permission_saved():
    light = FakeLight()
    light.settings.experimental_music = True
    await light.async_set_control("microphone", True)
    send = light._send_payload
    light._send_payload = AsyncMock(side_effect=ConnectionError("disconnected"))
    flow = flow_for(light)
    result = await flow.async_step_init({"experimental_music": False})
    assert result["errors"] == {"base": "cannot_update"}
    assert not light.settings.experimental_music and light._music_active
    light._send_payload = send
    result = await flow.async_step_init({"experimental_music": False})
    assert result["type"] == "create_entry"
    assert not light.settings.experimental_music and not light._music_active


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, "true", 1])
async def test_options_rejects_non_boolean_permission(invalid):
    light = FakeLight()
    result = await flow_for(light).async_step_init({"experimental_music": invalid})
    assert result["errors"] == {"base": "invalid_permission"}
    assert not light.settings.experimental_music and not light.frames


@pytest.mark.asyncio
async def test_options_requires_loaded_device():
    flow = flow_for(FakeLight())
    flow.config_entry.runtime_data = None
    result = await flow.async_step_init()
    assert result["type"] == "abort" and result["reason"] == "not_loaded"


@pytest.mark.asyncio
async def test_optout_blocks_without_writing_or_revoking_recovery():
    light = FakeLight()
    light.journal.begin(1000, {"is_on": True})
    light._timed_ownership = True
    for command in (
        light.async_set_control("microphone", True),
        light.async_start_timed_music(5),
    ):
        with pytest.raises(ServiceValidationError, match="Configure"):
            await command
        assert light.journal.active and light._timed_ownership
        assert not light.frames


def test_sound_switch_locked_until_allowed_but_can_always_stop():
    light = FakeLight()
    mic = IstripSwitch(light, "microphone", "Sound reactive")
    assert not mic.available
    light.settings.experimental_music = True
    assert mic.available
    light.settings.experimental_music = False
    light._music_active = True
    assert mic.available and mic.is_on


@pytest.mark.asyncio
@pytest.mark.parametrize("same_entry", [True, False])
async def test_migration_removes_only_this_entries_legacy_permission(same_entry):
    light = FakeLight()
    registry = Mock()
    registry.async_get_entity_id.return_value = "switch.old_permission"
    registry.async_get.return_value = SimpleNamespace(
        config_entry_id="test_entry" if same_entry else "other_entry"
    )
    entities = []
    entry = SimpleNamespace(runtime_data={"light": light}, entry_id="test_entry")
    with patch("custom_components.istrip.switch.er.async_get", return_value=registry):
        await async_setup_entry(None, entry, entities.extend)
    registry.async_get_entity_id.assert_called_once_with(
        "switch", "istrip", f"{light.unique_id}_experimental_music"
    )
    assert [entity.key for entity in entities] == ["microphone"]
    if same_entry:
        registry.async_remove.assert_called_once_with("switch.old_permission")
    else:
        registry.async_remove.assert_not_called()
