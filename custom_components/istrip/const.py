"""Constants for the iStrip+ BLE integration."""

DOMAIN = "istrip"

# Control service and write characteristic, per the decompiled official app
# (com.ben.istrips.ble.BleManager). See docs/ble-protocol.md.
CONTROL_SERVICE_UUID = "0000ac50-1212-efde-1523-785fedbeda25"

# Firmware-update (OTA) service and characteristics. These are writable but
# are NOT control characteristics: the device accepts light commands written
# here and silently discards them. Never select one as the write characteristic.
OTA_SERVICE_UUID = "0000ae00-0000-1000-8000-00805f9b34fb"
OTA_WRITE_CHAR_UUID = "0000ae01-0000-1000-8000-00805f9b34fb"
OTA_NOTIFY_CHAR_UUID = "0000ae02-0000-1000-8000-00805f9b34fb"

# Candidate write characteristics, most-confirmed first. This is only an
# ordering hint: the config flow confirms the real one by probing (see
# _probe_for_write_char). 0000ae01-... is the OTA characteristic and is kept
# only as a last-resort fallback for #14 reporters.
KNOWN_CHAR_UUIDS = [
    "0000ac52-1212-efde-1523-785fedbeda25",
    "0000ae01-0000-1000-8000-00805f9b34fb",
]