# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the keyless DefiLlama coins price client (hermetic, MockTransport)."""

from __future__ import annotations

from collections.abc import Callable

import httpx

from nexus_core.data.onchain.defillama_prices import DefiLlamaPriceClient


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> DefiLlamaPriceClient:
    return DefiLlamaPriceClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_historical_prices_parses_coins_and_builds_path() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["search_width"] = request.url.params.get("searchWidth", "")
        return httpx.Response(
            200,
            json={
                "coins": {
                    "ethereum:0xA0b8": {
                        "price": 1.0009,
                        "timestamp": 1_700_000_000,
                        "symbol": "USDC",
                        "decimals": 6,
                        "confidence": 0.99,
                    },
                    "solana:So111": {"price": 145.5, "timestamp": 1_700_000_123, "symbol": "SOL"},
                }
            },
        )

    out = _client(handler).historical_prices(["ethereum:0xA0b8", "solana:So111"], 1_700_000_000)

    assert set(out) == {"ethereum:0xA0b8", "solana:So111"}
    assert out["ethereum:0xA0b8"].price_usd == 1.0009
    assert out["ethereum:0xA0b8"].decimals == 6
    assert out["solana:So111"].timestamp == 1_700_000_123
    # the timestamp + coins reach the path; searchWidth rides as a query param
    assert "/prices/historical/1700000000" in captured["url"]
    assert "ethereum" in captured["url"] and "0xA0b8" in captured["url"]
    assert captured["search_width"] == "4h"


def test_historical_prices_drops_bad_entries() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "coins": {
                    "a": {"price": 0, "timestamp": 1},  # non-positive price
                    "b": {"price": 2.0},  # missing timestamp
                    "c": {"price": 3.0, "timestamp": 5},  # good
                }
            },
        )

    out = _client(handler).historical_prices(["a", "b", "c"], 1)
    assert set(out) == {"c"}
    assert out["c"].price_usd == 3.0


def test_historical_prices_degrades_to_empty_on_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    assert _client(handler).historical_prices(["a"], 1) == {}


def test_historical_prices_skips_fetch_on_empty_input() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not fetch for an empty coin list")

    assert _client(handler).historical_prices([], 1) == {}
