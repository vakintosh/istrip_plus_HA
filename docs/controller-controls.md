# Controller controls (development)

This MIT fork of [vakintosh/istrip_plus_HA](https://github.com/vakintosh/istrip_plus_HA)
keeps the `istrip` domain, existing light unique IDs and device identifiers.
Replace the existing integration; do not install a second copy. The portable
Briar status-light skill is a separate package and does not enable music.

## Controls

The existing device page gains:

- **Experimental music protocol**: explicit per-device opt-in, initially off.
- **Controller microphone (experimental)**: starts controller-local sound response;
  turning it off sends steady retained RGB/brightness. No audio leaves the controller.
- **Microphone sensitivity (experimental)**: 0–100, persisted across HA restarts.
- **Music style (experimental)**: Soft (default), Classic, Dynamic, Disco.
  Disco/dynamic lighting can flash. No automatic disco/strobe qualification tests.
- **Effect speed**: 1–100, preserving upstream per-effect speed storage/debouncing.
  This controls RGB animation effects, not microphone modes.
- **RGB channel order**: advanced configuration entity, disabled by default;
  enable it in the entity registry. RGB/RBG/GRB/GBR/BRG/BGR are host-side permutations
  for steady RGB and effect RGB parameters, with inverse notification mapping.
  This does not reprogram strip wiring, device effect palettes or opcode 5.
  Change it only while in static mode or off.

All entities share the original light's BLE connection. Services `set_effect`
(`effect`, optional `speed`) and `set_speed` remain available and now dispatch
only to integration-owned lights. Existing `entity_id` service calls still work.

## Timed return

```yaml
action: istrip.start_timed_music
target:
  entity_id: light.your_strip
data:
  duration: 60
```

Start from steady RGB or off; send an explicit static/off command after HA startup
first, since a restored HA state is not current hardware confirmation.
HA stores the pre-music snapshot and UTC deadline
before writing to the controller, and owns the timer (the laptop can disconnect).
Any later HA control cancels that timer. A different BLE lighting notification
revokes ownership; exact recent command echoes are ignored for five seconds.
Notifications cannot distinguish an identical manual command from an exact echo;
IR changes not reported by the device cannot be detected. This is not a physical
lock or guaranteed external-control arbitration.

The light's `timed_return_status` is `idle`, `active`, `restoring` or
`reconciliation_required`; `timed_return_deadline` is a Unix UTC timestamp.
An HA restart/reload, failed/ambiguous write or lost connection at expiry retains
the recovery record and **does not reconnect/retry an automatic restoration**.
HA cannot query reliable current device state, so automatic recovery after an
outage would risk overwriting manual changes. Inspect the device and send an
explicit desired static command, or call `istrip.cancel_timed_return` to discard
the record without writing. A steady light command exits music mode.

## Protocol evidence and limits

RHYTHM uses plaintext `54 52 00 57 03 group status fft sensitivity 00...`, encrypted
using the upstream 16-byte AES framing. This code sends controller styles only,
with FFT zero; no phone microphone capture or audio streaming is implemented.

- Exact header/frame: [gsp8181/ha-istrip-lamp-esphome](https://github.com/gsp8181/ha-istrip-lamp-esphome/tree/466873feee5416f7cd59421ee76a198a37796b6e)
  (`ISTRIP_PROTOCOL.md`, `esphome.cs`).
- Candidate controller status IDs: Soft=4, Classic=5, Dynamic=3, Disco=2,
  from inspection of related-app protocol behavior in
  [HanagataGH/idealled](https://github.com/HanagataGH/idealled/tree/dd4d24469bae823606090fee57c57edaaba63f2c).
  That app uses a different header (`...61`); these mappings are **not proof of
  exact iStrip+ or controller compatibility**. No decompiled app code is included.

Until hardware-qualified, all music controls remain experimental and opt-in.
Unit tests prove frame construction and HA behavior, not visible device response.
Begin hardware qualification with low-brightness Soft, then static return;
do not assume speed/brightness influence each controller music style.

## Installation and dependencies

Requires Home Assistant with Bluetooth and the manifest dependencies
(`bleak`, `bleak-retry-connector`, `pycryptodome`), installed by HA. Use the existing
supported local adapter or an active ESPHome Bluetooth proxy placed near the strip.
Controller and proxy proximity matters; successful laptop control alone does not
prove the proxy link. Keep the proxy's encrypted API/authenticated OTA and existing
network security. No firmware replacement is needed for these controls.

Back up `custom_components/istrip`, stop competing app/laptop connections, install
the reviewed component directory and restart HA after configuration validation.
Keep private addresses, tokens and backups out of source control. Roll back the
component directory if acceptance fails; preserve `.storage` recovery evidence.
Do not deploy this development branch until tests and independent review pass.

For offline development, use Python 3.14 and `pip install -r tests/requirements.in`,
then `python -m pytest -q tests`. The tests use synthetic devices and a local HA
runtime only, not the room's radio or credentials. Ruff 0.15.1 checks formatting
and lint. HA's own dependency deprecation warnings are not hardware failures.

Only service AC50 / characteristic AC52 is eligible for writes. AE00/AE01/AE02
are firmware-update endpoints and are never probed or used. Unknown writable
characteristics are not fallbacks. Pairing/group handling stays internal; OTA,
firmware, device timers and unverified channel-order opcodes are not exposed.

Assisted-by: Briar
