"""The iStrip+ BLE integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, OTA_WRITE_CHAR_UUID

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["light"]

CONF_ENTITY_ID = "entity_id"
CONF_EFFECT = "effect"
CONF_SPEED = "speed"

SERVICE_SET_EFFECT = "set_effect"
SERVICE_SET_SPEED = "set_speed"

SET_EFFECT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
        vol.Required(CONF_EFFECT): cv.string,
        vol.Optional(CONF_SPEED): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)

SET_SPEED_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
        vol.Required(CONF_SPEED): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
    }
)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old config entry."""
    if entry.version < 3:
        # Entries created before v3 could have the OTA (firmware update)
        # characteristic stored as the write characteristic. Writes to it are
        # accepted and silently discarded by the device, so the light never
        # responds. Drop the stored value and let the integration re-discover
        # a real control characteristic on next connect.
        # See docs/ble-protocol.md.
        data = dict(entry.data)
        stored = data.get("char_uuid") or ""

        if stored.lower() == OTA_WRITE_CHAR_UUID:
            del data["char_uuid"]
            _LOGGER.info(
                "Clearing stored OTA characteristic %s for %s; a control "
                "characteristic will be re-discovered on the next connection",
                stored,
                data.get("address"),
            )

        hass.config_entries.async_update_entry(entry, data=data, version=3)

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iStrip from a config entry."""
    entry.runtime_data = entry.data
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def async_set_effect_service(call: ServiceCall) -> None:
        """Handle the set_effect service call."""
        entity_id = call.data[CONF_ENTITY_ID]
        effect = call.data[CONF_EFFECT]
        speed = call.data.get(CONF_SPEED)

        component = hass.data.get("light")
        if component is None:
            return

        entity = component.get_entity(entity_id)
        if entity is None:
            return

        await entity.set_effect(effect, speed)

    async def async_set_speed_service(call: ServiceCall) -> None:
        """Handle the set_speed service call."""
        entity_id = call.data[CONF_ENTITY_ID]
        speed = call.data[CONF_SPEED]

        component = hass.data.get("light")
        if component is None:
            return

        entity = component.get_entity(entity_id)
        if entity is None:
            return

        await entity.set_speed(speed)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_EFFECT,
        async_set_effect_service,
        schema=SET_EFFECT_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_SPEED,
        async_set_speed_service,
        schema=SET_SPEED_SCHEMA,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.services.async_remove(DOMAIN, SERVICE_SET_EFFECT)
    hass.services.async_remove(DOMAIN, SERVICE_SET_SPEED)

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
