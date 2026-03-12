from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.config_entries import ConfigEntry
import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from .const import DOMAIN

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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up iStrip from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry.data
    await hass.config_entries.async_forward_entry_setups(entry, ["light"])

    # Register custom services
    async def async_set_effect_service(call: ServiceCall):
        """Handle the set_effect service call."""
        entity_id = call.data[CONF_ENTITY_ID]
        effect = call.data[CONF_EFFECT]
        speed = call.data.get(CONF_SPEED)

        # Find the light entity
        component = hass.data.get("light")
        if component is None:
            return

        entity = component.get_entity(entity_id)
        if entity is None:
            return

        # Call the entity method
        await entity.set_effect(effect, speed)

    async def async_set_speed_service(call: ServiceCall):
        """Handle the set_speed service call."""
        entity_id = call.data[CONF_ENTITY_ID]
        speed = call.data[CONF_SPEED]

        # Find the light entity
        component = hass.data.get("light")
        if component is None:
            return

        entity = component.get_entity(entity_id)
        if entity is None:
            return

        # Call the entity method
        await entity.set_speed(speed)

    # Register services
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


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    # Unregister services
    hass.services.async_remove(DOMAIN, SERVICE_SET_EFFECT)
    hass.services.async_remove(DOMAIN, SERVICE_SET_SPEED)

    return await hass.config_entries.async_unload_platforms(entry, ["light"])
