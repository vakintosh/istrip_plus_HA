"""Support for iStrip+ BLE LED lights."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_register_callback,
)
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity

from .ble_helpers import find_notify_char
from .const import (
    CONTROL_SERVICE_UUID,
    DEFAULT_SPEED,
    DOMAIN,
    EFFECT_DEFAULT_SPEEDS,
    KNOWN_CHAR_UUIDS,
    SPEED_SEND_INTERVAL,
)
from .controller import ControllerMixin, serialized
from .controls import MUSIC_EFFECT, integer, map_rgb
from .payload_generator import CommandType, PayloadGenerator

_LOGGER = logging.getLogger(__name__)


def _clamp_speed(speed: int) -> int:
    """Clamp to the device's 1-100 range.

    The official app coerces a slider value of 0 up to 1 rather than sending
    it (ClassicEffectFragment: `if (i == 0) i = 1;`).
    """
    return max(1, min(100, speed))


@dataclass
class IstripExtraStoredData(ExtraStoredData):
    """Per-effect speeds, which are not expressible as entity attributes."""

    effect_speeds: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        """Return a serialisable representation."""
        return {"effect_speeds": self.effect_speeds}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up iStrip light from config entry."""
    address: str = entry.data["address"]
    char_uuid: str | None = entry.data.get("char_uuid")
    name: str = entry.data.get("name", "iStrip")
    light = IstripLight(address, char_uuid, name, entry.entry_id)
    entry.runtime_data["light"] = light
    async_add_entities([light])
    platform = async_get_current_platform()
    platform.async_register_entity_service(
        "set_effect",
        {
            vol.Required("effect"): vol.In(list(light._pg.EFFECT_MODES)),
            vol.Optional("speed"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        },
        "async_service_set_effect",
    )
    platform.async_register_entity_service(
        "set_speed",
        {vol.Required("speed"): vol.All(cv.positive_int, vol.Range(min=1, max=100))},
        "set_speed",
    )
    platform.async_register_entity_service(
        "start_timed_music",
        {
            vol.Required("duration"): vol.All(
                cv.positive_int, vol.Range(min=1, max=86400)
            )
        },
        "async_start_timed_music",
    )
    platform.async_register_entity_service(
        "cancel_timed_return", {}, "async_cancel_timed_return"
    )


class IstripLight(ControllerMixin, LightEntity, RestoreEntity):
    """Representation of an iStrip+ BLE LED light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "istrip_light"
    _attr_supported_color_modes: set[ColorMode] = {ColorMode.RGB}  # noqa: RUF012
    _attr_color_mode = ColorMode.RGB
    _attr_supported_features = LightEntityFeature.EFFECT

    def __init__(
        self,
        address: str,
        char_uuid: str | None,
        name: str,
        entry_id: str,
    ) -> None:
        """Initialize the iStrip light."""
        self._address = address
        self._char_uuid = char_uuid if char_uuid in KNOWN_CHAR_UUIDS else None
        self._entry_id = entry_id
        self._pg = PayloadGenerator()
        self._client: BleakClientWithServiceCache | None = None
        self._connected = False
        self._init_controls()

        # Per-effect speeds, seeded from the defaults and overridable at
        # runtime. _pending_speed holds a speed set while no effect was
        # active, to be applied to whichever effect is selected next.
        self._effect_speeds: dict[str, int] = dict(EFFECT_DEFAULT_SPEEDS)
        self._pending_speed: int | None = None
        self._speed_debouncer: Debouncer | None = None
        # Serializes connect/subscribe/join so a concurrent call can't race
        # ahead and send a command before the join handshake has completed.
        self._connect_lock = asyncio.Lock()

        mac = address.lower().replace(":", "")
        self._attr_unique_id = f"istrip_{mac}"
        self._attr_is_on = False
        self._attr_rgb_color = (255, 255, 255)
        self._attr_brightness = 255
        self._attr_effect = None
        self._attr_effect_list = list(self._pg.EFFECT_MODES.keys())
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=name,
            manufacturer="iStrip",
            model="iStrip+ BLE",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose ownership and experimental state without private configuration."""
        record = self.journal.record
        return {
            "controller_microphone": self._music_active,
            "experimental_music_protocol": self.settings.experimental_music,
            "timed_return_status": record["status"] if record else "idle",
            "timed_return_deadline": record["deadline"] if record else None,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light with optional color, brightness, or effect."""
        if ATTR_EFFECT in kwargs and kwargs[ATTR_EFFECT] not in self._pg.EFFECT_MODES:
            raise ValueError("Unknown effect")
        await self._async_turn_on_locked(**kwargs)

    @serialized
    async def _async_turn_on_locked(self, **kwargs: Any) -> None:
        """Apply a validated light command while owning the command lock."""
        if ATTR_EFFECT in kwargs:
            effect_name = kwargs[ATTR_EFFECT]
            self._music_active = False
            self._adopt_pending_speed(effect_name)
            self._attr_effect = effect_name
            if ATTR_BRIGHTNESS in kwargs:
                self._attr_brightness = kwargs[ATTR_BRIGHTNESS]

            self._attr_is_on = True
            await self._send_payload(self._build_effect_payload(effect_name))
            return

        if ATTR_RGB_COLOR in kwargs:
            self._music_active = False
            self._attr_effect = None
            self._attr_rgb_color = kwargs[ATTR_RGB_COLOR]

        r, g, b = self._attr_rgb_color

        if ATTR_BRIGHTNESS in kwargs:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]

        if self._music_active:
            await self._write_music()
            return

        # Always convert to the device's 0-100 scale, even when brightness
        # wasn't explicitly passed (e.g. a color-only call while already on).
        brightness = int(self._attr_brightness * 100 / 255)

        if self._attr_effect and ATTR_RGB_COLOR not in kwargs:
            payload = self._build_effect_payload(self._attr_effect)
        else:
            payload = self._pg.get_rgb_payload(
                *map_rgb((r, g, b), self.settings.rgb_order), brightness
            )

        self._attr_is_on = True
        await self._send_payload(payload)

    @serialized
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light."""
        self._attr_is_on = False
        self._music_active = False
        self._attr_effect = None
        payload = self._pg.send_led_off()
        await self._send_payload(payload)

    async def set_effect(self, effect_name: str, speed: int | None = None) -> None:
        """Set an effect, optionally overriding that effect's speed."""
        if effect_name not in self._pg.EFFECT_MODES:
            raise ValueError("Unknown effect")
        if speed is not None:
            integer(speed, 1, 100)
        await self._async_set_effect_locked(effect_name, speed)

    @serialized
    async def _async_set_effect_locked(
        self, effect_name: str, speed: int | None
    ) -> None:
        """Apply a validated effect without revoking ownership on rejection."""
        self._music_active = False
        if speed is not None:
            self._store_speed(effect_name, speed)

        self._adopt_pending_speed(effect_name)
        self._attr_effect = effect_name
        payload = self._build_effect_payload(effect_name)

        if self._attr_is_on:
            await self._send_payload(payload)

    async def async_service_set_effect(self, effect: str, speed: int | None = None):
        """Preserve the original service field name on integration-owned targets."""
        await self.set_effect(effect, speed)

    async def set_speed(self, speed: int) -> None:
        """Set the speed of the active effect.

        Mirrors the official app, which always stores the value and only
        transmits it when an effect is running: ClassicEffectFragment.
        sendSpeed calls setSpeed unconditionally, then guards the send with
        getMode() > 0. Discarding the value instead would break the natural
        order of setting a speed first and picking an effect second.
        """
        async with self._command_lock:
            if self._music_active:
                raise ValueError("Effect speed does not control microphone modes")
            if type(speed) is not int or not 1 <= speed <= 100:
                raise ValueError("Speed must be an integer from 1 to 100")
            await self._revoke_return()
            if self._attr_effect is None:
                self._pending_speed = speed
                await self._cancel_return()
                self._controls_changed()
                return
            self._store_speed(self._attr_effect, speed)
            await self._cancel_return()
            self._controls_changed()
        # Debouncer may invoke the callback immediately; do not hold its lock.
        if self._attr_is_on and self._speed_debouncer is not None:
            await self._speed_debouncer.async_call()

    def _speed_for(self, effect_name: str | None) -> int:
        """Return the stored speed for an effect, or the device default."""
        if effect_name is None:
            return DEFAULT_SPEED
        return self._effect_speeds.get(effect_name, DEFAULT_SPEED)

    def _store_speed(self, effect_name: str, speed: int) -> None:
        """Record the speed for a specific effect."""
        self._effect_speeds[effect_name] = _clamp_speed(speed)

    def _adopt_pending_speed(self, effect_name: str) -> None:
        """Apply a speed that was set while no effect was active."""
        if self._pending_speed is None:
            return
        self._effect_speeds[effect_name] = self._pending_speed
        self._pending_speed = None

    def _build_effect_payload(self, effect_name: str) -> str:
        """Build an effect payload at that effect's stored speed."""
        device_brightness = max(10, int(self._attr_brightness * 100 / 255))
        return self._pg.get_effect_payload(
            effect_name,
            device_brightness,
            self._speed_for(effect_name),
            map_rgb(self._attr_rgb_color, self.settings.rgb_order),
        )

    async def _async_send_active_effect(self) -> None:
        """Resend the active effect. Debounced entry point for speed changes."""
        async with self._command_lock:
            if self._attr_effect is None or not self._attr_is_on or self._music_active:
                return
            await self._send_payload(self._build_effect_payload(self._attr_effect))

    async def async_added_to_hass(self) -> None:
        """Run when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        await self._load_controls()

        # Restore the last known color/brightness/effect across a HA
        # restart, since the device has no reliable way to be asked for
        # its current state (see _handle_notification).
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"
            if (rgb := last_state.attributes.get(ATTR_RGB_COLOR)) is not None:
                self._attr_rgb_color = tuple(rgb)
            if (brightness := last_state.attributes.get(ATTR_BRIGHTNESS)) is not None:
                self._attr_brightness = brightness
            if (effect := last_state.attributes.get(ATTR_EFFECT)) is not None:
                if effect == MUSIC_EFFECT:
                    # Restored state is optimistic, but must not masquerade as
                    # steady RGB. Merely marking it never restarts device music.
                    self._attr_effect = MUSIC_EFFECT
                    self._music_active = True
                else:
                    self._attr_effect = (
                        effect if effect in self._pg.EFFECT_MODES else None
                    )

        # Per-effect speeds cannot be expressed as entity attributes, so they
        # travel as extra stored data. Without this they reset to defaults on
        # every restart, which would be inconsistent with the effect itself
        # being restored just above.
        if (extra := await self.async_get_last_extra_data()) is not None:
            stored = extra.as_dict().get("effect_speeds")
            if isinstance(stored, dict):
                self._effect_speeds.update(
                    {
                        name: _clamp_speed(value)
                        for name, value in stored.items()
                        if isinstance(value, int)
                    }
                )

        # Collapse bursts of speed changes into one write. An automation bound
        # to an input_number can fire far faster than the device can usefully
        # respond; the official app throttles its own slider for this reason.
        self._speed_debouncer = Debouncer(
            self.hass,
            _LOGGER,
            cooldown=SPEED_SEND_INTERVAL,
            immediate=True,
            function=self._async_send_active_effect,
        )

        # The device may not be advertising when Home Assistant starts, in
        # which case no scanner can see it yet and the initial connect below
        # does nothing. Watch for it appearing rather than staying dead until
        # something happens to send a command.
        self.async_on_remove(
            async_register_callback(
                self.hass,
                self._async_device_seen,
                BluetoothCallbackMatcher(address=self._address),
                BluetoothScanningMode.ACTIVE,
            )
        )

        await self._ensure_connected()

    @callback
    def _async_device_seen(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Connect once a scanner reports the device, if not already connected."""
        if self._connected:
            return
        self.hass.async_create_task(self._ensure_connected())

    @property
    def extra_restore_state_data(self) -> IstripExtraStoredData:
        """Persist per-effect speeds across restarts."""
        return IstripExtraStoredData(effect_speeds=dict(self._effect_speeds))

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity is removed from Home Assistant."""
        await super().async_will_remove_from_hass()
        await self._unload_controls()
        if self._speed_debouncer is not None:
            self._speed_debouncer.async_shutdown()
        await self._disconnect()

    async def _ensure_connected(self) -> None:
        """Ensure BLE connection is established and notifications are enabled."""
        async with self._connect_lock:
            if self._connected and self._client and self._client.is_connected:
                return

            try:
                if self._client:
                    await self._disconnect()

                ble_device = async_ble_device_from_address(
                    self.hass, self._address, connectable=True
                )
                if ble_device is None:
                    # Normal at startup: the lamp simply has not advertised
                    # yet. _async_device_seen retries as soon as a scanner
                    # reports it, so this is not an error.
                    _LOGGER.debug(
                        "No connectable Bluetooth scanner sees %s yet; will "
                        "connect when it is next seen",
                        self._address,
                    )
                    self._attr_available = False
                    return

                self._client = await establish_connection(
                    BleakClientWithServiceCache,
                    ble_device,
                    self._attr_device_info["name"],
                    max_attempts=3,
                )
                _LOGGER.debug("Connected to iStrip device at %s", self._address)

                # Revalidate service membership even for a stored known UUID.
                self._char_uuid = self._discover_char_uuid_from_services()
                if not self._char_uuid:
                    _LOGGER.error(
                        "No lighting-control characteristic on %s", self._address
                    )
                    await self._disconnect()
                    self._attr_available = False
                    return
                self._persist_char_uuid()

                notify_char_uuid = find_notify_char(self._client, self._char_uuid)
                if notify_char_uuid:
                    try:
                        await self._client.start_notify(
                            notify_char_uuid, self._handle_notification
                        )
                        _LOGGER.debug(
                            "Subscribed to BLE notifications on %s", notify_char_uuid
                        )
                    # bleak/BLE backends raise a wide, inconsistent variety of
                    # errors here; any failure should be logged the same way.
                    except Exception:  # noqa: BLE001
                        _LOGGER.warning(
                            "Could not subscribe to notifications on %s",
                            notify_char_uuid,
                        )
                else:
                    _LOGGER.debug(
                        "No notify-capable characteristic found on %s; "
                        "IR-remote state sync will not be available",
                        self._address,
                    )

                # The device requires a one-time "join group" handshake right
                # after connecting, before it will act on any other command.
                try:
                    join_payload = self._pg.get_join_group_payload()
                    await self._client.write_gatt_char(
                        self._char_uuid, bytes.fromhex(join_payload), response=False
                    )
                    _LOGGER.debug("Sent join-group handshake to %s", self._address)
                # See the notify-subscribe except above: BLE errors here are
                # similarly broad and unpredictable.
                except Exception:  # noqa: BLE001
                    _LOGGER.warning(
                        "Failed to send join-group handshake to %s", self._address
                    )
                    await self._disconnect()
                    self._attr_available = False
                    return

                # Only mark connected once the join handshake has gone out,
                # so a waiting caller never sends a command ahead of it.
                self._connected = True
                self._attr_available = True

            # Connection/discovery can fail in many BLE-stack-specific ways;
            # treat any of them as a failed connection attempt.
            except Exception:  # noqa: BLE001
                _LOGGER.error("Failed to connect to device at %s", self._address)
                await self._disconnect()
                self._attr_available = False

    def _persist_char_uuid(self) -> None:
        """Store a runtime-discovered characteristic back on the config entry.

        Without this the entry keeps no char_uuid at all after the v3
        migration clears an OTA characteristic, and every connection pays for
        discovery again.
        """
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        if entry is None or entry.data.get("char_uuid") == self._char_uuid:
            return

        self.hass.config_entries.async_update_entry(
            entry, data={**entry.data, "char_uuid": self._char_uuid}
        )
        _LOGGER.debug(
            "Stored characteristic %s on the config entry for %s",
            self._char_uuid,
            self._address,
        )

    def _discover_char_uuid_from_services(self) -> str | None:
        """Find the best writable characteristic UUID from the connected client."""
        if not self._client or not self._client.is_connected:
            return None

        writable_uuids: list[str] = []
        for service in self._client.services:
            if str(service.uuid).lower() != CONTROL_SERVICE_UUID:
                continue
            for char in service.characteristics:
                if (
                    "write" in char.properties
                    or "write-without-response" in char.properties
                ):
                    writable_uuids.append(str(char.uuid))

        for known_uuid in KNOWN_CHAR_UUIDS:
            if known_uuid in writable_uuids:
                return known_uuid

        return None

    async def _disconnect(self) -> None:
        """Disconnect from the BLE device."""
        self._confirmed_static = False
        self._foreign_notification()
        if self._client:
            try:
                if self._client.is_connected:
                    await self._client.disconnect()
                _LOGGER.debug("Disconnected from iStrip device at %s", self._address)
            except Exception:  # noqa: BLE001 - disconnect can fail in many ways
                _LOGGER.error("Error disconnecting from %s", self._address)
            finally:
                self._client = None
                self._connected = False

    def _handle_notification(self, sender: int, data: bytearray) -> None:
        """Handle BLE notification from device."""
        try:
            decrypted = self._pg.decrypt_payload(bytes(data))
            state = self._pg.parse_state(decrypted)

            if self._is_expected_echo(bytes(data)):
                return
            if state["command_type"] in (CommandType.RGB, CommandType.RHYTHM):
                self._foreign_notification()

            if state["command_type"] == CommandType.RHYTHM:
                # External music is dynamic even if its style is not recognised.
                # Do not advertise it as steady lighting to status-light clients.
                self._music_active = True
                self._confirmed_static = False
                self._attr_is_on = True
                self._attr_effect = MUSIC_EFFECT
                self._controls_changed()
                return

            # The device echoes the join-group handshake back as a
            # notification right after connecting. That echo decodes to
            # R=G=B=0/brightness=0 -- it's not a real state update, so
            # applying it would wrongly show the light as off/black on
            # every reconnect (HA restart, ESP32 reboot, etc.).
            if state["command_type"] != CommandType.RGB:
                return

            self._music_active = False
            self._attr_is_on = state["is_on"]
            self._attr_rgb_color = map_rgb(
                state["rgb"], self.settings.rgb_order, inverse=True
            )
            self._attr_brightness = state["brightness"]
            self._attr_effect = state["effect"]
            self._confirmed_static = state["effect"] is None
            # A notification carries the speed of the effect reported in the
            # same frame, so attribute it to that effect rather than to a
            # single global value. This is how a physical IR remote change
            # gets reflected back into the per-effect table.
            if state["effect"] is not None:
                self._store_speed(state["effect"], state["speed"])

            self.schedule_update_ha_state()
            self._controls_changed()

        except Exception:
            _LOGGER.exception("Error handling notification from %s", self._address)

    async def _send_payload(
        self, hex_payload: str, retries: int = 2, retry_delay: float = 3.0
    ) -> None:
        """Send a payload to the device via BLE.

        The ESP32 Bluetooth proxy can occasionally crash and reboot
        mid-connection, recovering within a few seconds. Retrying gives it
        a chance to come back before we surface a failure to Home Assistant.
        """
        last_exc: Exception | None = None
        if self._restoring:
            # Never reconnect/retry an automatic return across an uncertain link.
            retries = 1
            if not self._connected or not self._client or not self._client.is_connected:
                raise ConnectionError("Timed return lost its original BLE connection")

        for attempt in range(1, retries + 1):
            try:
                await self._ensure_connected()

                if not self._client or not self._client.is_connected:
                    raise ConnectionError("Not connected to device")

                if self._char_uuid not in KNOWN_CHAR_UUIDS:
                    raise ValueError(
                        "Only the lighting-control characteristic is allowed"
                    )
                if self._restoring and not self._timed_ownership:
                    raise ConnectionError("Timed return no longer owns the light")

                self._remember_echo(hex_payload)
                await self._client.write_gatt_char(
                    self._char_uuid, bytes.fromhex(hex_payload), response=False
                )
                plaintext = self._pg.decrypt_payload(bytes.fromhex(hex_payload))
                self._confirmed_static = (
                    plaintext[4] == CommandType.RGB and plaintext[6] == 0
                )
                return

            # Write failures span BleakError, timeouts, and ESPHome-proxy-
            # specific errors; any of them means "retry the send".
            except Exception as err:  # noqa: BLE001
                last_exc = err
                self._connected = False
                self._confirmed_static = False
                self._attr_available = False
                if attempt < retries:
                    _LOGGER.warning(
                        "Send attempt %d/%d to %s failed (%s), retrying in %.1fs",
                        attempt,
                        retries,
                        self._address,
                        err,
                        retry_delay,
                    )
                    await asyncio.sleep(retry_delay)

        _LOGGER.error(
            "Failed to send BLE payload to %s after %d attempts", self._address, retries
        )
        raise last_exc
