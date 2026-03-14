"""The iStrip+ BLE integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN

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
