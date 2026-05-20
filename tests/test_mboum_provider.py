# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the MBOUM market data provider.

Hermetic — every request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.market import MboumMarketData
from nexus_core.data.providers import PriceBar, Quote


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_not_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MBOUM_API_KEY", raising=False)
    provider = MboumMarketData(api_key=None)
    assert provider.is_configured() is False
    assert provider.get_quote("AAPL") is None
    assert provider.get_price_history("AAPL") == []


def test_get_quote_extracts_price() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.url.params["ticker"] == "AAPL"
        return httpx.Response(
            200, json={"meta": {"status": 200}, "body": [{"regularMarketPrice": 231.4}]}
        )

    provider = MboumMarketData(api_key="test-key", http_client=_client(handler))
    quote = provider.get_quote("AAPL")
    assert isinstance(quote, Quote)
    assert quote.price == 231.4


def test_get_quote_unwraps_raw_field() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"body": [{"regularMarketPrice": {"raw": 99.5, "fmt": "99.50"}}]}
        )

    provider = MboumMarketData(api_key="k", http_client=_client(handler))
    quote = provider.get_quote("AAPL")
    assert quote is not None
    assert quote.price == 99.5


def test_get_quote_http_error_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = MboumMarketData(api_key="k", http_client=_client(handler))
    assert provider.get_quote("AAPL") is None


def test_get_price_history_list_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "body": [
                    {"date": "2026-01-02", "open": 1.0, "high": 2.0, "low": 0.5,
                     "close": 1.5, "volume": 100.0},
                    {"date": "2026-01-03", "open": 1.5, "high": 2.5, "low": 1.0,
                     "close": 2.0, "volume": 200.0},
                ]
            },
        )

    provider = MboumMarketData(api_key="k", http_client=_client(handler))
    bars = provider.get_price_history("AAPL", days=5)
    assert len(bars) == 2
    assert all(isinstance(bar, PriceBar) for bar in bars)
    assert bars[1].close == 2.0


def test_get_price_history_dict_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"body": {"2026-01-02": {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5}}},
        )

    provider = MboumMarketData(api_key="k", http_client=_client(handler))
    bars = provider.get_price_history("AAPL")
    assert len(bars) == 1
    assert bars[0].close == 1.5
    assert bars[0].timestamp == "2026-01-02"
