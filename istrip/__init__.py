# __init__.py

from homeassistant.core import HomeAssistant

async def async_setup_entry(hass: HomeAssistant, config_entry):
    """Set up the iStrip integration from a config entry."""
    return True

async def async_setup(hass: HomeAssistant, config: dict):
    """Set up the iStrip integration."""
    return True
