# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hysteresis state machine for regime signals.

Hysteresis — where the threshold to flip up differs from the threshold to
flip back — is the standard control-systems remedy for a noisy input whose
state should change in discrete steps. In regime detection it prevents a
signal that hovers around a threshold from flipping the regime every day.

The state machine here is generic: it accepts any number of named zones and
asymmetric enter/exit cutoffs, so the same mechanism handles VIX (normal →
elevated → crisis) or any other staircase signal you care to implement.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol


@dataclass(frozen=True)
class ZoneBoundary:
    """Describes the asymmetric cutoffs to enter and exit a hysteresis zone.

    ``enter`` is the value at which the current value must be >= to flip INTO
    the zone when moving up. ``exit`` is the value at which the current value
    must drop BELOW to flip OUT of the zone when moving down. For stability,
    ``enter`` should exceed ``exit``.
    """

    name: str
    enter: float
    exit: float


class HysteresisStore(Protocol):
    """Optional persistence interface for zone state.

    Implementations might persist to Redis, a database, or a local file so
    the zone survives process restarts. A no-op implementation is fine for
    tests and short-lived jobs.
    """

    def load(self) -> tuple[str, datetime | None] | None:
        """Return (zone_name, changed_at) or None if no prior state."""
        ...

    def save(self, zone: str, changed_at: datetime) -> None:
        """Persist the zone transition timestamp."""
        ...


@dataclass
class HysteresisState:
    """Tracks which zone a signal currently occupies and when it last changed.

    Typical usage::

        state = HysteresisState(
            default_zone="normal",
            zones=[
                ZoneBoundary("elevated", enter=26.0, exit=23.0),
                ZoneBoundary("crisis", enter=36.0, exit=33.0),
            ],
        )
        new_zone = state.update(current_vix)
        if new_zone != "normal":
            # take action
            ...

    The zones list must be ordered from lowest to highest severity.
    """

    default_zone: str
    zones: list[ZoneBoundary]
    current_zone: str = ""
    changed_at: datetime | None = None
    store: HysteresisStore | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.current_zone:
            self.current_zone = self.default_zone
        # Restore from store if available — best-effort, silent on failure.
        if self.store is not None:
            with contextlib.suppress(Exception):
                prior = self.store.load()
                if prior is not None:
                    self.current_zone, self.changed_at = prior

    def update(self, value: float) -> str:
        """Advance state based on a new signal reading and return current zone."""
        old_zone = self.current_zone
        self.current_zone = self._next_zone(value)
        if self.current_zone != old_zone:
            self.changed_at = datetime.now(UTC)
            if self.store is not None:
                with contextlib.suppress(Exception):
                    self.store.save(self.current_zone, self.changed_at)
        return self.current_zone

    def _next_zone(self, value: float) -> str:
        """Compute the next zone based on value and current zone (hysteresis logic)."""
        # Sort zones lowest → highest severity.
        zones_by_enter = sorted(self.zones, key=lambda z: z.enter)
        current_index = self._current_zone_index(zones_by_enter)

        # When in a zone, first check if we've escalated past the next zone.
        # Crossing multiple zones in one update is possible (e.g., a VIX flash
        # spike can go normal → crisis on one print) — walk up by enter, down
        # by exit.
        next_zone = self.current_zone
        # Try to escalate
        for i, zone in enumerate(zones_by_enter):
            if i <= current_index:
                continue
            if value >= zone.enter:
                next_zone = zone.name
        if next_zone != self.current_zone:
            return next_zone

        # Try to de-escalate: if below current zone's exit, drop to next lower.
        if current_index >= 0:
            current_zone = zones_by_enter[current_index]
            if value < current_zone.exit:
                # Find the next-lower zone we'd still be in
                candidate = self.default_zone
                for i in range(current_index - 1, -1, -1):
                    lower = zones_by_enter[i]
                    if value >= lower.exit:
                        candidate = lower.name
                        break
                return candidate

        return self.current_zone

    def _current_zone_index(self, zones_by_enter: list[ZoneBoundary]) -> int:
        """Return index of current zone in zones_by_enter, or -1 if default zone."""
        for i, zone in enumerate(zones_by_enter):
            if zone.name == self.current_zone:
                return i
        return -1

    def hours_in_zone(self) -> float | None:
        """How many hours the signal has spent in the current zone."""
        if self.changed_at is None:
            return None
        return (datetime.now(UTC) - self.changed_at).total_seconds() / 3600.0

    def to_dict(self) -> dict[str, object]:
        return {
            "zone": self.current_zone,
            "changed_at": self.changed_at.isoformat() if self.changed_at else None,
            "hours_in_zone": self.hours_in_zone(),
            "zones": [{"name": z.name, "enter": z.enter, "exit": z.exit} for z in self.zones],
        }


__all__ = ["HysteresisState", "HysteresisStore", "ZoneBoundary"]
