# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Unit tests for the forced-liquidation dampener."""

from __future__ import annotations

import pytest

from nexus_core.engine.regime import (
    DampenerSignal,
    ForcedLiquidationThresholds,
    detect_breadth_collapse,
    detect_correlation_spike,
    detect_vix_spike,
    detect_volume_spike,
    evaluate_dampener,
)


@pytest.mark.unit
class TestVixSpike:
    def test_large_jump_detected(self) -> None:
        t = ForcedLiquidationThresholds()
        result = detect_vix_spike(current_vix=28.0, prior_vix=20.0, thresholds=t)
        assert result.detected is True
        assert result.available is True
        # 40% jump
        assert result.value == 40.0

    def test_small_jump_not_detected(self) -> None:
        t = ForcedLiquidationThresholds()
        result = detect_vix_spike(current_vix=21.0, prior_vix=20.0, thresholds=t)
        assert result.detected is False

    def test_no_prior_falls_back_to_absolute(self) -> None:
        t = ForcedLiquidationThresholds()
        result = detect_vix_spike(current_vix=40.0, prior_vix=None, thresholds=t)
        assert result.detected is True

    def test_unavailable_when_current_missing(self) -> None:
        t = ForcedLiquidationThresholds()
        result = detect_vix_spike(current_vix=None, prior_vix=25.0, thresholds=t)
        assert result.available is False


@pytest.mark.unit
class TestBreadthCollapse:
    def test_collapse_detected(self) -> None:
        t = ForcedLiquidationThresholds()
        result = detect_breadth_collapse(pct_above_200dma=15.0, thresholds=t)
        assert result.detected is True
        assert result.value == 85.0  # 100 - 15

    def test_normal_not_detected(self) -> None:
        t = ForcedLiquidationThresholds()
        result = detect_breadth_collapse(pct_above_200dma=60.0, thresholds=t)
        assert result.detected is False


@pytest.mark.unit
class TestCorrelationSpike:
    def test_high_correlation_detected(self) -> None:
        t = ForcedLiquidationThresholds()
        # Perfectly correlated series
        series = [
            [-0.01, -0.02, -0.015, -0.03, -0.025],
            [-0.01, -0.02, -0.015, -0.03, -0.025],
            [-0.01, -0.02, -0.015, -0.03, -0.025],
        ]
        result = detect_correlation_spike(series, thresholds=t)
        assert result.detected is True

    def test_decorrelated_not_detected(self) -> None:
        t = ForcedLiquidationThresholds()
        # Genuinely independent series — random-walk returns.
        series = [
            [0.012, -0.004, 0.018, -0.002, 0.007],  # mostly up
            [-0.001, -0.005, 0.002, 0.004, -0.003],  # flat-ish
            [0.003, 0.009, 0.001, 0.002, 0.004],  # small up
        ]
        result = detect_correlation_spike(series, thresholds=t)
        assert result.available is True
        assert result.detected is False


@pytest.mark.unit
class TestVolumeSpike:
    def test_spike_on_down_day(self) -> None:
        t = ForcedLiquidationThresholds()
        volumes = [1.0] * 20 + [3.0]  # 3x avg
        closes = [100.0] * 20 + [95.0]  # down day
        result = detect_volume_spike(volumes, closes, thresholds=t)
        assert result.detected is True

    def test_spike_on_up_day_not_detected(self) -> None:
        t = ForcedLiquidationThresholds()
        volumes = [1.0] * 20 + [3.0]
        closes = [100.0] * 20 + [105.0]  # up day
        result = detect_volume_spike(volumes, closes, thresholds=t)
        assert result.detected is False


@pytest.mark.unit
class TestEvaluate:
    def test_fires_when_three_of_four(self) -> None:
        signals = [
            DampenerSignal("vix_spike", detected=True, available=True),
            DampenerSignal("breadth_collapse", detected=True, available=True),
            DampenerSignal("correlation_spike", detected=True, available=True),
            DampenerSignal("volume_spike", detected=False, available=True),
        ]
        result = evaluate_dampener(*signals)
        assert result.dampener_active is True
        assert result.signals_firing == 3
        assert result.signals_available == 4

    def test_does_not_fire_on_two_of_four(self) -> None:
        signals = [
            DampenerSignal("vix_spike", detected=True, available=True),
            DampenerSignal("breadth_collapse", detected=True, available=True),
            DampenerSignal("correlation_spike", detected=False, available=True),
            DampenerSignal("volume_spike", detected=False, available=True),
        ]
        result = evaluate_dampener(*signals)
        assert result.dampener_active is False

    def test_reduced_threshold_when_limited_signals(self) -> None:
        """With only 2 signals available, 2 firing is enough."""
        signals = [
            DampenerSignal("vix_spike", detected=True, available=True),
            DampenerSignal("breadth_collapse", detected=True, available=True),
            DampenerSignal("correlation_spike", detected=False, available=False),
            DampenerSignal("volume_spike", detected=False, available=False),
        ]
        result = evaluate_dampener(*signals)
        assert result.dampener_active is True

    def test_weight_adjustment(self) -> None:
        t = ForcedLiquidationThresholds()
        no_fire_signals = [
            DampenerSignal("a", detected=False, available=True),
            DampenerSignal("b", detected=False, available=True),
        ]
        result = evaluate_dampener(*no_fire_signals, thresholds=t)
        assert result.regime_weight_adjustment == 1.0

        fire_signals = [
            DampenerSignal("a", detected=True, available=True),
            DampenerSignal("b", detected=True, available=True),
            DampenerSignal("c", detected=True, available=True),
            DampenerSignal("d", detected=True, available=True),
        ]
        result = evaluate_dampener(*fire_signals, thresholds=t)
        assert result.regime_weight_adjustment == t.weight_adjustment_when_active
