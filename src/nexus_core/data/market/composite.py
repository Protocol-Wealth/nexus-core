# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Composite market data provider with ordered fallback.

Wraps an ordered list of :class:`~nexus_core.data.providers.MarketDataProvider`
implementations and returns the first usable result. This lets a deployment
prefer a keyless source (yfinance) and fall back to keyed sources (MBOUM,
MarketStack, CoinGecko) — or vice versa — without the regime engine or the API
layer knowing which source answered.

A provider that raises is treated as a miss; the next provider is tried.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Sequence

from ..providers import MarketDataProvider, PriceBar, Quote, market_status_from

logger = logging.getLogger(__name__)


class CompositeMarketData:
    """Try each wrapped provider in order; return the first usable result.

    Args:
        providers: Providers in priority order. The first to return a usable
            value wins.
    """

    def __init__(self, providers: Sequence[MarketDataProvider]) -> None:
        self._providers = list(providers)

    def get_quote(self, symbol: str) -> Quote | None:
        """Return the first non-``None`` quote across the wrapped providers."""
        for provider in self._providers:
            try:
                quote = provider.get_quote(symbol)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("composite: %s.get_quote failed: %s", type(provider).__name__, exc)
                continue
            if quote is not None:
                # Derive the coarse freshness label from as_of once, centrally,
                # so every provider's quotes carry it consistently.
                if quote.market_status is None:
                    return dataclasses.replace(
                        quote, market_status=market_status_from(quote.as_of)
                    )
                return quote
        return None

    def get_price_history(
        self,
        symbol: str,
        *,
        days: int = 365,
        interval: str = "1d",
    ) -> list[PriceBar]:
        """Return the first non-empty price history across the wrapped providers."""
        for provider in self._providers:
            try:
                bars = provider.get_price_history(symbol, days=days, interval=interval)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug(
                    "composite: %s.get_price_history failed: %s", type(provider).__name__, exc
                )
                continue
            if bars:
                return bars
        return []


__all__ = ["CompositeMarketData"]
