# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""yfinance-backed market data provider.

Implements the :class:`~nexus_core.data.providers.MarketDataProvider` protocol
against Yahoo Finance via the ``yfinance`` library. Keyless — no API
credentials required — which makes it the natural default for the public
nexus-core deployment.

Install with::

    pip install nexus-core[market]

yfinance scrapes a public, undocumented Yahoo endpoint; treat it as
best-effort. Every method returns ``None`` / an empty list rather than raising
on provider failure, so the regime engine's neutral-fallback path stays intact.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from ..providers import PriceBar, Quote

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - optional dependency
    yf = None

logger = logging.getLogger(__name__)


class YFinanceMarketData:
    """Market data provider backed by Yahoo Finance.

    Args:
        ticker_factory: Callable mapping a symbol string to an object exposing
            ``fast_info`` and ``history(...)`` — the ``yfinance.Ticker`` shape.
            Defaults to ``yfinance.Ticker``. Inject a fake for hermetic tests.
    """

    def __init__(self, *, ticker_factory: Callable[[str], Any] | None = None) -> None:
        if ticker_factory is None:
            if yf is None:
                raise ImportError(
                    "yfinance is required. Install with: pip install nexus-core[market]"
                )
            ticker_factory = yf.Ticker
        self._ticker_factory = ticker_factory

    def get_quote(self, symbol: str) -> Quote | None:
        """Return the latest quote for ``symbol``, or ``None`` if unavailable."""
        try:
            ticker = self._ticker_factory(symbol)
            price = _price_from_fast_info(getattr(ticker, "fast_info", None))
            if price is None:
                price = _price_from_recent_close(ticker)
            if price is None or price <= 0:
                return None
            return Quote(symbol=symbol, price=price, timestamp=datetime.now(UTC).isoformat())
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("yfinance quote fetch for %s failed: %s", symbol, exc)
            return None

    def get_price_history(
        self,
        symbol: str,
        *,
        days: int = 365,
        interval: str = "1d",
    ) -> list[PriceBar]:
        """Return OHLCV bars covering approximately ``days`` days."""
        try:
            ticker = self._ticker_factory(symbol)
            end = datetime.now(UTC)
            start = end - timedelta(days=days)
            frame = ticker.history(
                start=start.date().isoformat(),
                end=end.date().isoformat(),
                interval=interval,
            )
            return _frame_to_bars(frame)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("yfinance history fetch for %s failed: %s", symbol, exc)
            return []


def _price_from_fast_info(fast: Any) -> float | None:
    """Extract a last price from a ``yfinance`` ``fast_info`` object."""
    if fast is None:
        return None
    for key in ("last_price", "lastPrice"):
        value: Any = None
        try:
            value = fast[key]
        except (KeyError, TypeError, IndexError):
            value = getattr(fast, key, None)
        if value:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _price_from_recent_close(ticker: Any) -> float | None:
    """Fall back to the most recent close from a one-day history fetch."""
    frame = ticker.history(period="1d")
    if frame is None or getattr(frame, "empty", True):
        return None
    try:
        return float(frame["Close"].iloc[-1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _frame_to_bars(frame: Any) -> list[PriceBar]:
    """Convert a pandas OHLCV DataFrame into a list of :class:`PriceBar`."""
    if frame is None or getattr(frame, "empty", True):
        return []
    bars: list[PriceBar] = []
    for index, row in frame.iterrows():
        timestamp = index.isoformat() if hasattr(index, "isoformat") else str(index)
        volume_raw = row.get("Volume")
        volume: float | None = None
        if volume_raw is not None:
            coerced = float(volume_raw)
            if not math.isnan(coerced):
                volume = coerced
        bars.append(
            PriceBar(
                timestamp=timestamp,
                open=float(row["Open"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                close=float(row["Close"]),
                volume=volume,
            )
        )
    return bars


__all__ = ["YFinanceMarketData"]
