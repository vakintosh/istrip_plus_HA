"""Shared BLE GATT helpers for the iStrip+ integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bleak_retry_connector import BleakClientWithServiceCache


def find_notify_char(
    client: BleakClientWithServiceCache, write_uuid: str | None
) -> str | None:
    """Find a notify characteristic, preferring one in the same service as `write_uuid`."""
    same_service: list[str] = []
    other: list[str] = []

    for service in client.services:
        has_write = any(str(c.uuid) == write_uuid for c in service.characteristics)
        for char in service.characteristics:
            if "notify" in char.properties or "indicate" in char.properties:
                (same_service if has_write else other).append(str(char.uuid))

    if same_service:
        return same_service[0]
    return other[0] if other else None
