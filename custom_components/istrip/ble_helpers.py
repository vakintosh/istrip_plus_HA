"""Shared BLE GATT helpers for the iStrip+ integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import CONTROL_NOTIFY_CHAR_UUID, CONTROL_SERVICE_UUID, KNOWN_CHAR_UUIDS

if TYPE_CHECKING:
    from bleak_retry_connector import BleakClientWithServiceCache


def find_notify_char(
    client: BleakClientWithServiceCache, write_uuid: str | None
) -> str | None:
    """Use only the documented lighting notify UUID, never OTA fallbacks."""
    if write_uuid not in KNOWN_CHAR_UUIDS:
        return None
    for service in client.services:
        if str(service.uuid).lower() != CONTROL_SERVICE_UUID:
            continue
        has_write = any(str(c.uuid) == write_uuid for c in service.characteristics)
        for char in service.characteristics:
            if (
                has_write
                and str(char.uuid).lower() == CONTROL_NOTIFY_CHAR_UUID
                and ("notify" in char.properties or "indicate" in char.properties)
            ):
                return CONTROL_NOTIFY_CHAR_UUID
    return None
