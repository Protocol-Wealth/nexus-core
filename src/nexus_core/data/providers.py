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
from datetime import UTC, datetime
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


def market_status_from(as_of: str | None) -> str | None:
    """Coarse data-freshness label derived from an ISO ``as_of`` date/datetime.

    Returns ``"current"`` if the data point is from today (UTC) or later,
    ``"last_close"`` if from a prior date, and ``None`` if unknown. This is a
    *freshness* indicator (so a Saturday quote of Friday's close reads as
    ``last_close``, not a live price) — it is NOT an exchange-open/closed claim
    and applies no market-calendar or holiday logic.
    """
    if not as_of or len(as_of) < 10:
        return None
    day = as_of[:10]  # YYYY-MM-DD prefix of an ISO date or datetime
    if day[4] != "-" or day[7] != "-":
        return None
    return "current" if day >= datetime.now(UTC).strftime("%Y-%m-%d") else "last_close"


@dataclass
class Quote:
    """Real-time or end-of-day quote.

    ``timestamp`` is when the quote was *fetched*; ``as_of`` is the date/time of
    the *data point* itself (they differ for an end-of-day close pulled
    intraday, or any close pulled after hours / on a weekend). ``source`` names
    the provider that answered, and ``market_status`` is a coarse freshness
    label derived from ``as_of`` (see :func:`market_status_from`).
    """

    symbol: str
    price: float
    timestamp: str | None = None
    as_of: str | None = None
    source: str | None = None
    market_status: str | None = None


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

    def get_series_observation(self, series_id: str) -> tuple[float, str] | None:
        """Latest ``(value, observation_date)`` for a series, or None.

        Carries the data point's own date so callers can surface provenance
        (``as_of``) instead of the fetch time.
        """
        ...

    def is_configured(self) -> bool:
        """Whether this provider has credentials to serve requests."""
        ...


__all__ = ["MacroDataProvider", "MarketDataProvider", "PriceBar", "Quote"]
