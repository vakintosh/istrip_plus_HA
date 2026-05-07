"""Support for iStrip+ BLE LED lights."""

from __future__ import annotations

import logging
from typing import Any

from bleak.backends.device import BLEDevice
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

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

from .const import DOMAIN, EFFECT_DEFAULT_SPEEDS, DEFAULT_SPEED, KNOWN_CHAR_UUIDS
from .payload_generator import PayloadGenerator

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


class IstripLight(LightEntity):
    """Representation of an iStrip+ BLE LED light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "istrip_light"
    _attr_supported_color_modes = {ColorMode.RGB}
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
        self._device = BLEDevice(address, name, {})
        self._pg = PayloadGenerator()
        self._client: BleakClientWithServiceCache | None = None
        self._connected = False

        # Per-effect speed — starts from EFFECT_DEFAULT_SPEEDS, overridable at runtime
        self._effect_speeds: dict[str, int] = dict(EFFECT_DEFAULT_SPEEDS)

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

    def _get_speed(self, effect_name: str | None) -> int:
        """Return the stored speed for the given effect, or DEFAULT_SPEED."""
        if effect_name is None:
            return DEFAULT_SPEED
        return self._effect_speeds.get(effect_name, DEFAULT_SPEED)

    def _set_speed(self, effect_name: str | None, speed: int) -> None:
        """Store speed for the given effect."""
        if effect_name is not None:
            self._effect_speeds[effect_name] = max(1, min(100, speed))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light with optional color, brightness, or effect."""
        if ATTR_EFFECT in kwargs:
            effect_name = kwargs[ATTR_EFFECT]
            self._attr_effect = effect_name
            if ATTR_BRIGHTNESS in kwargs:
                self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
            device_brightness = max(10, int(self._attr_brightness * 100 / 255))
            speed = self._get_speed(effect_name)
            self._attr_is_on = True
            payload = self._pg.get_effect_payload(
                effect_name,
                device_brightness,
                speed,
                self._attr_rgb_color,
            )
            await self._send_payload(payload)
            return

        if ATTR_RGB_COLOR in kwargs:
            self._attr_effect = None
            self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]

        r, g, b = self._attr_rgb_color
        brightness = self._attr_brightness

        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
            brightness = int(self._attr_brightness * 100 / 255)

        if self._attr_effect and ATTR_RGB_COLOR not in kwargs:
            device_brightness = max(10, int(self._attr_brightness * 100 / 255))
            speed = self._get_speed(self._attr_effect)
            payload = self._pg.get_effect_payload(
                self._attr_effect,
                device_brightness,
                speed,
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
        """Set an effect with optional per-effect speed."""
        if speed is not None:
            self._set_speed(effect_name, speed)
        self._attr_effect = effect_name
        device_brightness = max(10, int(self._attr_brightness * 100 / 255))
        current_speed = self._get_speed(effect_name)
        payload = self._pg.get_effect_payload(
            effect_name,
            device_brightness,
            current_speed,
            self._attr_rgb_color,
        )
        if self._attr_is_on:
            await self._send_payload(payload)

    async def set_speed(self, speed: int) -> None:
        """Set the speed for the currently active effect."""
        if self._attr_effect is None:
            _LOGGER.warning("set_speed called but no effect is active — ignoring")
            return
        self._set_speed(self._attr_effect, speed)
        if self._attr_is_on:
            device_brightness = max(10, int(self._attr_brightness * 100 / 255))
            current_speed = self._get_speed(self._attr_effect)
            payload = self._pg.get_effect_payload(
                self._attr_effect,
                device_brightness,
                current_speed,
                self._attr_rgb_color,
            )
            await self._send_payload(payload)

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        await self._ensure_connected()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed from Home Assistant."""
        await super().async_will_remove_from_hass()
        await self._disconnect()

    async def _ensure_connected(self) -> None:
        """Ensure BLE connection is established and notifications are enabled."""
        if self._connected and self._client and self._client.is_connected:
            return

        try:
            if self._client:
                await self._disconnect()

            self._client = await establish_connection(
                BleakClientWithServiceCache,
                self._device,
                self._attr_device_info["name"],
                max_attempts=3,
            )
            self._connected = True
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

            try:
                await self._client.start_notify(
                    self._char_uuid, self._handle_notification
                )
                _LOGGER.debug("Subscribed to BLE notifications on %s", self._char_uuid)
            except Exception:
                _LOGGER.warning(
                    "Could not subscribe to notifications on %s", self._char_uuid
                )

        except Exception:
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
            except Exception:
                _LOGGER.error("Error disconnecting from %s", self._address)
            finally:
                self._client = None
                self._connected = False

    def _handle_notification(self, sender: int, data: bytearray) -> None:
        """Handle BLE notification from device."""
        try:
            _LOGGER.debug("Received notification: %s", data.hex())

            decrypted = self._pg.decrypt_payload(bytes(data))
            state = self._pg.parse_state(decrypted)

            _LOGGER.debug("Parsed state from notification: %s", state)

            self._attr_is_on = state["is_on"]
            self._attr_rgb_color = state["rgb"]
            self._attr_brightness = state["brightness"]
            self._attr_effect = state["effect"]
            # Update per-effect speed from device notification
            if state["effect"] is not None:
                self._set_speed(state["effect"], state["speed"])
            self.schedule_update_ha_state()

        except Exception:
            _LOGGER.error(
                "Error handling notification from %s", self._address, exc_info=True
            )

    async def _send_payload(self, hex_payload: str) -> None:
        """Send a payload to the device via BLE."""
        try:
            await self._ensure_connected()

            if not self._client or not self._client.is_connected:
                raise ConnectionError("Not connected to device")

            await self._client.write_gatt_char(
                self._char_uuid, bytes.fromhex(hex_payload), response=False
            )

        except Exception:
            _LOGGER.error("Failed to send BLE payload to %s", self._address)
            self._connected = False
            raise
