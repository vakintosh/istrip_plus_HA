"""Pure control settings and conservative timed-return journal.

Protocol facts are public; music style IDs are related-app hypotheses, not
hardware-qualified iStrip+ support. No app code is incorporated here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import permutations
from typing import Any

MUSIC_STYLES = {"Soft": 4, "Classic": 5, "Dynamic": 3, "Disco": 2}
MUSIC_EFFECT = "Controller microphone (experimental)"
RGB_ORDERS = tuple("".join(p) for p in permutations("RGB"))


def integer(value: int, low: int, high: int) -> int:
    """Reject booleans, floats and values outside the protocol range."""
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"Expected an integer from {low} to {high}")
    return value


def map_rgb(rgb: tuple[int, int, int], order: str, *, inverse: bool = False):
    """Apply a host-side channel permutation (not device opcode 5)."""
    if order not in RGB_ORDERS:
        raise ValueError("Unknown RGB order")
    if inverse:
        return tuple(rgb[order.index(c)] for c in "RGB")
    return tuple(rgb["RGB".index(c)] for c in order)


@dataclass
class ControlSettings:
    """Persistent preferences; enabling the integration never starts music."""

    experimental_music: bool = False
    sensitivity: int = 100
    music_style: str = "Soft"
    rgb_order: str = "RGB"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ControlSettings:
        """Validate persisted preferences before use."""
        result = cls()
        if type(data.get("experimental_music")) is bool:
            result.experimental_music = data["experimental_music"]
        if type(data.get("sensitivity")) is int and 0 <= data["sensitivity"] <= 100:
            result.sensitivity = data["sensitivity"]
        if data.get("music_style") in MUSIC_STYLES:
            result.music_style = data["music_style"]
        if data.get("rgb_order") in RGB_ORDERS:
            result.rgb_order = data["rgb_order"]
        return result

    def as_dict(self) -> dict[str, Any]:
        """Serialise only non-secret preferences."""
        return asdict(self)


class ReturnJournal:
    """Persist ownership evidence, never infer ownership across a restart."""

    def __init__(self) -> None:
        self.record: dict[str, Any] | None = None

    def load(self, record: dict[str, Any] | None) -> None:
        """An interrupted write or outage always needs explicit reconciliation."""
        if record:
            self.record = {**record, "status": "reconciliation_required"}

    def begin(self, deadline: float, snapshot: dict[str, Any]) -> None:
        """Record the pre-music static state before any hardware write."""
        if self.record:
            raise ValueError("Resolve or cancel the existing timed return first")
        self.record = {"deadline": deadline, "snapshot": snapshot, "status": "active"}

    def uncertain(self) -> None:
        """Keep the snapshot but prohibit automatic writes."""
        if self.record:
            self.record["status"] = "reconciliation_required"

    @property
    def active(self) -> bool:
        """Only uninterrupted ownership allows automatic return."""
        return self.record is not None and self.record.get("status") == "active"
