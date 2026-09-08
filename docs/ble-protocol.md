# iStrip+ BLE protocol reference

Reference notes for the GATT layout and command protocol used by iStrip-compatible
sunset lamps / LED strips.

Everything in the "Characteristics" section below is taken from the **official
iStrip+ Android app, version 1.3.6** (`com.ben.istrips`), decompiled with
[jadx](https://github.com/skylot/jadx). It is not inferred from behaviour — these
are the app's own constants.

The APK itself is deliberately not committed to this repository (28 MB, and
redistributing it is not ours to do). To reproduce:

```bash
jadx -d out --no-res --no-debug-info classes.dex
# then read: out/sources/com/ben/istrips/ble/BleManager.java
```

---

## Characteristics

From `com.ben.istrips.ble.BleManager` (lines 42-49):

| Constant              | UUID                                   | Purpose                                           |
| --------------------- | -------------------------------------- | ------------------------------------------------- |
| `UUID_SERVICE`        | `0000ac50-1212-efde-1523-785fedbeda25` | Control service                                   |
| `UUID_WRITE_CHA`      | `0000ac52-1212-efde-1523-785fedbeda25` | **Control writes — this is the one that matters** |
| `UUID_WRITE2_CHA`     | `d44bc439-abfd-45a2-b575-92541612960a` | Secondary write channel (unused by us)            |
| `UUID_WRITE3_CHA`     | `d44bc439-abfd-45a2-b575-92541612960b` | Tertiary write channel (unused by us)             |
| `UUID_READ_CHA`       | `00002902-0000-1000-8000-00805f9b34fb` | See "app quirks" below                            |
| `UUID_OTA_SERVICE`    | `0000ae00-0000-1000-8000-00805f9b34fb` | Firmware update service                           |
| `UUID_OTA_WRITE_CHA`  | `0000ae01-0000-1000-8000-00805f9b34fb` | Firmware update writes                            |
| `UUID_OTA_NOTIFY_CHA` | `0000ae02-0000-1000-8000-00805f9b34fb` | Firmware update notifications                     |

Every ordinary command the app sends goes to `UUID_WRITE_CHA`
(`BleManager.java:292`):

```java
public boolean write(BleDevice bleDevice, byte[] bArr) {
    return writeIntenal(bleDevice, bArr, UUID_WRITE_CHA, 0, 1);
}
```

### `0000ae01` is the OTA characteristic, not a control characteristic

This is the important consequence, and the root cause behind
[#14](https://github.com/vakintosh/istrip/issues/14) and
[#18](https://github.com/vakintosh/istrip/issues/18).

`0000ae01-...` lives in `0000ae00-...`, the **firmware update** service. It is
`UUID_OTA_WRITE_CHA`. Writing light commands there is writing into the firmware
updater: the device accepts the write at the GATT level, returns no error, and
does nothing at all with the payload. That is exactly the reported symptom —
"connects fine, accepts writes, light never responds".

The AES key and frame format were correct the whole time. The bytes were being
delivered to the wrong characteristic.

`0000ac52-...` is the correct control characteristic and should always be
preferred when the device exposes it.

### Devices expose both services at once

A GATT dump of an `SSL-C551BE` (61:DD:C5:C5:51:BE):

```
Service: 0000ac50-1212-efde-1523-785fedbeda25
  Char: 0000ac51-1212-efde-1523-785fedbeda25 - ['notify']
  Char: 0000ac52-1212-efde-1523-785fedbeda25 - ['write-without-response']
  Char: 0000ac53-1212-efde-1523-785fedbeda25 - ['write-without-response']
Service: 0000ae00-0000-1000-8000-00805f9b34fb
  Char: 0000ae01-0000-1000-8000-00805f9b34fb - ['write-without-response']
  Char: 0000ae02-0000-1000-8000-00805f9b34fb - ['notify']
```

An `SSL-060F4C` (52:07:2A:06:0F:4C) was independently reported in #18 with the
same `0xAC50` / `0xAC52` / `0xAC51` layout.

So "is this an `ae01` device or an `ac52` device?" is a false distinction — the
same device offers both. Selecting purely by "first known writable UUID present"
will pick whichever entry is listed first, which is why UUID ordering in
`const.py` silently decided whether the integration worked.

---

## Connection sequence

The app, on connect (`BleManager.java:103-107`):

```java
public void onReady(BleDevice bleDevice, BluetoothGatt bluetoothGatt) {
    super.onReady(bleDevice, bluetoothGatt);
    BleManager.this.setConnectedBtGatt(bluetoothGatt);
    BleManager.this.ble.startNotify(bleDevice, BleManager.this.notiftCallback);
}
```

i.e. connect → discover services → subscribe to notifications, before any
command traffic.

A `JOIN_GROUP_REQUEST` (`CommandType` value `1`, see `payload_generator.py`) is
then sent once per connection before any RGB/on/off command. Unlike the
characteristic table above, this ordering is **not** evidenced by an app symbol
named "join group" — it comes from an HCI snoop capture of a real session
(#18). Without it the device ignores subsequent commands.

### Notify characteristic is discovered by property, not by UUID

The app does not hardcode a notify characteristic. `BleRequestImpl.java:247-271`
walks the characteristics of `uuid_service` and `uuid_ota_service` and collects
anything advertising `PROPERTY_NOTIFY` (`0x10`) or `PROPERTY_INDICATE` (`0x20`):

```java
if ((bluetoothGattCharacteristic.getProperties() & 16) != 0) {
    this.notifyCharacteristics.add(bluetoothGattCharacteristic);
}
if ((bluetoothGattCharacteristic.getProperties() & 32) != 0) {
    this.notifyCharacteristics.add(bluetoothGattCharacteristic);
}
```

Our property-based notify discovery (preferring a notify/indicate characteristic
in the same GATT service as the chosen write characteristic) mirrors this. Do
**not** replace it with a hardcoded `ac51` — the vendor app does not do that, and
hardcoding would break variants we have not dumped.

### App quirks worth knowing

- `UUID_READ_CHA` is set to `00002902-0000-1000-8000-00805f9b34fb`, which is the
  standard **Client Characteristic Configuration Descriptor (CCCD)** UUID, not a
  characteristic UUID. It can therefore never match a characteristic during
  service discovery. This looks like a genuine bug in the vendor app; it is
  harmless because notify subscription is property-driven (above). Do not copy
  this constant into our code as if it were a readable characteristic.
- `BleManager.java:247` only scans `uuid_service` and `uuid_ota_service`.
  Characteristics in any other service are ignored by the app entirely.

---

## Command payloads

See `custom_components/istrip/payload_generator.py` for the implementation.

- 16-byte AES key, ECB, hardcoded in the firmware and the app.
- 4-byte header `54 52 00 57`.
- `GROUP_ID` of `1`.
- `CommandType`: `JOIN_GROUP_REQUEST=1`, `RGB=2`, `RHYTHM=3`, `TIMER=4`,
  `RGB_LINE_SEQUENCE=5`, `SPEED=6`, `LIGHT=7`.
- Brightness and speed are on a `0-100` scale on the wire, not `0-255`.

---

## Implications for this integration

1. `KNOWN_CHAR_UUIDS` must list `0000ac52-...` first. `0000ae01-...` should be
   kept only as a last-resort fallback, and annotated as the OTA characteristic
   so nobody "corrects" the order back.
2. Prefer confirming the write characteristic empirically (send the join
   handshake, wait for the echo on the notify characteristic) over trusting UUID
   order. Ordering is a hint; the probe is the source of truth.
3. Notify discovery stays property-based, matching the app.
4. `char_uuid` is persisted into the config entry at setup time. Existing
   installs that were onboarded onto `ae01` will keep writing to the OTA
   characteristic forever unless a config-entry migration clears the stored
   value and forces re-discovery.

## Sources

- `com/ben/istrips/ble/BleManager.java`, iStrip+ 1.3.6, decompiled with jadx.
- `cn/com/heaton/blelibrary/ble/BleRequestImpl.java` (bundled BLE library).
- Local GATT dumps of `SSL-C551BE`.
- HCI snoop capture of the official app, contributed in
  [#18](https://github.com/vakintosh/istrip/issues/18).
