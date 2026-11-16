"""The iStrip+ BLE integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import OTA_WRITE_CHAR_UUID

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["light", "number", "select", "switch"]


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
    entry.runtime_data = {}
    # The light owns the only connection; controls reference that same object.
    await hass.config_entries.async_forward_entry_setups(entry, ["light"])
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS[1:])

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Entity-platform services are HA-managed across all loaded config entries.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
