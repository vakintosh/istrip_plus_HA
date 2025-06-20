# payload_generator.py

from Crypto.Cipher import AES

class CommandType:
    """Enumeration for command types used in the LED strip communication."""
    JoinGroupRequest = 1
    Rgb = 2
    Rhythm = 3
    Timer = 4
    RgbLineSequence = 5
    Speed = 6
    Light = 7

class PayloadGenerator:
    """Generates payloads for the LED strip commands."""
    KEY = bytes([
        0x34, 0x52, 0x2A, 0x5B,
        0x7A, 0x6E, 0x49, 0x2C,
        0x08, 0x09, 0x0A, 0x9D,
        0x8D, 0x2A, 0x23, 0xF8
    ])

    # Static header
    HEADER = bytes([0x54, 0x52, 0x00, 0x57])

    GROUP_ID = 1  # Can be set dynamically later if needed

    def __init__(self):
        """Initialize the PayloadGenerator with the AES cipher."""
        self._cipher = AES.new(self.KEY, AES.MODE_ECB)

    def get_rgb_payload(self, red, green, blue, brightness=100, speed=100):
        """Generate the RGB payload for the LED strip.

        Args:
            red (int): The red color value (0-255).
            green (int): The green color value (0-255).
            blue (int): The blue color value (0-255).
            brightness (int, optional): The brightness level (0-100). Defaults to 100.
            speed (int, optional): The speed level (0-100). Defaults to 100.

        Returns:
            str: The encrypted and formatted payload.
        """
        payload = bytearray(16)
        payload[0:4] = self.HEADER
        payload[4] = CommandType.Rgb
        payload[5] = self.GROUP_ID
        payload[6] = 0x00  # Reserved or unknown mode


        payload[7] = red
        payload[8] = green
        payload[9] = blue

        payload[10] = brightness
        payload[11] = speed
        return self._encrypt_and_format(payload)


    def send_led_off(self, brightness=0, speed=100):
        """ Generate the payload to turn off the LED strip.
        Args:
            brightness (int, optional): The brightness level (0-100). Defaults to 0.
            speed (int, optional): The speed level (0-100). Defaults to 100.
        """
        payload = bytearray(16)
        payload[0:4] = self.HEADER
        payload[4] = CommandType.Rgb
        payload[5] = self.GROUP_ID
        payload[6:9] = b'\x00\x00\x00'
        payload[9] = 0x00               
        payload[10] = brightness
        payload[11] = speed

        return self._encrypt_and_format(payload)

    def _encrypt_and_format(self, payload: bytearray) -> str:
        """Encrypt the payload and format it as a hex string.
        Args:
            payload (bytearray): The payload to encrypt.

        Returns:
            str: The encrypted and formatted payload.
        """
        assert len(payload) == 16, f"Payload must be 16 bytes, got {len(payload)}"
        encrypted = self._cipher.encrypt(bytes(payload))
        return ''.join(f'{b:02x}' for b in encrypted)
