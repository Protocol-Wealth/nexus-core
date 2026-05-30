# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Integration tests for the /api/solana price router (Jupiter via MockTransport)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.solana import build_solana_router
from nexus_core.data.onchain import JupiterClient

_SOL = "So11111111111111111111111111111111111111112"
_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _mk(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _handler(request: httpx.Request) -> httpx.Response:
    ids = request.url.params.get("ids", "").split(",")
    body = {m: {"usdPrice": 80.0, "decimals": 9, "priceChange24h": 1.2} for m in ids if m == _SOL}
    body.update({m: {"usdPrice": 1.0, "decimals": 6} for m in ids if m == _USDC})
    return httpx.Response(200, json=body)


def _app(handler: Callable[[httpx.Request], httpx.Response] = _handler) -> FastAPI:
    app = FastAPI()
    app.include_router(build_solana_router(jupiter=JupiterClient(http_client=_mk(handler))))
    return app


def test_price_ok() -> None:
    r = TestClient(_app()).get(f"/api/solana/price/{_SOL}")
    assert r.status_code == 200
    body = r.json()
    assert body["mint"] == _SOL
    assert body["usd_price"] == 80.0
    assert body["price_change_24h_pct"] == 1.2
    assert "disclaimer" in body


def test_price_invalid_mint_400() -> None:
    assert TestClient(_app()).get("/api/solana/price/notamint").status_code == 400


def test_price_unknown_mint_404() -> None:
    # Valid base58 mint, but Jupiter returns no price for it.
    other = "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R"
    r = TestClient(_app(lambda _req: httpx.Response(200, json={}))).get(f"/api/solana/price/{other}")
    assert r.status_code == 404


def test_prices_batch() -> None:
    r = TestClient(_app()).get(f"/api/solana/prices?mints={_SOL},{_USDC}")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["prices"][_SOL]["usd_price"] == 80.0
    assert body["prices"][_USDC]["usd_price"] == 1.0


def test_prices_empty_400() -> None:
    assert TestClient(_app()).get("/api/solana/prices?mints=").status_code == 400


def test_prices_too_many_400() -> None:
    many = ",".join([_SOL] * 51)
    assert TestClient(_app()).get(f"/api/solana/prices?mints={many}").status_code == 400
