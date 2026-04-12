# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Unit tests for hysteresis state machine."""

from __future__ import annotations

import pytest

from nexus_core.engine.regime import HysteresisState, ZoneBoundary


@pytest.mark.unit
class TestHysteresisState:
    def _vix_zones(self) -> list[ZoneBoundary]:
        return [
            ZoneBoundary("elevated", enter=26.0, exit=23.0),
            ZoneBoundary("crisis", enter=36.0, exit=33.0),
        ]

    def test_starts_in_default(self) -> None:
        state = HysteresisState(default_zone="normal", zones=self._vix_zones())
        assert state.current_zone == "normal"

    def test_flips_to_elevated_when_above_enter(self) -> None:
        state = HysteresisState(default_zone="normal", zones=self._vix_zones())
        assert state.update(26.5) == "elevated"

    def test_does_not_flip_between_exit_and_enter(self) -> None:
        """Dead zone — must cross enter to flip up, exit to flip back."""
        state = HysteresisState(default_zone="normal", zones=self._vix_zones())
        # Start normal. VIX rises to 24.5 (between exit=23, enter=26) → stay normal.
        assert state.update(24.5) == "normal"
        # VIX rises above 26 → flip to elevated.
        assert state.update(27.0) == "elevated"
        # VIX drops back to 24.5 → stay elevated (hysteresis).
        assert state.update(24.5) == "elevated"
        # VIX drops below 23 → flip back to normal.
        assert state.update(22.5) == "normal"

    def test_can_escalate_two_zones_at_once(self) -> None:
        """A VIX flash spike can go normal → crisis in one update."""
        state = HysteresisState(default_zone="normal", zones=self._vix_zones())
        assert state.update(40.0) == "crisis"

    def test_de_escalates_from_crisis_to_elevated(self) -> None:
        state = HysteresisState(default_zone="normal", zones=self._vix_zones())
        state.update(40.0)
        assert state.current_zone == "crisis"
        assert state.update(32.0) == "elevated"

    def test_tracks_transition_time(self) -> None:
        state = HysteresisState(default_zone="normal", zones=self._vix_zones())
        assert state.changed_at is None
        state.update(30.0)
        assert state.changed_at is not None
        # hours_in_zone returns a number after transition
        hours = state.hours_in_zone()
        assert hours is not None
        assert hours >= 0

    def test_to_dict(self) -> None:
        state = HysteresisState(default_zone="normal", zones=self._vix_zones())
        state.update(30.0)
        payload = state.to_dict()
        assert payload["zone"] == "elevated"
        assert "changed_at" in payload
        assert len(payload["zones"]) == 2
