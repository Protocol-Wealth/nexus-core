# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Integration tests for the /api/benchmarks router (CoinGecko via MockTransport)."""

from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.benchmarks import build_benchmarks_router
from nexus_core.data.market import CoinGeckoMarketData

# Two OHLC bars per coin: close 2000 → 3000 (+50%). Rows are [ts_ms, o, h, l, c].
_OHLC = [[1_000_000, 2000, 2100, 1900, 2000], [2_000_000, 2900, 3100, 2800, 3000]]


def _coingecko(handler) -> CoinGeckoMarketData:  # type: ignore[no-untyped-def]
    return CoinGeckoMarketData(http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def _app(handler) -> FastAPI:  # type: ignore[no-untyped-def]
    app = FastAPI()
    app.include_router(build_benchmarks_router(coingecko=_coingecko(handler)))
    return app


def test_list_benchmarks() -> None:
    app = _app(lambda req: httpx.Response(200, json=_OHLC))
    r = TestClient(app).get("/api/benchmarks")
    assert r.status_code == 200
    names = [b["name"] for b in r.json()["benchmarks"]]
    assert "ETH" in names and "ETH-USDC 50/50" in names


def test_series_computes_base_100() -> None:
    app = _app(lambda req: httpx.Response(200, json=_OHLC))
    r = TestClient(app).get("/api/benchmarks/series?days=90")
    assert r.status_code == 200
    body = r.json()
    by_name = {b["name"]: b for b in body["benchmarks"]}
    # ETH +50% → 150 end; 50/50 ETH-USDC → +25% → 125 end.
    assert by_name["ETH"]["total_return_pct"] == 150.0 - 100.0
    assert by_name["ETH"]["points"][-1]["value"] == 150.0
    assert by_name["ETH-USDC 50/50"]["points"][-1]["value"] == 125.0
    assert body["points"] == 2


def test_series_503_when_no_history() -> None:
    app = _app(lambda req: httpx.Response(500, text="err"))
    r = TestClient(app).get("/api/benchmarks/series")
    assert r.status_code == 503


def test_series_days_validation() -> None:
    app = _app(lambda req: httpx.Response(200, json=_OHLC))
    assert TestClient(app).get("/api/benchmarks/series?days=0").status_code == 422
    assert TestClient(app).get("/api/benchmarks/series?days=9999").status_code == 422
