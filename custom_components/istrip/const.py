"""Constants for the iStrip+ BLE integration."""

from __future__ import annotations

DOMAIN = "istrip"

# Firmware-update (OTA) service and characteristics, per the decompiled
# official app -- see docs/ble-protocol.md. These are writable but are NOT
# control characteristics: the device accepts light commands written here and
# silently ignores them. Never select one as the write characteristic.
OTA_SERVICE_UUID = "0000ae00-0000-1000-8000-00805f9b34fb"
OTA_WRITE_CHAR_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
OTA_NOTIFY_CHAR_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"

# Known writable characteristic UUIDs used by iStrip-compatible devices.
# Different lamps may use different UUIDs (see GitHub issue #14).
KNOWN_CHAR_UUIDS = [
    "0000ae01-0000-1000-8000-00805f9b34fb",
    "0000ac52-1212-efde-1523-785fedbeda25",
]
