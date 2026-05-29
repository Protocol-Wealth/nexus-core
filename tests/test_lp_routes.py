# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Integration tests for the /api/lp router (real clients + MockTransport)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.lp import build_lp_router
from nexus_core.data.onchain import MerklClient, TatumClient, TheGraphClient

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
                "sqrtPrice": "793073905181059963158917209204",  # ~tick 200
                "tick": "200",
                "feeTier": "3000",
                "liquidity": "1000000000000000000",
                "totalValueLockedUSD": "10000000",
                "volumeUSD": "365000000",
                "token0": {"id": "0xt0", "symbol": "USDC", "decimals": "6"},
                "token1": {"id": "0xt1", "symbol": "WETH", "decimals": "18"},
                "poolDayData": [{"volumeUSD": "1000000"}],
            },
        }
    }
}


def _mk(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _graph_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_POSITION_DATA)


def _tatum_handler(request: httpx.Request) -> httpx.Response:
    words = ["00" * 32] * 10 + [f"{1_000_000:064x}", f"{10**15:064x}"]
    return httpx.Response(200, json={"result": "0x" + "".join(words)})


def _merkl_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json=[{"identifier": "0xpool", "name": "R", "chainId": 1, "apr": 4.0, "status": "LIVE"}],
    )


def _app(*, graph_key: str | None = "k") -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_lp_router(
            thegraph=TheGraphClient(api_key=graph_key, http_client=_mk(_graph_handler)),
            tatum=TatumClient(api_key="k", http_client=_mk(_tatum_handler)),
            merkl=MerklClient(http_client=_mk(_merkl_handler)),
        )
    )
    return app


def test_lp_chains() -> None:
    r = TestClient(_app()).get("/api/lp/chains")
    assert r.status_code == 200
    assert {"chain": "ethereum", "protocol": "uniswap", "version": "v3"} in r.json()["chains"]


def test_lp_analytics_fields() -> None:
    client = TestClient(_app())
    r = client.get("/api/lp/uniswap-v3/ethereum/123/analytics?price_token0_usd=1&price_token1_usd=2000")
    assert r.status_code == 200
    body = r.json()
    assert body["token_id"] == "123"
    assert body["in_range"] is True
    assert body["reward_apr"] == 4.0  # from Merkl
    assert body["uncollected_fees_source"] == "rpc_tokens_owed"
    # uncollected: 1_000_000/1e6 USDC = 1.0 USDC; 1e15/1e18 WETH = 0.001 WETH
    assert body["uncollected_fees0"] == 1.0
    assert body["uncollected_fees1"] == 0.001
    assert body["total_apr_estimate"] >= body["reward_apr"]
    assert "disclaimer" in body


def test_lp_bad_chain_400() -> None:
    r = TestClient(_app()).get("/api/lp/uniswap-v3/solana/1/analytics?price_token0_usd=1&price_token1_usd=1")
    assert r.status_code == 400


def test_lp_unconfigured_503() -> None:
    r = TestClient(_app(graph_key=None)).get(
        "/api/lp/uniswap-v3/ethereum/1/analytics?price_token0_usd=1&price_token1_usd=1"
    )
    assert r.status_code == 503


def test_lp_missing_price_params_422() -> None:
    r = TestClient(_app()).get("/api/lp/uniswap-v3/ethereum/123/analytics")
    assert r.status_code == 422  # required query params


def test_lp_missing_position_404() -> None:
    app = FastAPI()
    app.include_router(
        build_lp_router(
            thegraph=TheGraphClient(
                api_key="k",
                http_client=_mk(lambda req: httpx.Response(200, json={"data": {"position": None}})),
            ),
            tatum=TatumClient(api_key="k", http_client=_mk(_tatum_handler)),
            merkl=MerklClient(http_client=_mk(_merkl_handler)),
        )
    )
    r = TestClient(app).get("/api/lp/uniswap-v3/ethereum/999/analytics?price_token0_usd=1&price_token1_usd=1")
    assert r.status_code == 404
