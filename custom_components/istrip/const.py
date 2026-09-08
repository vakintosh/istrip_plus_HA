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

# Speed the device itself defaults to (DataManager.speed in the official app).
DEFAULT_SPEED = 100

# Minimum seconds between speed commands. The official app throttles its
# speed slider to 150ms while dragging and guarantees a final send on
# release; without this, an automation bound to an input_number floods the
# device with BLE writes.
SPEED_SEND_INTERVAL = 0.15

# Per-effect default speeds: slow for fades and breathing, fast for strobes
# and flashes. The official app has no equivalent, it keeps one global speed,
# but a sensible starting point per effect is a better fit for Home Assistant
# than making the user re-tune the slider every time they switch.
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
