# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Regime Detection Engine.

Multi-signal regime classification using gold/SPX ratio, real rates, DXY,
VIX (with hysteresis), credit spreads, bond futures, and optional prediction
market consensus. See USPTO #64/034,229 for the defensive patent filing.

Quick start:

    from nexus_core.engine.regime import RegimeEngine

    engine = RegimeEngine(
        market_data=my_market_adapter,
        macro_data=my_fred_adapter,
    )
    result = engine.classify()
    print(result.regime, result.confidence_score, result.rationale)

The ``RegimeClassifier`` is a pure function of ``RegimeSignals`` + thresholds
— use it directly if you prefer to own signal fetching. ``RegimeThresholds``
carries example defaults that should be calibrated to your data sources and
risk preferences.
"""

from __future__ import annotations

from .classifier import RegimeClassifier
from .codes import ClientType, RegimeCode, SignalDirection
from .dampener import (
    DampenerResult,
    DampenerSignal,
    detect_breadth_collapse,
    detect_correlation_spike,
    detect_vix_spike,
    detect_volume_spike,
)
from .dampener import (
    evaluate as evaluate_dampener,
)
from .engine import RegimeEngine
from .hysteresis import HysteresisState, HysteresisStore, ZoneBoundary
from .signal_fetcher import SignalFetcher
from .signals import RegimeResult, RegimeSignals, SignalStatus
from .thresholds import ForcedLiquidationThresholds, RegimeThresholds, ThresholdBundle

__all__ = [
    # Codes & enums
    "ClientType",
    "RegimeCode",
    "SignalDirection",
    # Thresholds
    "ForcedLiquidationThresholds",
    "RegimeThresholds",
    "ThresholdBundle",
    # Signals & results
    "RegimeResult",
    "RegimeSignals",
    "SignalStatus",
    # Hysteresis
    "HysteresisState",
    "HysteresisStore",
    "ZoneBoundary",
    # Classifier / engine
    "RegimeClassifier",
    "RegimeEngine",
    "SignalFetcher",
    # Dampener
    "DampenerResult",
    "DampenerSignal",
    "detect_breadth_collapse",
    "detect_correlation_spike",
    "detect_vix_spike",
    "detect_volume_spike",
    "evaluate_dampener",
]
