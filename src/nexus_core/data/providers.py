# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Data provider protocols.

Abstract interfaces the rest of nexus-core programs against. Concrete
implementations — for FRED, FMP, MBOUM, yfinance, Polygon, or your own
internal data service — adapt to these protocols.

No production calls belong in this file. Keep provider adapters next to the
engine they serve (``data/market/``, ``data/edgar/``, ``data/onchain/``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class PriceBar:
    """One OHLCV bar."""

    timestamp: str  # ISO-8601
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


@dataclass
class Quote:
    """Real-time or end-of-day quote."""

    symbol: str
    price: float
    timestamp: str | None = None


@runtime_checkable
class MarketDataProvider(Protocol):
    """Minimum interface needed for regime detection + scoring."""

    def get_quote(self, symbol: str) -> Quote | None:
        """Return current quote for a symbol, or None if unavailable."""
        ...

    def get_price_history(
        self,
        symbol: str,
        *,
        days: int = 365,
        interval: str = "1d",
    ) -> list[PriceBar]:
        """Return OHLCV bars covering approximately ``days`` days."""
        ...


@runtime_checkable
class MacroDataProvider(Protocol):
    """FRED-style series lookups used for macro signals (rates, DXY, etc.)."""

    def get_series(self, series_id: str) -> float | None:
        """Latest value for a series, or None if unavailable."""
        ...

    def is_configured(self) -> bool:
        """Whether this provider has credentials to serve requests."""
        ...


__all__ = ["MacroDataProvider", "MarketDataProvider", "PriceBar", "Quote"]
