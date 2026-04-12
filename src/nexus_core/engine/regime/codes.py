# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Regime codes and client-type enums.

The regime taxonomy — five macro regimes covering the full range of monetary,
inflationary, and liquidity conditions — is drawn from the durable regime
literature (Dalio's economic machine, Hamilton 1989, Bridgewater All Weather)
and defined in concrete terms so users can match their own signal thresholds.

The codes themselves are a contract: downstream consumers (allocation matrices,
scoring systems, MCP tools) key off these values. Extend via a separate enum
rather than mutating this one.
"""

from __future__ import annotations

from enum import Enum


class RegimeCode(str, Enum):
    """Macroeconomic regime classification.

    Inherits from ``str`` so JSON serialization and ``==`` comparisons with
    string literals work without ``.value``.
    """

    GROWTH = "GROWTH"
    """Low inflation, rising productivity, risk-on sentiment, strong dollar,
    positive real rates. Favors equity-heavy allocations with growth tilt."""

    TRANSITION = "TRANSITION"
    """Mixed signals, elevated uncertainty, potential regime shift forming.
    Correlation breakdowns increasing. Gradual rebalancing warranted."""

    HARD_ASSET = "HARD_ASSET"
    """Inflation or stagflation, currency debasement, risk-off sentiment,
    weak dollar. Favors hard assets and foundational layers."""

    DEFLATION = "DEFLATION"
    """Credit contraction, falling prices, liquidity crisis, flight to cash.
    Everything correlates initially. Favors cash and short-term bonds."""

    REPRESSION = "REPRESSION"
    """Deeply negative real rates, yield curve control, debt monetization.
    Nominal gains mask real losses. Favors real assets and TIPS."""


class ClientType(str, Enum):
    """Lifecycle classification for allocation matrices.

    Accumulation phase = longer time horizon, higher risk budget.
    Distribution phase = preservation of purchasing power, income focus.
    """

    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"


class SignalDirection(str, Enum):
    """Standard status values for signal classification."""

    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    CRISIS = "crisis"
    CONTRARIAN = "contrarian"


__all__ = ["ClientType", "RegimeCode", "SignalDirection"]
