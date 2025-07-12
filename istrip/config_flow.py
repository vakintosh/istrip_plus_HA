from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.data_entry_flow import FlowResult
import voluptuous as vol
import logging
from bleak import BleakClient
from .const import DOMAIN
from typing import Any, Optional, Dict

_LOGGER = logging.getLogger(__name__)

class IstripConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._discovered_devices: Dict[str, BluetoothServiceInfoBleak] = {}
        self._discovery_info: Optional[BluetoothServiceInfoBleak] = None
        self._char_uuid: Optional[str] = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle Bluetooth discovery."""
        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial user step."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            self._discovery_info = self._discovered_devices[address]

            char_uuid = await self._discover_char_uuid(address)
            if not char_uuid:
                return self.async_show_form(
                    step_id="user",
                    data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(
                        {addr: info.name for addr, info in self._discovered_devices.items()}
                    )}),
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

        device_list = {address: info.name for address, info in self._discovered_devices.items()}

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(device_list)}),
        )

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
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
            _LOGGER.debug(f"Connecting to {address}")
            async with BleakClient(address) as client:
                _LOGGER.debug("Connected, accessing services...")

                services = client.services

                for service in services:
                    for char in service.characteristics:
                        _LOGGER.debug(f"Char: {char.uuid} - Properties: {char.properties}")
                        if (
                            "write" in char.properties
                            or "write-without-response" in char.properties
                        ):
                            return str(char.uuid)
        except Exception as e:
            _LOGGER.warning(f"Could not discover characteristics: {e}")
        return None