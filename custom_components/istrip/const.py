"""Constants for the iStrip+ BLE integration."""

DOMAIN = "istrip"

# Order matters: the first UUID present on a given device is preferred.
# 0000ac52-... is the confirmed-correct write characteristic (verified
# against a real BLE capture of the official app); 0000ae01-... is kept
# as a fallback for device variants that only expose that one.
KNOWN_CHAR_UUIDS = [
    "0000ac52-1212-efde-1523-785fedbeda25",
    "0000ae01-0000-1000-8000-00805f9b34fb",
]
