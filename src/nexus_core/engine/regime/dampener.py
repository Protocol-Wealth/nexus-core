# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Forced-liquidation dampener.

When markets deleverage mechanically — risk-parity blowups, vol-targeting
cascades, options hedging unwinds — the surface-level signals (VIX, breadth,
cross-asset correlations) fire together and look exactly like a regime
change. In practice these events often reverse within days, so a naïve
regime classifier will over-rotate into HARD_ASSET or DEFLATION and then
whipsaw back.

The dampener is a filter that checks for the *signature* of forced selling:

    1. VIX 1-day spike > 30%
    2. Breadth collapse (>80% of components below 200DMA)
    3. Cross-asset correlation spike (avg pairwise > 0.8 across diversified assets)
    4. Volume spike > 2x 20-day avg on a down day

When enough signals fire, the dampener tells the regime classifier to *hold*
the prior regime for now. This is a deliberately conservative policy — it
errs on the side of stability.

The functions here are pure: you pass in the relevant time-series data and
get back a dampener decision. Fetching the data is the caller's problem.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .thresholds import ForcedLiquidationThresholds


@dataclass
class DampenerSignal:
    """One of the 4 dampener signals."""

    name: str
    detected: bool
    available: bool
    value: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "detected": self.detected,
            "available": self.available,
            "value": self.value,
        }


@dataclass
class DampenerResult:
    """Overall dampener decision and supporting diagnostics."""

    forced_liquidation_detected: bool
    signals_firing: int
    signals_available: int
    signals: list[DampenerSignal]
    dampener_active: bool
    regime_weight_adjustment: float
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "forced_liquidation_detected": self.forced_liquidation_detected,
            "signals_firing": self.signals_firing,
            "signals_available": self.signals_available,
            "signals": [s.to_dict() for s in self.signals],
            "dampener_active": self.dampener_active,
            "regime_weight_adjustment": self.regime_weight_adjustment,
            "note": self.note,
        }


def detect_vix_spike(
    current_vix: float | None,
    prior_vix: float | None,
    thresholds: ForcedLiquidationThresholds,
) -> DampenerSignal:
    """Detect a > 30% single-day VIX jump."""
    if current_vix is None:
        return DampenerSignal("vix_spike", detected=False, available=False)
    if prior_vix is None or prior_vix <= 0:
        # Fall back to absolute level: still capture clear crisis readings.
        return DampenerSignal(
            "vix_spike",
            detected=current_vix > 35.0,
            available=True,
            value=None,
        )
    change_pct = ((current_vix - prior_vix) / prior_vix) * 100.0
    return DampenerSignal(
        "vix_spike",
        detected=change_pct > thresholds.vix_1d_spike_pct,
        available=True,
        value=round(change_pct, 1),
    )


def detect_breadth_collapse(
    pct_above_200dma: float | None,
    thresholds: ForcedLiquidationThresholds,
) -> DampenerSignal:
    """Detect > 80% of components below 200DMA."""
    if pct_above_200dma is None:
        return DampenerSignal("breadth_collapse", detected=False, available=False)
    pct_down = 100.0 - pct_above_200dma
    return DampenerSignal(
        "breadth_collapse",
        detected=pct_down > thresholds.breadth_collapse_pct,
        available=True,
        value=round(pct_down, 1),
    )


def detect_correlation_spike(
    return_series: list[list[float]],
    thresholds: ForcedLiquidationThresholds,
) -> DampenerSignal:
    """Detect cross-asset correlation > 0.8 from a list of return series.

    Expects at least 3 return series (each a list of 5+ daily returns).
    """
    if len(return_series) < 3:
        return DampenerSignal("correlation_spike", detected=False, available=False)

    n = min(len(r) for r in return_series)
    if n < 5:
        return DampenerSignal("correlation_spike", detected=False, available=False)

    # Use the most recent 5 observations for each series.
    recent = [r[-5:] for r in return_series]
    correlations = []
    for i in range(len(recent)):
        for j in range(i + 1, len(recent)):
            corr = _pearson_correlation(recent[i], recent[j])
            if corr is not None:
                correlations.append(abs(corr))

    if not correlations:
        return DampenerSignal("correlation_spike", detected=False, available=False)

    avg_corr = sum(correlations) / len(correlations)
    return DampenerSignal(
        "correlation_spike",
        detected=avg_corr > thresholds.cross_asset_correlation_spike,
        available=True,
        value=round(avg_corr, 3),
    )


def detect_volume_spike(
    volumes: list[float],
    closes: list[float],
    thresholds: ForcedLiquidationThresholds,
) -> DampenerSignal:
    """Detect volume > 2x 20-day avg on a down day."""
    if len(volumes) < 10 or len(closes) < 2:
        return DampenerSignal("volume_spike", detected=False, available=False)
    is_down_day = closes[-1] < closes[-2]
    window = volumes[-21:-1] if len(volumes) > 20 else volumes[:-1]
    if not window:
        return DampenerSignal("volume_spike", detected=False, available=False)
    avg_volume = sum(window) / len(window)
    if avg_volume <= 0:
        return DampenerSignal("volume_spike", detected=False, available=False)
    ratio = volumes[-1] / avg_volume
    return DampenerSignal(
        "volume_spike",
        detected=(ratio > thresholds.volume_multiple_20d) and is_down_day,
        available=True,
        value=round(ratio, 2),
    )


def evaluate(
    *signals: DampenerSignal,
    thresholds: ForcedLiquidationThresholds | None = None,
) -> DampenerResult:
    """Combine 4 dampener signals into an overall decision.

    Threshold adapts to how many signals are actually available:
        - 4 available: need 3 firing
        - 2-3 available: need 2 firing
        - <2 available: never fires
    """
    thresholds = thresholds or ForcedLiquidationThresholds()
    available = sum(1 for s in signals if s.available)
    firing = sum(1 for s in signals if s.detected)

    if available >= 4:
        required = thresholds.min_signals_to_fire
    elif available >= 2:
        required = 2
    else:
        required = available + 1  # impossible to fire

    detected = firing >= required and available >= 2
    weight = thresholds.weight_adjustment_when_active if detected else 1.0
    note = (
        "Forced liquidation signatures detected — regime signals dampened "
        "to prevent mechanical over-rotation."
        if detected
        else "Normal market conditions."
    )

    return DampenerResult(
        forced_liquidation_detected=detected,
        signals_firing=firing,
        signals_available=available,
        signals=list(signals),
        dampener_active=detected,
        regime_weight_adjustment=weight,
        note=note,
    )


def _pearson_correlation(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation between two equal-length sequences."""
    n = min(len(x), len(y))
    if n < 3:
        return None
    x, y = x[:n], y[:n]
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sx = math.sqrt(sum((xi - mx) ** 2 for xi in x))
    sy = math.sqrt(sum((yi - my) ** 2 for yi in y))
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


__all__ = [
    "DampenerResult",
    "DampenerSignal",
    "detect_breadth_collapse",
    "detect_correlation_spike",
    "detect_volume_spike",
    "detect_vix_spike",
    "evaluate",
]
