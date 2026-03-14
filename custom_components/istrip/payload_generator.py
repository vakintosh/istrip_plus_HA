"""Payload generation and parsing for iStrip+ BLE LED strip communication."""

from __future__ import annotations

from enum import IntEnum

from Crypto.Cipher import AES


class CommandType(IntEnum):
    """Command types used in the LED strip communication."""

    JOIN_GROUP_REQUEST = 1
    RGB = 2
    RHYTHM = 3
    TIMER = 4
    RGB_LINE_SEQUENCE = 5
    SPEED = 6
    LIGHT = 7

_EFFECT_MODE_REVERSE: dict[int, str] = {}


class PayloadGenerator:
    """Generates and parses encrypted payloads for the iStrip+ LED strip."""

    __slots__ = ("_cipher",)

    KEY = bytes(
        [
            0x34,
            0x52,
            0x2A,
            0x5B,
            0x7A,
            0x6E,
            0x49,
            0x2C,
            0x08,
            0x09,
            0x0A,
            0x9D,
            0x8D,
            0x2A,
            0x23,
            0xF8,
        ]
    )

    HEADER = bytes([0x54, 0x52, 0x00, 0x57])

    GROUP_ID = 1

    EFFECT_MODES: dict[str, int] = {
        "3-Color Breathing": 6,
        "3-Color Fade": 2,
        "3-Color Flash": 10,
        "7-Color Breathing": 5,
        "7-Color Fade": 1,
        "7-Color Flash": 9,
        "Blue Breathing": 7,
        "Blue Strobe": 8,
        "Green Breathing": 11,
        "Green Strobe": 12,
        "Red Breathing": 3,
        "Red Strobe": 4,
    }

    def __init__(self) -> None:
        """Initialize the PayloadGenerator with the AES cipher."""
        self._cipher = AES.new(self.KEY, AES.MODE_ECB)
        if not _EFFECT_MODE_REVERSE:
            _EFFECT_MODE_REVERSE.update({v: k for k, v in self.EFFECT_MODES.items()})

    def get_rgb_payload(
        self,
        red: int,
        green: int,
        blue: int,
        brightness: int = 100,
        speed: int = 100,
    ) -> str:
        """Generate the RGB payload for the LED strip."""
        payload = bytearray(16)
        payload[0:4] = self.HEADER
        payload[4] = CommandType.RGB
        payload[5] = self.GROUP_ID
        payload[6] = 0x00

        payload[7] = red
        payload[8] = green
        payload[9] = blue

        payload[10] = brightness
        payload[11] = speed
        return self._encrypt_and_format(payload)

    def send_led_off(self, brightness: int = 0, speed: int = 100) -> str:
        """Generate the payload to turn off the LED strip."""
        payload = bytearray(16)
        payload[0:4] = self.HEADER
        payload[4] = CommandType.RGB
        payload[5] = self.GROUP_ID
        payload[6:9] = b"\x00\x00\x00"
        payload[9] = 0x00
        payload[10] = brightness
        payload[11] = speed

        return self._encrypt_and_format(payload)

    def get_effect_payload(
        self,
        effect_name: str,
        brightness: int = 100,
        speed: int = 100,
        rgb: tuple[int, int, int] = (255, 255, 255),
    ) -> str:
        """Generate the effect payload for the LED strip.

        Raises:
            ValueError: If the effect name is not recognised.
        """
        if effect_name not in self.EFFECT_MODES:
            raise ValueError(
                f"Unknown effect: {effect_name}. "
                f"Available: {list(self.EFFECT_MODES.keys())}"
            )

        mode = self.EFFECT_MODES[effect_name]
        red, green, blue = rgb

        payload = bytearray(16)
        payload[0:4] = self.HEADER
        payload[4] = CommandType.RGB
        payload[5] = self.GROUP_ID
        payload[6] = mode
        payload[7] = red
        payload[8] = green
        payload[9] = blue
        payload[10] = brightness
        payload[11] = speed

        return self._encrypt_and_format(payload)

    def _encrypt_and_format(self, payload: bytearray) -> str:
        """Encrypt the payload and format it as a hex string."""
        assert len(payload) == 16, f"Payload must be 16 bytes, got {len(payload)}"
        encrypted = self._cipher.encrypt(bytes(payload))
        return "".join(f"{b:02x}" for b in encrypted)

    def decrypt_payload(self, data: bytes) -> bytearray:
        """Decrypt a payload received from the device."""
        if len(data) != 16:
            raise ValueError(f"Encrypted payload must be 16 bytes, got {len(data)}")

        decrypted = self._cipher.decrypt(bytes(data))
        return bytearray(decrypted)

    def parse_state(self, decrypted_payload: bytearray) -> dict[str, object]:
        """Parse a decrypted payload to extract device state."""
        if len(decrypted_payload) != 16:
            raise ValueError(f"Payload must be 16 bytes, got {len(decrypted_payload)}")

        header = bytes(decrypted_payload[0:4])
        if header != self.HEADER:
            raise ValueError(
                f"Invalid header: expected {self.HEADER.hex()}, got {header.hex()}"
            )

        command_type = decrypted_payload[4]
        mode = decrypted_payload[6]
        red = decrypted_payload[7]
        green = decrypted_payload[8]
        blue = decrypted_payload[9]
        brightness = decrypted_payload[10]
        speed = decrypted_payload[11]

        is_on = not (red == 0 and green == 0 and blue == 0 and mode == 0)

        ha_brightness = int(brightness * 255 / 100) if brightness > 0 else 0

        effect = _EFFECT_MODE_REVERSE.get(mode) if mode > 0 else None

        return {
            "is_on": is_on,
            "rgb": (red, green, blue),
            "brightness": ha_brightness,
            "effect": effect,
            "speed": speed,
            "command_type": command_type,
            "mode": mode,
        }
