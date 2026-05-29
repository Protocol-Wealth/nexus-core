# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the DefiLlama DeFi TVL client.

Hermetic — every request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from nexus_core.data.onchain import DefiLlamaClient


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_get_protocols_sorts_and_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/protocols"
        return httpx.Response(
            200,
            json=[
                {"name": "Aave", "symbol": "AAVE", "tvl": 12_000_000_000, "category": "Lending",
                 "chains": ["Ethereum", "Base"], "slug": "aave", "change_1d": 0.5, "change_7d": -1.2},
                {"name": "Zero", "symbol": "ZRO", "tvl": None, "category": "Dexes",
                 "chains": ["Ethereum"], "slug": "zero"},
                {"name": "Lido", "symbol": "LDO", "tvl": 30_000_000_000, "category": "Liquid Staking",
                 "chains": ["Ethereum"], "slug": "lido"},
            ],
        )

    protocols = DefiLlamaClient(http_client=_client(handler)).get_protocols(limit=5)
    # null-TVL protocol dropped; remaining sorted by TVL desc.
    assert [p.name for p in protocols] == ["Lido", "Aave"]
    assert protocols[1].chains == ["Ethereum", "Base"]
    assert protocols[1].change_7d == -1.2


def test_get_protocols_respects_limit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"name": f"P{i}", "symbol": "", "tvl": float(i), "slug": f"p{i}"} for i in range(1, 10)],
        )

    protocols = DefiLlamaClient(http_client=_client(handler)).get_protocols(limit=3)
    assert len(protocols) == 3
    assert protocols[0].name == "P9"


def test_get_protocol_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/protocol/aave"
        return httpx.Response(
            200,
            json={"name": "Aave", "symbol": "AAVE", "tvl": 12_000_000_000.0,
                  "chains": ["Ethereum"], "category": "Lending", "url": "https://aave.com"},
        )

    detail = DefiLlamaClient(http_client=_client(handler)).get_protocol("aave")
    assert detail is not None
    assert detail["name"] == "Aave"
    assert detail["tvl"] == 12_000_000_000.0


def test_get_protocol_with_list_tvl_history_yields_none_tvl() -> None:
    # Some /protocol/{slug} payloads return tvl as a historical series, not a scalar.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"name": "X", "tvl": [{"date": 1, "totalLiquidityUSD": 1}]})

    detail = DefiLlamaClient(http_client=_client(handler)).get_protocol("x")
    assert detail is not None
    assert detail["tvl"] is None


def test_get_chains_sorts_and_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/chains"
        return httpx.Response(
            200,
            json=[
                {"name": "Ethereum", "tvl": 80_000_000_000, "tokenSymbol": "ETH"},
                {"name": "Dead", "tvl": 0, "tokenSymbol": "X"},
                {"name": "Base", "tvl": 5_000_000_000, "tokenSymbol": "ETH"},
            ],
        )

    chains = DefiLlamaClient(http_client=_client(handler)).get_chains()
    assert [c["name"] for c in chains] == ["Ethereum", "Base"]


def test_http_error_degrades_to_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    client = DefiLlamaClient(http_client=_client(handler))
    assert client.get_protocols() == []
    assert client.get_protocol("aave") is None
    assert client.get_chains() == []
