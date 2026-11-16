"""HA-side controls sharing the light's single BLE connection."""

from __future__ import annotations

import asyncio
import logging
import time
from functools import wraps

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .controls import (
    MUSIC_EFFECT,
    MUSIC_STYLES,
    RGB_ORDERS,
    ControlSettings,
    ReturnJournal,
    integer,
    map_rgb,
)

_LOGGER = logging.getLogger(__name__)


def serialized(method):
    """Serialize user commands and relinquish any temporary ownership first."""

    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        async with self._command_lock:
            try:
                await self._revoke_return()
                result = await method(self, *args, **kwargs)
                await self._cancel_return()
                return result
            finally:
                self._controls_changed()

    return wrapped


class ControllerMixin:
    """Controls implemented by IstripLight, not by a second BLE client."""

    def _init_controls(self):
        self.settings = ControlSettings()
        self.journal = ReturnJournal()
        self._command_lock = asyncio.Lock()
        self._music_active = False
        self._cancel_timer = None
        self._store = None
        self._restoring = False
        self._timed_ownership = False
        self._expected_echoes = {}
        self._confirmed_static = False

    async def _load_controls(self):
        self._store = Store(self.hass, 1, f"{DOMAIN}_controls_{self._entry_id}")
        stored = await self._store.async_load() or {}
        self.settings = ControlSettings.from_dict(stored.get("settings", {}))
        self.journal.load(stored.get("return"))
        if self.journal.record:
            await self._save_controls()

    async def _save_controls(self):
        if self._store:
            await self._store.async_save(
                {"settings": self.settings.as_dict(), "return": self.journal.record}
            )

    def _controls_changed(self):
        if self.hass:
            self.async_write_ha_state()
            async_dispatcher_send(self.hass, f"{DOMAIN}_{self._entry_id}_controls")

    async def _cancel_return(self):
        """Explicit user action relinquishes ownership, never restores blindly."""
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None
        self._timed_ownership = False
        if self.journal.record:
            record = self.journal.record
            self.journal.record = None
            try:
                await self._save_controls()
            except BaseException:
                # A failed clear must not discard the only in-memory snapshot.
                self.journal.record = record
                self.journal.uncertain()
                raise

    async def _revoke_return(self):
        """Keep recovery evidence until a new explicit command succeeds."""
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None
        self._timed_ownership = False
        if self.journal.record:
            self.journal.uncertain()
            await self._save_controls()

    def _foreign_notification(self):
        """Unknown physical changes revoke automatic restoration immediately."""
        if self.journal.record:
            self._timed_ownership = False
            self.journal.uncertain()
            if self._cancel_timer:
                self._cancel_timer()
                self._cancel_timer = None
            self.hass.async_create_task(self._save_controls())
            self._controls_changed()

    def _remember_echo(self, payload: str):
        now = time.monotonic()
        self._expected_echoes = {
            key: expiry for key, expiry in self._expected_echoes.items() if expiry > now
        }
        self._expected_echoes[payload] = now + 5

    def _is_expected_echo(self, data: bytes) -> bool:
        expiry = self._expected_echoes.get(data.hex(), 0)
        return expiry > time.monotonic()

    async def _write_static(self, *, is_on=True, rgb=None, brightness=None):
        rgb = tuple(rgb if rgb is not None else self._attr_rgb_color)
        brightness = brightness if brightness is not None else self._attr_brightness
        if is_on:
            payload = self._pg.get_rgb_payload(
                *map_rgb(rgb, self.settings.rgb_order), int(brightness * 100 / 255)
            )
        else:
            payload = self._pg.send_led_off()
        await self._send_payload(payload)
        self._music_active = False
        self._attr_effect = None
        self._attr_is_on = is_on
        self._attr_rgb_color = rgb
        self._attr_brightness = brightness

    def _require_music_permission(self):
        if not self.settings.experimental_music:
            raise ServiceValidationError(
                "Sound reactive needs permission first. Open Settings > Devices & "
                "services > iStrip > Configure and enable Allow experimental "
                "sound-reactive control. This enables permission, not music."
            )

    async def _write_music(self):
        self._require_music_permission()
        # Send retained static brightness first: some controllers need an on frame.
        await self._write_static()
        await self._send_payload(
            self._pg.get_microphone_payload(
                self.settings.music_style, self.settings.sensitivity
            )
        )
        self._music_active = True
        self._attr_effect = MUSIC_EFFECT

    async def async_set_control(self, key, value):
        """Set a native HA number/select/switch, under one command lock."""
        async with self._command_lock:
            if key == "sensitivity":
                integer(value, 0, 100)
            elif key == "music_style":
                if value not in MUSIC_STYLES:
                    raise ValueError("Unknown music style")
            elif key == "rgb_order":
                if value not in RGB_ORDERS:
                    raise ValueError("Unknown RGB order")
                if self._music_active or self._attr_effect:
                    raise ValueError("Select static lighting before changing RGB order")
            elif key in ("microphone", "experimental_music"):
                if type(value) is not bool:
                    raise ValueError("Expected boolean")
            else:
                raise ValueError("Unknown control")
            if key == "microphone" and value:
                # Invalid activation must not revoke an existing recovery owner.
                self._require_music_permission()
            try:
                await self._revoke_return()
                if key == "microphone":
                    if value:
                        await self._write_music()
                    elif self._music_active or not self._confirmed_static:
                        await self._write_static(is_on=self._attr_is_on)
                else:
                    previous = getattr(self.settings, key)
                    setattr(self.settings, key, value)
                    # Save before writes so an ambiguous write retains its settings.
                    try:
                        await self._save_controls()
                    except BaseException:
                        # A failed save must not silently apply a setting in RAM.
                        # Restore the last accepted value so a retry can persist it.
                        setattr(self.settings, key, previous)
                        raise
                    if key == "experimental_music" and not value and self._music_active:
                        await self._write_static(is_on=self._attr_is_on)
                    elif self._music_active:
                        await self._write_music()
                    elif key == "rgb_order" and self._attr_is_on:
                        await self._write_static()
                await self._cancel_return()
            finally:
                self._controls_changed()

    async def async_start_timed_music(self, duration):
        """Enter music temporarily; only static initial states are restorable."""
        integer(duration, 1, 86400)
        async with self._command_lock:
            self._require_music_permission()
            if self._attr_effect or self._music_active:
                raise ValueError("Start timed music from static lighting or off")
            if not self._confirmed_static:
                raise ValueError(
                    "Send an explicit static or off command after startup first"
                )
            snapshot = {
                "is_on": self._attr_is_on,
                "rgb": list(self._attr_rgb_color),
                "brightness": self._attr_brightness,
            }
            self.journal.begin(time.time() + duration, snapshot)
            try:
                await self._save_controls()
                if not self.journal.active:
                    raise ConnectionError("Light changed before timed music")
                self._timed_ownership = True
                await self._write_music()
                if not self._timed_ownership:
                    raise ConnectionError("Light changed while starting timed music")
                delay = max(0, self.journal.record["deadline"] - time.time())
                self._cancel_timer = async_call_later(
                    self.hass, delay, self._return_due
                )
            except BaseException:
                self._timed_ownership = False
                self.journal.uncertain()
                await self._save_recovery()
                raise
            finally:
                self._controls_changed()

    async def _return_due(self, _now):
        async with self._command_lock:
            self._cancel_timer = None
            if not self.journal.active or not self._timed_ownership:
                return
            record = self.journal.record
            snapshot = record["snapshot"]
            self._restoring = True
            try:
                # Persist before attempting a write. A crash mid-write is ambiguous.
                record["status"] = "restoring"
                await self._save_controls()
                if not self._timed_ownership:
                    raise ConnectionError("Light changed before timed return")
                await self._write_static(**snapshot)
                if not self._timed_ownership:
                    raise ConnectionError("Light changed during timed return")
                await self._cancel_return()
            except BaseException as err:
                self.journal.record = record
                self.journal.uncertain()
                self._timed_ownership = False
                await self._save_recovery()
                if not isinstance(err, Exception):
                    raise
                _LOGGER.exception(
                    "Timed return needs reconciliation; no automatic retry"
                )
            finally:
                self._restoring = False
                self._controls_changed()

    async def _save_recovery(self):
        """Retain RAM evidence if storage is unavailable; never retry hardware."""
        try:
            await self._save_controls()
        except Exception:
            _LOGGER.exception(
                "Cannot persist timed-return recovery; snapshot retained in memory"
            )

    async def async_cancel_timed_return(self):
        """Discard a recovery record without changing hardware."""
        async with self._command_lock:
            await self._cancel_return()
            self._controls_changed()

    async def _unload_controls(self):
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None
        if self.journal.record:
            self.journal.uncertain()
            self._timed_ownership = False
            await self._save_controls()
