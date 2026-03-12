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

    HEADER = bytes([0x54, 0x52, 0x00, 0x57])

    GROUP_ID = 1  # Can be set dynamically later if needed

    # Effect mode constants (mode 1-12)
    EFFECT_MODES = {
        "7-Color Fade": 1,
        "3-Color Fade": 2,
        "Red Breathing": 3,
        "Red Strobe": 4,
        "7-Color Breathing": 5,
        "3-Color Breathing": 6,
        "Blue Breathing": 7,
        "Blue Strobe": 8,
        "7-Color Flash": 9,
        "3-Color Flash": 10,
        "Green Breathing": 11,
        "Green Strobe": 12,
    }

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

    def get_effect_payload(self, effect_name, brightness=100, speed=100, rgb=(255, 255, 255)):
        """Generate the effect payload for the LED strip.

        Args:
            effect_name (str): The name of the effect (e.g., "Fade7", "Breath R").
            brightness (int, optional): The brightness level (10-100). Defaults to 100.
            speed (int, optional): The speed level (1-100). Defaults to 100.
            rgb (tuple, optional): RGB color tuple (R, G, B) for effects that use it. Defaults to (255, 255, 255).

        Returns:
            str: The encrypted and formatted payload.

        Raises:
            ValueError: If the effect name is not recognized.
        """
        if effect_name not in self.EFFECT_MODES:
            raise ValueError(f"Unknown effect: {effect_name}. Available: {list(self.EFFECT_MODES.keys())}")

        mode = self.EFFECT_MODES[effect_name]
        red, green, blue = rgb
        
        payload = bytearray(16)
        payload[0:4] = self.HEADER
        payload[4] = CommandType.Rgb
        payload[5] = self.GROUP_ID
        payload[6] = mode  # Effect mode (1-12)
        payload[7] = red    # Red component (used by some effects like Strobe)
        payload[8] = green  # Green component
        payload[9] = blue   # Blue component
        payload[10] = brightness  # Brightness
        payload[11] = speed       # Speed
        
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