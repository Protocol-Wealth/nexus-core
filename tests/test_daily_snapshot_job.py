# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the daily snapshot Cloud Run Job (CoinGecko + DB write mocked)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from nexus_core.data.market import CoinGeckoMarketData
from nexus_core.jobs import daily_snapshot

_PRICES = {"bitcoin": 60000.0, "ethereum": 3000.0, "solana": 150.0}


def _cg(handler: Any) -> CoinGeckoMarketData:
    return CoinGeckoMarketData(http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def _full_handler(request: httpx.Request) -> httpx.Response:
    ids = request.url.params.get("ids", "")
    return httpx.Response(200, json={ids: {"usd": _PRICES.get(ids, 1.0)}})


def test_run_snapshot_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")
    captured: dict[str, Any] = {}

    async def fake_write(snapshot_date: str, prices: dict[str, float]) -> None:
        captured["date"] = snapshot_date
        captured["prices"] = prices

    monkeypatch.setattr(daily_snapshot, "write_benchmark_snapshot", fake_write)
    result = asyncio.run(daily_snapshot.run_snapshot(_cg(_full_handler)))
    assert result["prices"]["BTC"] == 60000.0  # type: ignore[index]
    assert result["prices"]["USDC"] == 1.0  # type: ignore[index]
    assert captured["prices"]["ETH"] == 3000.0


def test_run_snapshot_incomplete_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")

    async def fake_write(snapshot_date: str, prices: dict[str, float]) -> None:  # pragma: no cover
        raise AssertionError("must not write a partial day")

    monkeypatch.setattr(daily_snapshot, "write_benchmark_snapshot", fake_write)

    def partial(request: httpx.Request) -> httpx.Response:
        ids = request.url.params.get("ids", "")
        if ids == "bitcoin":
            return httpx.Response(200, json={"bitcoin": {"usd": 60000.0}})
        return httpx.Response(200, json={})  # ETH/SOL unpriced → get_quote None

    with pytest.raises(RuntimeError, match="Incomplete"):
        asyncio.run(daily_snapshot.run_snapshot(_cg(partial)))


def test_run_snapshot_no_db_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        asyncio.run(daily_snapshot.run_snapshot(_cg(_full_handler)))


def test_run_returns_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    # run() wraps run_snapshot and never raises — returns 1 on failure.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert daily_snapshot.run() == 1
