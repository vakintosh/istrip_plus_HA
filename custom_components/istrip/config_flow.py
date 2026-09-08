"""Config flow for iStrip+ BLE integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME

from .ble_helpers import find_notify_char
from .const import DOMAIN, KNOWN_CHAR_UUIDS
from .payload_generator import PayloadGenerator

_LOGGER = logging.getLogger(__name__)

# How long to wait for the device to echo the join-group handshake back as
# a notification before giving up on a candidate write characteristic and
# trying the next one.
PROBE_TIMEOUT = 2.0


class IstripConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iStrip+ BLE."""

    VERSION = 3

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
        """Find the device's real write characteristic, probing if needed.

        Writes never error even when silently ignored, so presence alone
        can't tell candidates apart -- see `_probe_for_write_char`.
        """
        try:
            ble_device = async_ble_device_from_address(
                self.hass, address, connectable=True
            )
            if ble_device is None:
                _LOGGER.warning(
                    "No connectable Bluetooth scanner currently sees %s", address
                )
                return None

            client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                "iStrip",
                max_attempts=3,
            )
            try:
                writable_uuids: list[str] = []
                for service in client.services:
                    for char in service.characteristics:
                        if (
                            "write" in char.properties
                            or "write-without-response" in char.properties
                        ):
                            writable_uuids.append(str(char.uuid))

                if not writable_uuids:
                    return None

                # Try known-good UUIDs first, then anything else writable.
                candidates = [u for u in KNOWN_CHAR_UUIDS if u in writable_uuids]
                candidates += [u for u in writable_uuids if u not in candidates]

                confirmed = await self._probe_for_write_char(client, candidates)
                if confirmed:
                    return confirmed

                _LOGGER.warning(
                    "Could not confirm a write characteristic for %s via the "
                    "join-handshake echo; falling back to known UUID order",
                    address,
                )
                for known_uuid in KNOWN_CHAR_UUIDS:
                    if known_uuid in writable_uuids:
                        return known_uuid
                return writable_uuids[0]

            finally:
                await client.disconnect()
        # Connection/discovery can fail in many BLE-stack-specific ways.
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not discover characteristics for %s", address)
        return None

    async def _probe_for_write_char(
        self, client: BleakClientWithServiceCache, candidates: list[str]
    ) -> str | None:
        """Send the join handshake to each candidate; return the one that echoes it back."""
        join_hex = PayloadGenerator().get_join_group_payload()

        for candidate in candidates:
            notify_uuid = find_notify_char(client, candidate)
            if not notify_uuid:
                continue

            confirmed = asyncio.Event()

            # Bind as defaults to avoid a late-binding closure bug.
            def _on_notify(
                _sender: object,
                data: bytearray,
                _confirmed: asyncio.Event = confirmed,
                _expected: str = join_hex,
            ) -> None:
                if data.hex() == _expected:
                    _confirmed.set()

            try:
                await client.start_notify(notify_uuid, _on_notify)
            except Exception as err:  # noqa: BLE001 - try the next candidate
                _LOGGER.debug("Could not subscribe to %s: %s", notify_uuid, err)
                continue

            try:
                await client.write_gatt_char(
                    candidate, bytes.fromhex(join_hex), response=False
                )
                await asyncio.wait_for(confirmed.wait(), timeout=PROBE_TIMEOUT)
            except TimeoutError:
                _LOGGER.debug("No join-handshake echo from %s in time", candidate)
                continue
            except Exception as err:  # noqa: BLE001 - try the next candidate
                _LOGGER.debug("Probing %s failed: %s", candidate, err)
                continue
            else:
                _LOGGER.debug(
                    "Confirmed write characteristic %s via join-handshake echo",
                    candidate,
                )
                return candidate
            finally:
                try:
                    await client.stop_notify(notify_uuid)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("Could not unsubscribe from %s: %s", notify_uuid, err)

        return None
