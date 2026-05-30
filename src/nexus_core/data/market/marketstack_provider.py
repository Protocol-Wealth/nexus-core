# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""MarketStack-backed market data provider.

Implements :class:`~nexus_core.data.providers.MarketDataProvider` against the
MarketStack v2 API (https://docs.apilayer.com/marketstack). MarketStack serves
end-of-day OHLCV for stocks, ETFs, and indices across global exchanges.

Requires an API key — set ``MARKETSTACK_API_KEY`` or pass ``api_key``.
``get_quote`` and ``get_price_history`` return ``None`` / ``[]`` when no key is
configured.

This provider serves **end-of-day** data only; the ``interval`` argument is
accepted for protocol compatibility but ignored (every bar is a daily bar).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..http import fetch_json
from ..providers import PriceBar, Quote

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.marketstack.com/v2"
_DEFAULT_TIMEOUT = 10.0


class MarketStackMarketData:
    """Market data provider backed by the MarketStack v2 EOD API.

    Args:
        api_key: MarketStack access key. Falls back to ``MARKETSTACK_API_KEY``.
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or os.environ.get("MARKETSTACK_API_KEY") or None
        self._http_client = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        """Whether an API key is available."""
        return self._api_key is not None

    def get_quote(self, symbol: str) -> Quote | None:
        """Return the latest end-of-day quote for ``symbol``."""
        if self._api_key is None:
            return None
        try:
            payload = fetch_json(
                f"{_BASE_URL}/eod/latest",
                params={"symbols": symbol, "access_key": self._api_key},
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("MarketStack quote fetch for %s failed: %s", symbol, exc)
            return None

        record = _first_record(payload)
        if record is None:
            return None
        close = _as_float(record.get("close"))
        if close is None or close <= 0:
            return None
        as_of = record.get("date")  # MarketStack EOD: the data point's session date
        return Quote(
            symbol=symbol, price=close, timestamp=as_of, as_of=as_of, source="marketstack"
        )

    def get_price_history(
        self,
        symbol: str,
        *,
        days: int = 365,
        interval: str = "1d",
    ) -> list[PriceBar]:
        """Return daily OHLCV bars covering approximately ``days`` days."""
        if self._api_key is None:
            return []
        try:
            payload = fetch_json(
                f"{_BASE_URL}/eod",
                params={
                    "symbols": symbol,
                    "access_key": self._api_key,
                    "limit": min(max(days, 1), 1000),
                },
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("MarketStack history fetch for %s failed: %s", symbol, exc)
            return []

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []

        bars: list[PriceBar] = []
        for record in data:
            bar = _record_to_bar(record)
            if bar is not None:
                bars.append(bar)
        return bars


def _first_record(payload: Any) -> dict[str, Any] | None:
    """Pull the first record from a MarketStack ``{"data": [...]}`` envelope."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else None
    if isinstance(data, dict):
        return data
    return None


def _record_to_bar(record: Any) -> PriceBar | None:
    """Convert a single MarketStack EOD record into a :class:`PriceBar`."""
    if not isinstance(record, dict):
        return None
    close = _as_float(record.get("close"))
    if close is None:
        return None
    return PriceBar(
        timestamp=str(record.get("date") or ""),
        open=_as_float(record.get("open")) or close,
        high=_as_float(record.get("high")) or close,
        low=_as_float(record.get("low")) or close,
        close=close,
        volume=_as_float(record.get("volume")),
    )


def _as_float(value: Any) -> float | None:
    """Coerce a JSON value to ``float``, or ``None`` if it is not numeric."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


__all__ = ["MarketStackMarketData"]
