from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    LightEntityFeature,
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ATTR_EFFECT,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from .payload_generator import PayloadGenerator
from bleak import BleakClient
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up iStrip light from config entry."""
    address = entry.data["address"]
    char_uuid = entry.data["char_uuid"]
    async_add_entities([IstripLight(address, char_uuid)])


class IstripLight(LightEntity):
    def __init__(self, address, char_uuid):
        self._address = address
        self._char_uuid = char_uuid
        self._is_on = False
        self._rgb_color = (255, 255, 255)
        self._brightness = 255
        self._effect = None  # Current effect name
        self._effect_speed = 100  # Speed for effects (1-100)
        self._pg = PayloadGenerator()

    @property
    def unique_id(self):
        return f"istrip_{self._address.lower().replace(':', '')}"

    @property
    def name(self):
        return "iStrip BLE Light"

    @property
    def is_on(self):
        return self._is_on

    @property
    def brightness(self):
        return self._brightness

    @property
    def rgb_color(self):
        return self._rgb_color

    @property
    def supported_color_modes(self):
        return {ColorMode.RGB}

    @property
    def color_mode(self):
        return ColorMode.RGB

    @property
    def effect_list(self):
        """Return the list of supported effects."""
        return list(self._pg.EFFECT_MODES.keys())

    @property
    def effect(self):
        """Return the current effect."""
        return self._effect

    @property
    def supported_features(self):
        """Return the supported features."""
        return LightEntityFeature.EFFECT

    async def async_turn_on(self, **kwargs):
        """Turn on the light with optional color, brightness, or effect."""
        # Handle effect parameter
        if ATTR_EFFECT in kwargs:
            effect_name = kwargs[ATTR_EFFECT]
            self._effect = effect_name
            # When effect is set, use current RGB color (or default white)
            brightness = self._brightness
            if ATTR_BRIGHTNESS in kwargs:
                self._brightness = kwargs[ATTR_BRIGHTNESS]
                brightness = self._brightness
            
            # Convert HA brightness (0-255) to device brightness (10-100)
            device_brightness = max(10, int(brightness * 100 / 255))
            
            self._is_on = True
            # Pass RGB color to effect payload (needed for Strobe/Flash effects)
            payload = self._pg.get_effect_payload(effect_name, device_brightness, self._effect_speed, self._rgb_color)
            await self._send_payload(payload)
            return

        # Handle RGB color parameter
        if ATTR_RGB_COLOR in kwargs:
            # Setting RGB color clears the effect
            self._effect = None
            self._rgb_color = kwargs[ATTR_RGB_COLOR]

        r, g, b = self._rgb_color
        brightness = self._brightness

        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = kwargs[ATTR_BRIGHTNESS]
            brightness = int(self._brightness * 100 / 255)

        # If no effect is active and no RGB was just set, maintain current mode
        if self._effect and ATTR_RGB_COLOR not in kwargs:
            # Re-apply current effect with updated brightness
            device_brightness = max(10, int(self._brightness * 100 / 255))
            payload = self._pg.get_effect_payload(self._effect, device_brightness, self._effect_speed, self._rgb_color)
        else:
            # RGB mode
            payload = self._pg.get_rgb_payload(r, g, b, brightness)

        self._is_on = True
        await self._send_payload(payload)

    async def async_turn_off(self, **kwargs):
        """Turn off the light."""
        self._is_on = False
        payload = self._pg.send_led_off()
        await self._send_payload(payload)

    async def set_effect(self, effect_name, speed=None):
        """Set an effect with optional speed.
        
        Args:
            effect_name (str): Name of the effect to set
            speed (int, optional): Speed value (1-100)
        """
        if speed is not None:
            self._effect_speed = max(1, min(100, speed))
        
        self._effect = effect_name
        device_brightness = max(10, int(self._brightness * 100 / 255))
        payload = self._pg.get_effect_payload(effect_name, device_brightness, self._effect_speed, self._rgb_color)
        
        if self._is_on:
            await self._send_payload(payload)

    async def set_speed(self, speed):
        """Set the speed for the current effect.
        
        Args:
            speed (int): Speed value (1-100)
        """
        self._effect_speed = max(1, min(100, speed))
        
        # If an effect is active and light is on, re-send with new speed
        if self._effect and self._is_on:
            device_brightness = max(10, int(self._brightness * 100 / 255))
            payload = self._pg.get_effect_payload(self._effect, device_brightness, self._effect_speed, self._rgb_color)
            await self._send_payload(payload)

    async def _send_payload(self, hex_payload):
        """Send a payload to the device via BLE."""
        try:
            async with BleakClient(self._address) as client:
                await client.write_gatt_char(self._char_uuid, bytes.fromhex(hex_payload), response=False)
        except Exception as e:
            _LOGGER.error(f"Failed to send BLE payload: {e}")