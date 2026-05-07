"""Constants for the iStrip+ BLE integration."""

from __future__ import annotations

DOMAIN = "istrip"

# Known writable characteristic UUIDs used by iStrip-compatible devices.
# Different lamps may use different UUIDs (see GitHub issue #14).
KNOWN_CHAR_UUIDS = [
    "0000ae01-0000-1000-8000-00805f9b34fb",
    "0000ac52-1212-efde-1523-785fedbeda25",
]

DEFAULT_SPEED = 100

# Per-effect default speeds: slow for fades/breathing, fast for strobes/flashes.
EFFECT_DEFAULT_SPEEDS: dict[str, int] = {
    "7-Color Fade": 1,
    "3-Color Fade": 1,
    "7-Color Breathing": 1,
    "3-Color Breathing": 1,
    "Red Breathing": 1,
    "Blue Breathing": 1,
    "Green Breathing": 1,
    "Red Strobe": 100,
    "Blue Strobe": 100,
    "Green Strobe": 100,
    "7-Color Flash": 100,
    "3-Color Flash": 100,
}
