# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Regime classification thresholds — Protocol Wealth's published calibration.

These defaults are the calibrated values Protocol Wealth runs in production and
publishes openly as part of the EMF framework (https://protocolwealthllc.com/framework,
/investing, /thesis, /how-we-work) — **not** arbitrary placeholders. They were fit by
backtesting labeled regime periods (2008-09 DEFLATION, 1968-80 HARD_ASSET,
2011-2024 GROWTH, 2020-22 TRANSITION, 1942-65 REPRESSION).

.. note::

    The values reflect PW's specific signal construction (FRED real rates,
    BBB OAS credit spreads via BAMLC0A4CBBB, ZB=F 30Y bond futures, DXY via
    DTWEXBGS). Adopters whose signal sources or asset universe differ should
    re-fit. **All outputs are for educational and research purposes only — not
    individualized investment advice.**

Re-fit workflow (for adopters with different signals):
    1. Fetch 10+ years of historical signals.
    2. Label known regime periods (e.g. 2008-09 = DEFLATION, 1968-80 = HARD_ASSET).
    3. Fit thresholds that would have classified those periods correctly.
    4. Validate with rolling walk-forward testing.
    5. Revisit at least annually, or when signal construction changes.

Hysteresis dead-zones (VIX elevated/crisis enter/exit) prevent regime flapping
on daily noise. The width of the dead zone controls responsiveness vs. stability.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegimeThresholds:
    """Threshold cutoffs for classifying raw signal values into regimes.

    Immutable by design — callers that need different thresholds should build
    a new instance rather than mutating a shared one. Thread-safe.

    The defaults are Protocol Wealth's published calibration (see the module
    docstring). Adopters with different signal construction override by
    constructing a new instance with their own re-fit values.
    """

    # Gold/SPX Ratio — relative strength of hard money vs. equities.
    # Long-run range ~0.3 to ~1.5; the bucketing here is a simple three-way
    # split and will need asset-universe-specific tuning.
    gold_spx_growth_max: float = 0.50
    gold_spx_transition_max: float = 0.70
    gold_spx_hard_asset_min: float = 0.70

    # Real rates (10Y TIPS yield or 10Y nominal - breakeven inflation).
    real_rates_risk_on: float = 1.5
    real_rates_neutral_min: float = 0.0
    real_rates_risk_off: float = 0.0
    real_rates_repression: float = -1.0

    # DXY (trade-weighted dollar index, ~100 = neutral).
    dxy_strong: float = 105.0
    dxy_weak: float = 95.0

    # VIX — bare labels (used only for informational status, not flipping).
    vix_complacent: float = 15.0
    vix_elevated: float = 25.0
    vix_crisis: float = 35.0

    # VIX hysteresis — must cross ENTER to flip up, drop below EXIT to flip back.
    # PW-calibrated dead zones (3-point gap), tuned for a tolerable regime-flip
    # rate against daily VIX noise.
    vix_elevated_enter: float = 26.0
    vix_elevated_exit: float = 23.0
    vix_crisis_enter: float = 36.0
    vix_crisis_exit: float = 33.0

    # Credit spreads (bps) — PW-calibrated against BBB OAS (FRED BAMLC0A4CBBB).
    # Adopters using HY, CDX IG/HY, or another credit series should re-fit.
    spreads_tight: float = 80.0
    spreads_normal_max: float = 150.0
    spreads_wide_max: float = 250.0

    # 30-Year Treasury bond futures (ZB=F) — proxy for long duration & PM direction.
    # PW-calibrated PM-direction brackets; re-fit as the rate environment shifts.
    bond_futures_bullish_pm: float = 113.0
    bond_futures_neutral: float = 118.0
    bond_futures_bearish_pm: float = 125.0

    # Yield curve slope (10Y - 2Y, percentage points).
    yield_curve_normal_min: float = 0.5

    # How long a regime must persist before treating the transition as confirmed.
    regime_confirmation_weeks: int = 12


@dataclass(frozen=True)
class ForcedLiquidationThresholds:
    """Thresholds for the forced-liquidation dampener.

    When a majority of these signals fire, the regime classifier will dampen
    its response — preventing mechanical over-rotation into HARD_ASSET or
    DEFLATION during what may be a short, technical deleveraging event.

    Illustrative defaults — calibrate against historical forced-liquidation
    episodes (Aug 2015, Feb 2018, Mar 2020, Aug 2024) in your own data.
    """

    vix_1d_spike_pct: float = 30.0
    """A single-day VIX move this large is unusual even in stress."""

    breadth_collapse_pct: float = 80.0
    """% of index components trading below 200DMA."""

    cross_asset_correlation_spike: float = 0.80
    """Avg pairwise correlation across diversified assets."""

    volume_multiple_20d: float = 2.0
    """Today's volume vs. 20-day average on a down day."""

    min_signals_to_fire: int = 3
    """Of 4 signals, how many must fire to dampen. Falls to 2 if fewer signals available."""

    weight_adjustment_when_active: float = 0.5
    """Regime signal weight scalar (0 = freeze, 1 = no dampening)."""


@dataclass(frozen=True)
class ThresholdBundle:
    """Convenience bundle carrying all threshold families used by the engine."""

    regime: RegimeThresholds = field(default_factory=RegimeThresholds)
    forced_liquidation: ForcedLiquidationThresholds = field(
        default_factory=ForcedLiquidationThresholds
    )


__all__ = [
    "ForcedLiquidationThresholds",
    "RegimeThresholds",
    "ThresholdBundle",
]
