"""Exercise native entity-service dispatch using the target HA runtime."""

import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import EntityPlatform

from custom_components.istrip import async_setup_entry, async_unload_entry
from custom_components.istrip import light as light_platform


@pytest.mark.asyncio
async def test_services_scope_to_istrip_and_support_multiple_entries(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    platform = EntityPlatform(
        hass=hass,
        logger=logging.getLogger(__name__),
        domain="light",
        platform_name="istrip",
        platform=light_platform,
        scan_interval=timedelta(seconds=30),
        entity_namespace=None,
    )
    lights = []
    for suffix in ("01", "02"):
        entry = SimpleNamespace(
            data={"address": f"AA:BB:CC:DD:EE:{suffix}"},
            entry_id=f"entry{suffix}",
            runtime_data={},
        )
        with patch.object(
            light_platform, "async_get_current_platform", return_value=platform
        ):
            await light_platform.async_setup_entry(hass, entry, Mock())
        light = entry.runtime_data["light"]
        light.hass = hass
        light.entity_id = f"light.strip{suffix}"
        light.platform = platform
        light.set_effect = AsyncMock()
        light.set_speed = AsyncMock()
        platform.domain_platform_entities[light.entity_id] = light
        hass.states.async_set(light.entity_id, "on")
        lights.append(light)

    for light in lights:
        await hass.services.async_call(
            "istrip",
            "set_effect",
            {"entity_id": light.entity_id, "effect": "7-Color Fade", "speed": 20},
            blocking=True,
        )
        light.set_effect.assert_awaited_once_with("7-Color Fade", 20)

    # An unrelated light exists, but is not in this platform's entity collection.
    hass.states.async_set("light.unrelated", "on")
    await hass.services.async_call(
        "istrip",
        "set_speed",
        {"entity_id": "light.unrelated", "speed": 50},
        blocking=True,
    )
    for light in lights:
        light.set_speed.assert_not_awaited()

    # Simulate unload of one entry: no global service teardown is allowed.
    platform.domain_platform_entities.pop(lights[0].entity_id)
    await hass.services.async_call(
        "istrip",
        "set_speed",
        {"entity_id": lights[1].entity_id, "speed": 50},
        blocking=True,
    )
    lights[1].set_speed.assert_awaited_once_with(speed=50)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            "istrip",
            "set_speed",
            {"entity_id": lights[1].entity_id, "speed": 101},
            blocking=True,
        )


@pytest.mark.asyncio
async def test_setup_orders_light_before_controls_and_unload_keeps_services():
    forward = AsyncMock()
    unload = AsyncMock(return_value=True)
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_forward_entry_setups=forward, async_unload_platforms=unload
        )
    )
    entry = SimpleNamespace(runtime_data=None)
    assert await async_setup_entry(hass, entry)
    assert [args.args[1] for args in forward.await_args_list] == [
        ["light"],
        ["number", "select", "switch"],
    ]
    assert await async_unload_entry(hass, entry)
    unload.assert_awaited_once()
