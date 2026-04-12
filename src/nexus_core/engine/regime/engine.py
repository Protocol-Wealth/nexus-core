# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""High-level regime engine.

``RegimeEngine`` wires the three lower-level primitives together:

    1. ``SignalFetcher`` — pulls raw signals from data providers.
    2. ``RegimeClassifier`` — pure classification from signals.
    3. Forced-liquidation ``dampener`` — optional smoothing layer.

For the simplest usage, see ``examples/basic_regime.py``:

    from nexus_core.engine.regime import RegimeEngine
    engine = RegimeEngine(market_data=my_market, macro_data=my_fred)
    result = engine.classify()
    print(result.regime, result.confidence_score)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ...data.providers import MacroDataProvider, MarketDataProvider
from .classifier import RegimeClassifier
from .hysteresis import HysteresisState, HysteresisStore, ZoneBoundary
from .signal_fetcher import SignalFetcher
from .signals import RegimeResult, RegimeSignals
from .thresholds import RegimeThresholds

logger = logging.getLogger(__name__)


class RegimeEngine:
    """Convenience orchestrator: fetch signals and classify.

    Parameters:
        market_data: Adapter implementing ``MarketDataProvider``.
        macro_data: Adapter implementing ``MacroDataProvider``.
        thresholds: Override default thresholds.
        hysteresis_store: Optional persistence for VIX hysteresis.
        cache_ttl_minutes: How long to reuse a cached signal fetch before refetching.
    """

    def __init__(
        self,
        market_data: MarketDataProvider | None = None,
        macro_data: MacroDataProvider | None = None,
        *,
        thresholds: RegimeThresholds | None = None,
        hysteresis_store: HysteresisStore | None = None,
        cache_ttl_minutes: int = 15,
    ) -> None:
        self.thresholds = thresholds or RegimeThresholds()
        self.fetcher = SignalFetcher(market_data=market_data, macro_data=macro_data)
        self.vix_state = HysteresisState(
            default_zone="normal",
            zones=[
                ZoneBoundary(
                    "elevated",
                    enter=self.thresholds.vix_elevated_enter,
                    exit=self.thresholds.vix_elevated_exit,
                ),
                ZoneBoundary(
                    "crisis",
                    enter=self.thresholds.vix_crisis_enter,
                    exit=self.thresholds.vix_crisis_exit,
                ),
            ],
            store=hysteresis_store,
        )
        self.classifier = RegimeClassifier(thresholds=self.thresholds, vix_state=self.vix_state)

        self._cache_ttl_minutes = cache_ttl_minutes
        self._cached_signals: RegimeSignals | None = None
        self._cache_timestamp: datetime | None = None
        self._current_regime: str | None = None
        self._regime_start: datetime | None = None

    # ---------------------------------------------------------------- public

    def fetch_signals(self, *, force_refresh: bool = False) -> RegimeSignals:
        """Fetch fresh signals or return cached if within TTL."""
        if (
            not force_refresh
            and self._cached_signals is not None
            and self._cache_timestamp is not None
        ):
            age_min = (datetime.now(UTC) - self._cache_timestamp).total_seconds() / 60
            if age_min < self._cache_ttl_minutes:
                return self._cached_signals

        signals = self.fetcher.fetch()
        self._cached_signals = signals
        self._cache_timestamp = datetime.now(UTC)
        return signals

    def classify(
        self,
        signals: RegimeSignals | None = None,
        *,
        prediction_market: dict[str, float | str] | None = None,
    ) -> RegimeResult:
        """Classify the current regime. Falls back to fetching signals if none passed."""
        if signals is None:
            signals = self.fetch_signals()

        now = datetime.now(UTC)
        days_in_regime = (now - self._regime_start).days if self._regime_start else 0

        result = self.classifier.classify(
            signals,
            prior_regime=self._current_regime,
            days_in_regime=days_in_regime,
            prediction_market=prediction_market,
        )

        # Track regime transitions.
        if result.regime != self._current_regime:
            logger.info(
                "Regime transition: %s → %s (confidence=%s%%)",
                self._current_regime or "INIT",
                result.regime,
                result.confidence_score,
            )
            self._current_regime = result.regime
            self._regime_start = now

        return result

    # --------------------------------------------------------------- accessors

    @property
    def current_regime(self) -> str | None:
        """Most-recently-classified regime, or None if ``classify()`` not called."""
        return self._current_regime

    @property
    def regime_start(self) -> datetime | None:
        """When the current regime was first classified."""
        return self._regime_start


__all__ = ["RegimeEngine"]
