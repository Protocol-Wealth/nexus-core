# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the persisted benchmark-history router (DB mocked).

The write path is the ``nexus-core snapshot`` Cloud Run Job (see
test_daily_snapshot_job.py) — there is no public write endpoint to test here.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app import snapshots as snap_mod
from nexus_core.app.snapshots import build_snapshots_router
from nexus_core.data.db import DatabaseUnavailableError


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(build_snapshots_router())
    return TestClient(app)


def test_history_503_without_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert _client().get("/api/benchmarks/history").status_code == 503


def test_history_503_when_db_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    # DATABASE_URL is set but Cloud SQL is momentarily unreachable: the read
    # raises DatabaseUnavailableError → the route degrades to 503, never 500.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")

    async def fake_read(limit: int = 365) -> list[dict[str, Any]]:
        raise DatabaseUnavailableError("benchmark history is temporarily unavailable")

    monkeypatch.setattr(snap_mod, "read_benchmark_snapshots", fake_read)
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
