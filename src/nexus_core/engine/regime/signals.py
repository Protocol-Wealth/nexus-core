# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Signal dataclasses for regime classification.

These types are the contract between data-fetching code and the classifier.
They are intentionally plain dataclasses (not Pydantic) so consumers can
subclass them freely without pulling in Pydantic's validation costs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class SignalStatus:
    """Classification of a single signal against configured thresholds.

    Attributes:
        name: Human-readable name (e.g. "Gold/SPX Ratio", "VIX").
        current_value: Numeric signal value.
        threshold_info: Brief description of cutoffs used (for explainability).
        status: One of ``SignalDirection`` values as a string.
        supports_regime: Which ``RegimeCode`` this signal's current reading supports.
    """

    name: str
    current_value: float
    threshold_info: str
    status: str
    supports_regime: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "current_value": self.current_value,
            "threshold_info": self.threshold_info,
            "status": self.status,
            "supports_regime": self.supports_regime,
        }


@dataclass
class RegimeSignals:
    """Raw signal readings used for regime detection.

    Required fields drive classification. Optional fields enrich the output
    but don't change the classification decision when absent.

    Build this from whatever data sources you prefer (FRED, Bloomberg, your
    own caches). The classifier takes this as input and does not know where
    the data came from.
    """

    gold_spx_ratio: float
    gold_spx_200wma: float
    gold_spx_vs_wma: str  # "above", "below", "testing"
    real_rates: float
    dxy: float
    vix: float
    credit_spreads: float  # bps, typically BBB OAS

    # Optional / supplementary signals
    hy_credit_spreads: float | None = None
    breadth: float | None = None  # % above 200DMA
    bond_futures_30y: float | None = None
    precious_metals_signal: str | None = None  # "bullish", "neutral", "bearish"
    yield_curve_2s10s: float | None = None
    yield_curve_status: str | None = None  # "normal", "flattening", "inverted"

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "gold_spx_ratio": self.gold_spx_ratio,
            "gold_spx_200wma": self.gold_spx_200wma,
            "gold_spx_vs_wma": self.gold_spx_vs_wma,
            "real_rates": self.real_rates,
            "dxy": self.dxy,
            "vix": self.vix,
            "credit_spreads": self.credit_spreads,
            "hy_credit_spreads": self.hy_credit_spreads,
            "breadth": self.breadth,
            "bond_futures_30y": self.bond_futures_30y,
            "precious_metals_signal": self.precious_metals_signal,
            "yield_curve_2s10s": self.yield_curve_2s10s,
            "yield_curve_status": self.yield_curve_status,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class RegimeResult:
    """Full output of regime classification.

    Attributes:
        regime: Classified regime code.
        confidence_score: 0-100, based on how many signals agree.
        days_in_regime: How long the current regime has been active.
        signals: The raw signals used (for reproducibility).
        signal_statuses: Per-signal classification (for explainability).
        rationale: Short natural-language explanation.
        dynamic_200wma: Optional trend-adjusted 200WMA context.
        forced_liquidation_dampener: Dampener state (if active).
    """

    regime: str  # RegimeCode value
    confidence_score: int
    days_in_regime: int
    signals: RegimeSignals
    signal_statuses: list[SignalStatus]
    rationale: str
    dynamic_200wma: dict[str, Any] | None = None
    forced_liquidation_dampener: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "regime": self.regime,
            "confidence_score": self.confidence_score,
            "days_in_regime": self.days_in_regime,
            "signals": self.signals.to_dict(),
            "signal_statuses": [s.to_dict() for s in self.signal_statuses],
            "rationale": self.rationale,
        }
        if self.dynamic_200wma is not None:
            result["dynamic_200wma"] = self.dynamic_200wma
        if self.forced_liquidation_dampener is not None:
            result["forced_liquidation_dampener"] = self.forced_liquidation_dampener
        return result


__all__ = ["RegimeResult", "RegimeSignals", "SignalStatus"]
