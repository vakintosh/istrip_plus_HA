# Controller controls (development)

This MIT fork of [vakintosh/istrip_plus_HA](https://github.com/vakintosh/istrip_plus_HA)
keeps the `istrip` domain, existing light unique IDs and device identifiers.
Replace the existing integration; do not install a second copy. The portable
Briar status-light skill is a separate package and does not enable music.

## Controls

The existing device page gains:

- **Sound reactive**: the single operating switch for controller-local sound response;
  turning it off returns to retained RGB/brightness without powering on an already
  off strip. No audio leaves the controller.
- **Sound sensitivity**: 0–100, persisted across HA restarts.
- **Sound style (unverified)**: Soft (default), Classic, Dynamic, Disco.
  Disco/dynamic lighting can flash. No automatic disco/strobe qualification tests.
- **Effect speed**: 1–100, preserving upstream per-effect speed storage/debouncing.
  This controls RGB animation effects, not microphone modes.
- **RGB channel order**: advanced configuration entity, disabled by default;
  enable it in the entity registry. RGB/RBG/GRB/GBR/BRG/BGR are host-side permutations
  for steady RGB and effect RGB parameters, with inverse notification mapping.
  This does not reprogram strip wiring, device effect palettes or opcode 5.
  Change it only while in static mode or off.

### Enable sound-reactive control once

Open **Settings → Devices & services → iStrip → Configure** and enable
**Allow experimental sound-reactive control** after reading the warning.
This grants permission; it does not start sound response or capture audio.
Then use **Sound reactive** on the device page. With permission off that switch
is unavailable, and direct service activation returns an explanatory validation
error rather than an unexpected exception. Turning off an already active mode
remains possible. Disabling permission attempts to stop active sound response;
a Bluetooth/storage failure is reported rather than claimed as success.

Upgrades retain the saved opt-in, light identity, sound-switch unique ID and
other existing control IDs. Existing entity IDs and user-assigned names are
preserved by HA, so older installations can retain their original entity ID or
custom name. Only the old **Experimental music protocol** permission switch is
removed from the entity registry. Automations targeting that obsolete switch
must be updated: permission is now configuration, not an operating mode.
The existing per-device settings Store remains the source of truth; opening or
saving unchanged configuration does not cancel an active timed return.

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
If storage fails, no automatic return starts until its journal has been saved;
the snapshot is retained in memory on failed clearing/persistence, with recovery
marked uncertain. A manual change while the initial snapshot is being saved aborts
music without writing. Invalid effect/control requests do not cancel a valid timer.
Restored microphone mode remains marked dynamic after HA restart, but this marker
is optimistic state, not an automatic command to restart microphone mode.

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

### Qualification record and research

Public protocol evidence distinguishes a RHYTHM frame from static RGB. The
related app separately calls `openMIC(mode, sensitivity)` for its controller
microphone and `setRhythm(mode, level)` when processing phone audio in
`RhythmActivity.java`; this is evidence of separate paths, not proof that its
controller IDs apply to iStrip+. We do not copy its app implementation.

The development HA checks accepted opt-in gating, timed music entry, timed
return to static, and cancellation by an explicit HA static command. These are
HA/BLE write-path checks, not physical sound-response qualification. Quiet vs
nearby sound, sensitivity response, each style, IR overrides, and actual
light output after a disconnected recovery remain unverified. No automatic
Classic/Dynamic/Disco tests or microphone recordings are part of qualification.

The interface follows HA's [options-flow pattern](https://developers.home-assistant.io/docs/core/integration/options_flow/)
and [service-action exception guidance](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/action-exceptions/):
one operating switch, a separate configuration permission, and
`ServiceValidationError` for attempts without permission. This does not qualify
the proprietary controller protocol or remove its experimental warning.

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
