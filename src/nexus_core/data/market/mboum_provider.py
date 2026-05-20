# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""MBOUM-backed market data provider.

Implements :class:`~nexus_core.data.providers.MarketDataProvider` against the
MBOUM Financial Data API (https://docs.mboum.com). MBOUM proxies Yahoo Finance
data and accepts Yahoo-style symbols (``AAPL``, ``SPY``, ``^VIX``, ``GC=F``,
``BTC-USD``), which makes it a drop-in fallback for the keyless yfinance
provider.

Requires an API key — set ``MBOUM_API_KEY`` or pass ``api_key``. ``get_quote``
and ``get_price_history`` return ``None`` / ``[]`` when no key is configured.

.. note::

    The quote field names and the history record shape below are inferred from
    MBOUM's Yahoo-proxy envelope (documented ``{"meta": ..., "body": ...}``).
    The extractors are deliberately permissive (multiple candidate field names,
    ``{"raw": ...}`` unwrapping). Confirm against a live key during validation.
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

_BASE_URL = "https://api.mboum.com"
_DEFAULT_TIMEOUT = 30.0


class MboumMarketData:
    """Market data provider backed by the MBOUM API.

    Args:
        api_key: MBOUM bearer token. Falls back to the ``MBOUM_API_KEY`` env var.
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds (MBOUM recommends >= 30s).
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or os.environ.get("MBOUM_API_KEY") or None
        self._http_client = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        """Whether an API key is available."""
        return self._api_key is not None

    def get_quote(self, symbol: str) -> Quote | None:
        """Return the latest quote for ``symbol``, or ``None`` if unavailable."""
        if self._api_key is None:
            return None
        try:
            payload = fetch_json(
                f"{_BASE_URL}/v1/markets/stock/quotes",
                params={"ticker": symbol},
                headers={"Authorization": f"Bearer {self._api_key}"},
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("MBOUM quote fetch for %s failed: %s", symbol, exc)
            return None

        record = _first_record(payload)
        if record is None:
            return None
        price = _extract_number(
            record,
            ("regularMarketPrice", "price", "last", "regularMarketPreviousClose"),
        )
        if price is None or price <= 0:
            return None
        return Quote(symbol=symbol, price=price, timestamp=datetime.now(UTC).isoformat())

    def get_price_history(
        self,
        symbol: str,
        *,
        days: int = 365,
        interval: str = "1d",
    ) -> list[PriceBar]:
        """Return OHLCV bars covering approximately ``days`` days."""
        if self._api_key is None:
            return []
        try:
            payload = fetch_json(
                f"{_BASE_URL}/v2/markets/stock/history",
                params={
                    "ticker": symbol,
                    "interval": interval,
                    "limit": min(max(days, 1), 1000),
                },
                headers={"Authorization": f"Bearer {self._api_key}"},
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("MBOUM history fetch for %s failed: %s", symbol, exc)
            return []

        body = payload.get("body") if isinstance(payload, dict) else None
        if isinstance(body, dict):
            records: list[Any] = [
                {**value, "_key": key} if isinstance(value, dict) else value
                for key, value in body.items()
            ]
        elif isinstance(body, list):
            records = body
        else:
            return []

        bars: list[PriceBar] = []
        for record in records:
            bar = _record_to_bar(record)
            if bar is not None:
                bars.append(bar)
        return bars


def _first_record(payload: Any) -> dict[str, Any] | None:
    """Pull the first quote record out of an MBOUM ``{"body": ...}`` envelope."""
    body = payload.get("body") if isinstance(payload, dict) else None
    if isinstance(body, list):
        return body[0] if body and isinstance(body[0], dict) else None
    if isinstance(body, dict):
        return body
    return None


def _record_to_bar(record: Any) -> PriceBar | None:
    """Convert a single OHLCV record into a :class:`PriceBar`."""
    if not isinstance(record, dict):
        return None
    close = _extract_number(record, ("close", "Close"))
    if close is None:
        return None
    open_ = _extract_number(record, ("open", "Open")) or close
    high = _extract_number(record, ("high", "High")) or close
    low = _extract_number(record, ("low", "Low")) or close
    volume = _extract_number(record, ("volume", "Volume"))
    timestamp = record.get("date") or record.get("date_utc") or record.get("_key") or ""
    return PriceBar(
        timestamp=str(timestamp),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def _extract_number(record: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    """Extract a numeric value, unwrapping MBOUM ``{"raw": ...}`` field objects."""
    for key in keys:
        if key not in record:
            continue
        value: Any = record[key]
        if isinstance(value, dict):
            value = value.get("raw")
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


__all__ = ["MboumMarketData"]
