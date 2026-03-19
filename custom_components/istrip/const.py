"""Constants for the iStrip+ BLE integration."""

from __future__ import annotations

DOMAIN = "istrip"

# Known writable characteristic UUIDs used by iStrip-compatible devices.
# Different lamps may use different UUIDs (see GitHub issue #14).
KNOWN_CHAR_UUIDS = [
    "0000ae01-0000-1000-8000-00805f9b34fb",
    "0000ac52-1212-efde-1523-785fedbeda25",
]
