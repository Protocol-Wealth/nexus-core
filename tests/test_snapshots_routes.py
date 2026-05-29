# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the snapshot trigger + persisted-history router (DB mocked)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app import snapshots as snap_mod
from nexus_core.app.snapshots import build_snapshots_router
from nexus_core.data.market import CoinGeckoMarketData

_PRICES = {"bitcoin": 60000.0, "ethereum": 3000.0, "solana": 150.0}


def _cg() -> CoinGeckoMarketData:
    def handler(request: httpx.Request) -> httpx.Response:
        ids = request.url.params.get("ids", "")
        return httpx.Response(200, json={ids: {"usd": _PRICES.get(ids, 1.0)}})

    return CoinGeckoMarketData(http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(build_snapshots_router(coingecko=_cg()))
    return TestClient(app)


def test_run_snapshot_503_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SNAPSHOT_TOKEN", raising=False)
    r = _client().post("/api/internal/snapshot/run")
    assert r.status_code == 503


def test_run_snapshot_403_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNAPSHOT_TOKEN", "secret")
    r = _client().post("/api/internal/snapshot/run", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 403


def test_run_snapshot_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNAPSHOT_TOKEN", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///marketdata?host=/cloudsql/x")
    captured: dict[str, Any] = {}

    async def fake_write(snapshot_date: str, prices: dict[str, float]) -> None:
        captured["date"] = snapshot_date
        captured["prices"] = prices

    monkeypatch.setattr(snap_mod, "write_benchmark_snapshot", fake_write)
    r = _client().post("/api/internal/snapshot/run", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["stored"] is True
    assert body["prices"]["BTC"] == 60000.0
    assert body["prices"]["USDC"] == 1.0
    assert captured["prices"]["ETH"] == 3000.0


def test_run_snapshot_502_incomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNAPSHOT_TOKEN", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")

    def handler(request: httpx.Request) -> httpx.Response:
        ids = request.url.params.get("ids", "")
        if ids == "bitcoin":
            return httpx.Response(200, json={"bitcoin": {"usd": 60000.0}})
        return httpx.Response(200, json={})  # ETH/SOL unpriced → get_quote None

    app = FastAPI()
    cg = CoinGeckoMarketData(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    app.include_router(build_snapshots_router(coingecko=cg))
    r = TestClient(app).post("/api/internal/snapshot/run", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 502  # completeness gate: never persist a partial day


def test_history_503_without_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _client().get("/api/benchmarks/history").status_code == 503


def test_history_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")

    async def fake_read(limit: int = 365) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(snap_mod, "read_benchmark_snapshots", fake_read)
    body = _client().get("/api/benchmarks/history").json()
    assert body["snapshots"] == 0
    assert body["benchmarks"] == []


def test_history_computes_base_100(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")

    async def fake_read(limit: int = 365) -> list[dict[str, Any]]:
        return [
            {"date": "2026-01-01", "prices": {"BTC": 40000, "ETH": 2000, "SOL": 100, "USDC": 1.0}},
            {"date": "2026-01-02", "prices": {"BTC": 44000, "ETH": 3000, "SOL": 100, "USDC": 1.0}},
        ]

    monkeypatch.setattr(snap_mod, "read_benchmark_snapshots", fake_read)
    body = _client().get("/api/benchmarks/history").json()
    assert body["snapshots"] == 2
    by_name = {b["name"]: b for b in body["benchmarks"]}
    # ETH 2000→3000 = +50% → end 150; 50/50 ETH-USDC → +25% → end 125
    assert by_name["ETH"]["points"][-1]["value"] == pytest.approx(150.0)
    assert by_name["ETH-USDC 50/50"]["points"][-1]["value"] == pytest.approx(125.0)


def test_history_forward_fills_missing_asset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")

    async def fake_read(limit: int = 365) -> list[dict[str, Any]]:
        return [
            {"date": "2026-01-01", "prices": {"BTC": 40000, "ETH": 2000, "SOL": 100, "USDC": 1.0}},
            {"date": "2026-01-02", "prices": {"BTC": 44000, "SOL": 100, "USDC": 1.0}},  # ETH missing
        ]

    monkeypatch.setattr(snap_mod, "read_benchmark_snapshots", fake_read)
    body = _client().get("/api/benchmarks/history").json()
    by_name = {b["name"]: b for b in body["benchmarks"]}
    # ETH forward-filled to 2000 on day 2 → flat (end 100), NOT a false −100% crash.
    assert by_name["ETH"]["points"][-1]["value"] == pytest.approx(100.0)
