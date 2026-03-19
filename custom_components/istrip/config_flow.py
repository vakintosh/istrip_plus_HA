"""Config flow for iStrip+ BLE integration."""

from __future__ import annotations

import logging
from typing import Any

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME

from .const import DOMAIN, KNOWN_CHAR_UUIDS

_LOGGER = logging.getLogger(__name__)


class IstripConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iStrip+ BLE."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._char_uuid: str | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle Bluetooth discovery."""
        self._discovery_info = discovery_info
        self._char_uuid = await self._discover_char_uuid(discovery_info.address)
        return await self.async_step_bluetooth_confirm()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user step."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            self._discovery_info = self._discovered_devices[address]

            char_uuid = await self._discover_char_uuid(address)
            if not char_uuid:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema(
                        {
                            vol.Required(CONF_ADDRESS): vol.In(
                                {
                                    addr: info.name
                                    for addr, info in self._discovered_devices.items()
                                }
                            )
                        }
                    ),
                    errors={"address": "no_valid_char_found"},
                )

            self._char_uuid = char_uuid
            return await self.async_step_bluetooth_confirm()

        current_addresses = self._async_current_ids()
        for discovery_info in async_discovered_service_info(self.hass, False):
            address = discovery_info.address
            if address in current_addresses or address in self._discovered_devices:
                continue
            if not discovery_info.name:
                continue
            self._discovered_devices[address] = discovery_info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        device_list = {
            address: info.name for address, info in self._discovered_devices.items()
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(device_list)}),
        )

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the Bluetooth device."""
        assert self._discovery_info is not None
        discovery_info = self._discovery_info

        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            return self.async_create_entry(
                title=discovery_info.name,
                data={
                    CONF_ADDRESS: discovery_info.address.upper(),
                    CONF_NAME: discovery_info.name,
                    "char_uuid": self._char_uuid,
                },
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({}),
        )

    async def _discover_char_uuid(self, address: str) -> str | None:
        """Connect to BLE device and find a writable characteristic UUID."""
        try:
            _LOGGER.debug("Connecting to %s", address)
            device = BLEDevice(address, "iStrip", {})
            client = await establish_connection(
                BleakClientWithServiceCache,
                device,
                "iStrip",
                max_attempts=3,
            )
            try:
                _LOGGER.debug("Connected, accessing services")

                services = client.services
                writable_uuids: list[str] = []

                for service in services:
                    for char in service.characteristics:
                        _LOGGER.debug(
                            "Char: %s - Properties: %s",
                            char.uuid,
                            char.properties,
                        )
                        if (
                            "write" in char.properties
                            or "write-without-response" in char.properties
                        ):
                            writable_uuids.append(str(char.uuid))

                # Prioritize known iStrip characteristic UUIDs
                for known_uuid in KNOWN_CHAR_UUIDS:
                    if known_uuid in writable_uuids:
                        _LOGGER.debug(
                            "Found known characteristic UUID: %s", known_uuid
                        )
                        return known_uuid

                # Fall back to the first writable characteristic
                if writable_uuids:
                    _LOGGER.debug(
                        "Using first writable characteristic: %s", writable_uuids[0]
                    )
                    return writable_uuids[0]

            finally:
                await client.disconnect()
        except Exception:
            _LOGGER.warning("Could not discover characteristics for %s", address)
        return None
