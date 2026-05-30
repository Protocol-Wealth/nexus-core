# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""CoinGecko-backed crypto market data provider.

Implements :class:`~nexus_core.data.providers.MarketDataProvider` against the
CoinGecko v3 API (https://www.coingecko.com/api). CoinGecko addresses coins by
**coin id** (``bitcoin``, ``ethereum``) rather than ticker symbol — pass the
coin id as the ``symbol`` argument.

CoinGecko works without a key (5-15 calls/min, unreliable). A free Demo key is
strongly recommended (~30 calls/min) — set ``COINGECKO_API_KEY`` or pass
``api_key``. ``is_configured()`` reports whether a key is present, but quote and
history calls work either way.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx

from ..http import fetch_json
from ..providers import PriceBar, Quote

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.coingecko.com/api/v3"
_DEFAULT_TIMEOUT = 10.0

#: CoinGecko's ``/coins/{id}/ohlc`` endpoint only accepts these ``days`` values.
_ALLOWED_OHLC_DAYS = (1, 7, 14, 30, 90, 180, 365)


class CoinGeckoMarketData:
    """Crypto market data provider backed by CoinGecko.

    Args:
        api_key: CoinGecko Demo API key. Falls back to ``COINGECKO_API_KEY``.
        vs_currency: Quote currency for prices (default ``usd``).
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        vs_currency: str = "usd",
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or os.environ.get("COINGECKO_API_KEY") or None
        self._vs_currency = vs_currency
        self._http_client = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        """Whether a Demo API key is available (calls work without one)."""
        return self._api_key is not None

    def get_quote(self, symbol: str) -> Quote | None:
        """Return the latest price for a coin id (e.g. ``bitcoin``)."""
        try:
            payload = fetch_json(
                f"{_BASE_URL}/simple/price",
                params={"ids": symbol, "vs_currencies": self._vs_currency},
                headers=self._headers(),
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("CoinGecko quote fetch for %s failed: %s", symbol, exc)
            return None

        coin = payload.get(symbol) if isinstance(payload, dict) else None
        price = coin.get(self._vs_currency) if isinstance(coin, dict) else None
        if price is None:
            return None
        try:
            value = float(price)
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        now = datetime.now(UTC).isoformat()
        # Crypto trades 24/7, so the live price's as_of is effectively now.
        return Quote(symbol=symbol, price=value, timestamp=now, as_of=now, source="coingecko")

    def get_price_history(
        self,
        symbol: str,
        *,
        days: int = 365,
        interval: str = "1d",
    ) -> list[PriceBar]:
        """Return OHLC bars for a coin id covering approximately ``days`` days."""
        try:
            payload = fetch_json(
                f"{_BASE_URL}/coins/{symbol}/ohlc",
                params={"vs_currency": self._vs_currency, "days": _nearest_days(days)},
                headers=self._headers(),
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("CoinGecko history fetch for %s failed: %s", symbol, exc)
            return []

        if not isinstance(payload, list):
            return []

        bars: list[PriceBar] = []
        for row in payload:
            bar = _ohlc_row_to_bar(row)
            if bar is not None:
                bars.append(bar)
        return bars

    def _headers(self) -> dict[str, str] | None:
        if self._api_key is None:
            return None
        return {"x-cg-demo-api-key": self._api_key}


def _nearest_days(days: int) -> int:
    """Map an arbitrary day count to the nearest CoinGecko-allowed value."""
    return min(_ALLOWED_OHLC_DAYS, key=lambda allowed: abs(allowed - days))


def _ohlc_row_to_bar(row: Any) -> PriceBar | None:
    """Convert a CoinGecko ``[ts_ms, open, high, low, close]`` row to a bar."""
    if not isinstance(row, list) or len(row) < 5:
        return None
    try:
        timestamp_ms = float(row[0])
        open_, high, low, close = (float(row[i]) for i in range(1, 5))
    except (TypeError, ValueError):
        return None
    timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).isoformat()
    return PriceBar(
        timestamp=timestamp,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=None,
    )


__all__ = ["CoinGeckoMarketData"]
