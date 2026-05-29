# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the The Graph Uniswap V3 position client (hermetic via MockTransport)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.onchain import TheGraphClient

_POSITION_DATA = {
    "data": {
        "position": {
            "id": "123",
            "owner": "0xowner",
            "liquidity": "1000000000000000000",
            "depositedToken0": "1000",
            "depositedToken1": "0.5",
            "tickLower": {"tickIdx": "100"},
            "tickUpper": {"tickIdx": "300"},
            "pool": {
                "id": "0xpool",
                "sqrtPrice": "79228162514264337593543950336",  # Q96 → tick ~0
                "tick": "200",
                "feeTier": "3000",
                "liquidity": "5000000000000000000",
                "totalValueLockedUSD": "10000000",
                "volumeUSD": "999999999",
                "token0": {"id": "0xt0", "symbol": "USDC", "decimals": "6"},
                "token1": {"id": "0xt1", "symbol": "WETH", "decimals": "18"},
                "poolDayData": [{"volumeUSD": "1000000"}, {"volumeUSD": "2000000"}],
            },
        }
    }
}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THEGRAPH_API_KEY", raising=False)
    c = TheGraphClient(api_key=None)
    assert c.is_configured() is False
    assert c.fetch_v3_position("ethereum", "1") is None


def test_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THEGRAPH_API_KEY", "k")
    assert TheGraphClient().is_configured() is True


def test_unsupported_chain_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request for an unsupported chain")

    assert TheGraphClient(api_key="k", http_client=_client(handler)).fetch_v3_position("solana", "1") is None


def test_fetch_v3_position_parses_and_uses_url_path_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("User-Agent", "").startswith("nexus-core")
        assert "/api/k/subgraphs/id/" in request.url.path  # key in URL path
        return httpx.Response(200, json=_POSITION_DATA)

    pos = TheGraphClient(api_key="k", http_client=_client(handler)).fetch_v3_position("ethereum", "123")
    assert pos is not None
    assert pos.token_id == "123"
    assert pos.liquidity == 1_000_000_000_000_000_000
    assert pos.tick_lower == 100 and pos.tick_upper == 300
    assert pos.current_tick == 200 and pos.fee_tier == 3000
    assert pos.decimals0 == 6 and pos.decimals1 == 18
    assert pos.token0_symbol == "USDC" and pos.token1_symbol == "WETH"
    assert pos.pool_tvl_usd == pytest.approx(10_000_000)
    assert pos.pool_avg_daily_volume_usd == pytest.approx(1_500_000)  # (1M+2M)/2
    assert pos.deposited0 == pytest.approx(1000.0)


def test_graphql_errors_degrade_to_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "boom"}]})

    assert TheGraphClient(api_key="k", http_client=_client(handler)).fetch_v3_position("ethereum", "1") is None


def test_http_error_degrades_to_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    assert TheGraphClient(api_key="k", http_client=_client(handler)).fetch_v3_position("ethereum", "1") is None


def test_missing_position_degrades_to_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"position": None}})

    assert TheGraphClient(api_key="k", http_client=_client(handler)).fetch_v3_position("ethereum", "9") is None
