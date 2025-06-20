# light.py

from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR
)
from .payload_generator import PayloadGenerator
from .const import BLE_ADDRESS, CHAR_UUID
from bleak import BleakClient
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the iStrip BLE light platform."""
    async_add_entities([IstripLight()])


class IstripLight(LightEntity):
    """Representation of the iStrip App."""
    def __init__(self):
        self._is_on = False
        self._rgb_color = (255, 255, 255)
        self._brightness = 255
        self._pg = PayloadGenerator()

    @property
    def unique_id(self):
        """Return a unique ID for the light."""
        return f"istrip_{BLE_ADDRESS.lower().replace(':', '')}"

    @property
    def name(self):
        """Return the name of the light."""
        return "iStrip BLE Light"

    @property
    def is_on(self):
        """Return True if the light is on."""
        return self._is_on

    @property
    def brightness(self):
        """Return the brightness of the light."""
        return self._brightness

    @property
    def rgb_color(self):
        """Return the RGB color of the light."""
        return self._rgb_color

    @property
    def supported_color_modes(self):
        """Return the supported color modes."""
        return {ColorMode.RGB}

    @property
    def color_mode(self):
        """Return the current color mode."""
        return ColorMode.RGB

    async def async_turn_on(self, **kwargs):
        """Turn the light on with the specified RGB color and brightness."""
        r, g, b = self._rgb_color
        brightness = self._brightness

        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            self._rgb_color = (r, g, b)

        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = kwargs[ATTR_BRIGHTNESS]
            brightness = int(self._brightness * 100 / 255)

        self._is_on = True

        payload = self._pg.get_rgb_payload(r, g, b, brightness)
        await self._send_payload(payload)

    async def async_turn_off(self, **kwargs):
        """Turn the light off."""
        self._is_on = False
        payload = self._pg.send_led_off()
        await self._send_payload(payload)

    async def _send_payload(self, hex_payload):
        """Send the BLE payload to the iStrip device."""
        try:
            async with BleakClient(BLE_ADDRESS) as client:
                await client.write_gatt_char(CHAR_UUID, bytes.fromhex(hex_payload), response=False)
        except Exception as e:
            _LOGGER.error(f"Failed to send BLE payload: {e}")
