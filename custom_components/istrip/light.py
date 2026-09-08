"""Support for iStrip+ BLE LED lights."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .ble_helpers import find_notify_char
from .const import DOMAIN, KNOWN_CHAR_UUIDS
from .payload_generator import CommandType, PayloadGenerator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iStrip light from config entry."""
    address: str = entry.data["address"]
    char_uuid: str | None = entry.data.get("char_uuid")
    name: str = entry.data.get("name", "iStrip")
    async_add_entities([IstripLight(address, char_uuid, name, entry.entry_id)])


class IstripLight(LightEntity, RestoreEntity):
    """Representation of an iStrip+ BLE LED light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "istrip_light"
    _attr_supported_color_modes: set[ColorMode] = {ColorMode.RGB}  # noqa: RUF012
    _attr_color_mode = ColorMode.RGB
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(
        self,
        address: str,
        char_uuid: str | None,
        name: str,
        entry_id: str,
    ) -> None:
        """Initialize the iStrip light."""
        self._address = address
        self._char_uuid = char_uuid
        self._pg = PayloadGenerator()
        self._client: BleakClientWithServiceCache | None = None
        self._connected = False
        self._effect_speed = 100
        # Serializes connect/subscribe/join so a concurrent call can't race
        # ahead and send a command before the join handshake has completed.
        self._connect_lock = asyncio.Lock()

        mac = address.lower().replace(":", "")
        self._attr_unique_id = f"istrip_{mac}"
        self._attr_is_on = False
        self._attr_rgb_color = (255, 255, 255)
        self._attr_brightness = 255
        self._attr_effect = None
        self._attr_effect_list = list(self._pg.EFFECT_MODES.keys())
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=name,
            manufacturer="iStrip",
            model="iStrip+ BLE",
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light with optional color, brightness, or effect."""
        if ATTR_EFFECT in kwargs:
            effect_name = kwargs[ATTR_EFFECT]
            self._attr_effect = effect_name
            brightness = self._attr_brightness
            if ATTR_BRIGHTNESS in kwargs:
                self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
                brightness = self._attr_brightness

            device_brightness = max(10, int(brightness * 100 / 255))

            self._attr_is_on = True
            payload = self._pg.get_effect_payload(
                effect_name,
                device_brightness,
                self._effect_speed,
                self._attr_rgb_color,
            )
            await self._send_payload(payload)
            return

        if ATTR_RGB_COLOR in kwargs:
            self._attr_effect = None
            self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]

        r, g, b = self._attr_rgb_color

        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]

        # Always convert to the device's 0-100 scale, even when brightness
        # wasn't explicitly passed (e.g. a color-only call while already on).
        brightness = int(self._attr_brightness * 100 / 255)

        if self._attr_effect and ATTR_RGB_COLOR not in kwargs:
            device_brightness = max(10, int(self._attr_brightness * 100 / 255))
            payload = self._pg.get_effect_payload(
                self._attr_effect,
                device_brightness,
                self._effect_speed,
                self._attr_rgb_color,
            )
        else:
            payload = self._pg.get_rgb_payload(r, g, b, brightness)

        self._attr_is_on = True
        await self._send_payload(payload)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        self._attr_is_on = False
        payload = self._pg.send_led_off()
        await self._send_payload(payload)

    async def set_effect(self, effect_name: str, speed: int | None = None) -> None:
        """Set an effect with optional speed."""
        if speed is not None:
            self._effect_speed = max(1, min(100, speed))

        self._attr_effect = effect_name
        device_brightness = max(10, int(self._attr_brightness * 100 / 255))
        payload = self._pg.get_effect_payload(
            effect_name,
            device_brightness,
            self._effect_speed,
            self._attr_rgb_color,
        )

        if self._attr_is_on:
            await self._send_payload(payload)

    async def set_speed(self, speed: int) -> None:
        """Set the speed for the current effect."""
        self._effect_speed = max(1, min(100, speed))

        if self._attr_effect and self._attr_is_on:
            device_brightness = max(10, int(self._attr_brightness * 100 / 255))
            payload = self._pg.get_effect_payload(
                self._attr_effect,
                device_brightness,
                self._effect_speed,
                self._attr_rgb_color,
            )
            await self._send_payload(payload)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        await super().async_added_to_hass()

        # Restore the last known color/brightness/effect across a HA
        # restart, since the device has no reliable way to be asked for
        # its current state (see _handle_notification).
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"
            if (rgb := last_state.attributes.get(ATTR_RGB_COLOR)) is not None:
                self._attr_rgb_color = tuple(rgb)
            if (brightness := last_state.attributes.get(ATTR_BRIGHTNESS)) is not None:
                self._attr_brightness = brightness
            if (effect := last_state.attributes.get(ATTR_EFFECT)) is not None:
                self._attr_effect = effect

        await self._ensure_connected()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed from Home Assistant."""
        await super().async_will_remove_from_hass()
        await self._disconnect()

    async def _ensure_connected(self) -> None:
        """Ensure BLE connection is established and notifications are enabled."""
        async with self._connect_lock:
            if self._connected and self._client and self._client.is_connected:
                return

            try:
                if self._client:
                    await self._disconnect()

                ble_device = async_ble_device_from_address(
                    self.hass, self._address, connectable=True
                )
                if ble_device is None:
                    _LOGGER.error(
                        "No connectable Bluetooth scanner currently sees %s",
                        self._address,
                    )
                    return

                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    self._attr_device_info["name"],
                    max_attempts=3,
                )
                _LOGGER.debug("Connected to iStrip device at %s", self._address)

                # If char_uuid was not discovered during setup, find it now
                if not self._char_uuid:
                    self._char_uuid = self._discover_char_uuid_from_services()
                    if not self._char_uuid:
                        _LOGGER.error(
                            "No writable characteristic found on %s", self._address
                        )
                        await self._disconnect()
                        return
                    _LOGGER.info(
                        "Discovered characteristic UUID %s on %s",
                        self._char_uuid,
                        self._address,
                    )

                notify_char_uuid = find_notify_char(self._client, self._char_uuid)
                if notify_char_uuid:
                    try:
                        await self._client.start_notify(
                            notify_char_uuid, self._handle_notification
                        )
                        _LOGGER.debug(
                            "Subscribed to BLE notifications on %s", notify_char_uuid
                        )
                    # bleak/BLE backends raise a wide, inconsistent variety of
                    # errors here; any failure should be logged the same way.
                    except Exception:  # noqa: BLE001
                        _LOGGER.warning(
                            "Could not subscribe to notifications on %s",
                            notify_char_uuid,
                        )
                else:
                    _LOGGER.debug(
                        "No notify-capable characteristic found on %s; "
                        "IR-remote state sync will not be available",
                        self._address,
                    )

                # The device requires a one-time "join group" handshake right
                # after connecting, before it will act on any other command.
                try:
                    join_payload = self._pg.get_join_group_payload()
                    await self._client.write_gatt_char(
                        self._char_uuid, bytes.fromhex(join_payload), response=False
                    )
                    _LOGGER.debug("Sent join-group handshake to %s", self._address)
                # See the notify-subscribe except above: BLE errors here are
                # similarly broad and unpredictable.
                except Exception:  # noqa: BLE001
                    _LOGGER.warning(
                        "Failed to send join-group handshake to %s", self._address
                    )

                # Only mark connected once the join handshake has gone out,
                # so a waiting caller never sends a command ahead of it.
                self._connected = True

            # Connection/discovery can fail in many BLE-stack-specific ways;
            # treat any of them as a failed connection attempt.
            except Exception:  # noqa: BLE001
                _LOGGER.error("Failed to connect to device at %s", self._address)
                self._connected = False
                self._client = None

    def _discover_char_uuid_from_services(self) -> str | None:
        """Find the best writable characteristic UUID from the connected client."""
        if not self._client or not self._client.is_connected:
            return None

        writable_uuids: list[str] = []
        for service in self._client.services:
            for char in service.characteristics:
                if (
                    "write" in char.properties
                    or "write-without-response" in char.properties
                ):
                    writable_uuids.append(str(char.uuid))

        for known_uuid in KNOWN_CHAR_UUIDS:
            if known_uuid in writable_uuids:
                return known_uuid

        return writable_uuids[0] if writable_uuids else None

    async def _disconnect(self) -> None:
        """Disconnect from the BLE device."""
        if self._client:
            try:
                if self._client.is_connected:
                    await self._client.disconnect()
                _LOGGER.debug("Disconnected from iStrip device at %s", self._address)
            except Exception:  # noqa: BLE001 - disconnect can fail in many ways
                _LOGGER.error("Error disconnecting from %s", self._address)
            finally:
                self._client = None
                self._connected = False

    def _handle_notification(self, sender: int, data: bytearray) -> None:
        """Handle BLE notification from device."""
        try:
            decrypted = self._pg.decrypt_payload(bytes(data))
            state = self._pg.parse_state(decrypted)

            # The device echoes the join-group handshake back as a
            # notification right after connecting. That echo decodes to
            # R=G=B=0/brightness=0 -- it's not a real state update, so
            # applying it would wrongly show the light as off/black on
            # every reconnect (HA restart, ESP32 reboot, etc.).
            if state["command_type"] != CommandType.RGB:
                return

            self._attr_is_on = state["is_on"]
            self._attr_rgb_color = state["rgb"]
            self._attr_brightness = state["brightness"]
            self._attr_effect = state["effect"]
            self._effect_speed = state["speed"]

            self.schedule_update_ha_state()

        except Exception:
            _LOGGER.exception("Error handling notification from %s", self._address)

    async def _send_payload(
        self, hex_payload: str, retries: int = 2, retry_delay: float = 3.0
    ) -> None:
        """Send a payload to the device via BLE.

        The ESP32 Bluetooth proxy can occasionally crash and reboot
        mid-connection, recovering within a few seconds. Retrying gives it
        a chance to come back before we surface a failure to Home Assistant.
        """
        last_exc: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                await self._ensure_connected()

                if not self._client or not self._client.is_connected:
                    raise ConnectionError("Not connected to device")

                await self._client.write_gatt_char(
                    self._char_uuid, bytes.fromhex(hex_payload), response=False
                )
                return

            # Write failures span BleakError, timeouts, and ESPHome-proxy-
            # specific errors; any of them means "retry the send".
            except Exception as err:  # noqa: BLE001
                last_exc = err
                self._connected = False
                if attempt < retries:
                    _LOGGER.warning(
                        "Send attempt %d/%d to %s failed (%s), retrying in %.1fs",
                        attempt,
                        retries,
                        self._address,
                        err,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)

        _LOGGER.error(
            "Failed to send BLE payload to %s after %d attempts", self._address, retries
        )
        raise last_exc
