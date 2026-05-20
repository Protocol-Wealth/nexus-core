# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the CoinGecko crypto market data provider.

Hermetic — every request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.market import CoinGeckoMarketData
from nexus_core.data.providers import PriceBar, Quote


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_get_quote_extracts_price() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["ids"] == "bitcoin"
        return httpx.Response(200, json={"bitcoin": {"usd": 95000.0}})

    provider = CoinGeckoMarketData(http_client=_client(handler))
    quote = provider.get_quote("bitcoin")
    assert isinstance(quote, Quote)
    assert quote.symbol == "bitcoin"
    assert quote.price == 95000.0


def test_get_quote_unknown_coin_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    provider = CoinGeckoMarketData(http_client=_client(handler))
    assert provider.get_quote("not-a-coin") is None


def test_get_quote_sends_demo_key_header() -> None:
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-cg-demo-api-key")
        return httpx.Response(200, json={"ethereum": {"usd": 3300.0}})

    provider = CoinGeckoMarketData(api_key="cg-demo", http_client=_client(handler))
    quote = provider.get_quote("ethereum")
    assert quote is not None
    assert quote.price == 3300.0
    assert seen["key"] == "cg-demo"


def test_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COINGECKO_API_KEY", raising=False)
    assert CoinGeckoMarketData(api_key="k").is_configured() is True
    assert CoinGeckoMarketData(api_key=None).is_configured() is False


def test_get_price_history_maps_ohlc_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # days=8 maps to the nearest CoinGecko-allowed value (7).
        assert request.url.params["days"] == "7"
        return httpx.Response(
            200,
            json=[
                [1735776000000, 93000.0, 94000.0, 92000.0, 93500.0],
                [1735862400000, 93500.0, 95000.0, 93000.0, 94800.0],
            ],
        )

    provider = CoinGeckoMarketData(http_client=_client(handler))
    bars = provider.get_price_history("bitcoin", days=8)
    assert len(bars) == 2
    assert all(isinstance(bar, PriceBar) for bar in bars)
    assert bars[1].close == 94800.0
    assert bars[0].volume is None


def test_http_error_degrades_gracefully() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    provider = CoinGeckoMarketData(http_client=_client(handler))
    assert provider.get_quote("bitcoin") is None
    assert provider.get_price_history("bitcoin") == []
