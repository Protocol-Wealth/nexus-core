# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Unit tests for regime thresholds."""

from __future__ import annotations

import pytest

from nexus_core.engine.regime import (
    ForcedLiquidationThresholds,
    RegimeThresholds,
    ThresholdBundle,
)


@pytest.mark.unit
class TestRegimeThresholds:
    def test_defaults_are_sensible(self) -> None:
        t = RegimeThresholds()
        assert 0 < t.gold_spx_growth_max < t.gold_spx_transition_max
        assert t.dxy_weak < t.dxy_strong
        assert t.vix_complacent < t.vix_elevated < t.vix_crisis
        assert t.spreads_tight < t.spreads_normal_max < t.spreads_wide_max

    def test_hysteresis_has_dead_zone(self) -> None:
        t = RegimeThresholds()
        # Enter must be above exit — otherwise hysteresis doesn't work.
        assert t.vix_elevated_enter > t.vix_elevated_exit
        assert t.vix_crisis_enter > t.vix_crisis_exit
        # Crisis enter should be above elevated enter.
        assert t.vix_crisis_enter > t.vix_elevated_enter

    def test_immutable(self) -> None:
        t = RegimeThresholds()
        with pytest.raises(Exception):
            t.gold_spx_growth_max = 0.99  # type: ignore[misc]

    def test_custom_thresholds(self) -> None:
        t = RegimeThresholds(
            gold_spx_growth_max=0.40,
            vix_elevated_enter=30.0,
            vix_elevated_exit=25.0,
        )
        assert t.gold_spx_growth_max == 0.40
        assert t.vix_elevated_enter == 30.0


@pytest.mark.unit
class TestForcedLiquidationThresholds:
    def test_defaults(self) -> None:
        t = ForcedLiquidationThresholds()
        assert t.vix_1d_spike_pct > 0
        assert t.breadth_collapse_pct > 50
        assert 0 < t.cross_asset_correlation_spike <= 1.0
        assert t.volume_multiple_20d > 1.0
        assert 0 <= t.weight_adjustment_when_active <= 1.0


@pytest.mark.unit
class TestThresholdBundle:
    def test_default_bundle(self) -> None:
        bundle = ThresholdBundle()
        assert isinstance(bundle.regime, RegimeThresholds)
        assert isinstance(bundle.forced_liquidation, ForcedLiquidationThresholds)
