# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the MarketStack market data provider.

Hermetic — every request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.market import MarketStackMarketData
from nexus_core.data.providers import PriceBar, Quote


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_not_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MARKETSTACK_API_KEY", raising=False)
    provider = MarketStackMarketData(api_key=None)
    assert provider.is_configured() is False
    assert provider.get_quote("AAPL") is None
    assert provider.get_price_history("AAPL") == []


def test_get_quote_extracts_close() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["access_key"] == "ms-key"
        assert request.url.params["symbols"] == "AAPL"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"symbol": "AAPL", "close": 230.1, "date": "2026-01-05T00:00:00+0000"}
                ]
            },
        )

    provider = MarketStackMarketData(api_key="ms-key", http_client=_client(handler))
    quote = provider.get_quote("AAPL")
    assert isinstance(quote, Quote)
    assert quote.price == 230.1
    assert quote.timestamp == "2026-01-05T00:00:00+0000"


def test_get_quote_empty_data_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    provider = MarketStackMarketData(api_key="k", http_client=_client(handler))
    assert provider.get_quote("AAPL") is None


def test_get_price_history_maps_records() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"date": "2026-01-05", "open": 1.0, "high": 2.0, "low": 0.5,
                     "close": 1.5, "volume": 10.0},
                    {"date": "2026-01-04", "open": 0.9, "high": 1.5, "low": 0.8,
                     "close": 1.0, "volume": 20.0},
                ]
            },
        )

    provider = MarketStackMarketData(api_key="k", http_client=_client(handler))
    bars = provider.get_price_history("AAPL", days=10)
    assert len(bars) == 2
    assert all(isinstance(bar, PriceBar) for bar in bars)
    assert bars[0].close == 1.5


def test_http_error_degrades_gracefully() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"error": "bad request"})

    provider = MarketStackMarketData(api_key="k", http_client=_client(handler))
    assert provider.get_quote("AAPL") is None
    assert provider.get_price_history("AAPL") == []
