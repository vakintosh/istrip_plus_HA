from homeassistant.components.light import (
    ColorMode,
    LightEntity,
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
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

    async def async_turn_on(self, **kwargs):
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
        self._is_on = False
        payload = self._pg.send_led_off()
        await self._send_payload(payload)

    async def _send_payload(self, hex_payload):
        try:
            async with BleakClient(self._address) as client:
                await client.write_gatt_char(self._char_uuid, bytes.fromhex(hex_payload), response=False)
        except Exception as e:
            _LOGGER.error(f"Failed to send BLE payload: {e}")