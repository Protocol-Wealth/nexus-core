# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the market-data cache + usage-tracking wrappers."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.routes import build_router
from nexus_core.data.market import CachedMarketData, UsageTrackingMarketData
from nexus_core.data.providers import PriceBar, Quote


class _CountingProvider:
    """Inner provider that counts calls; returns None/[] for the symbol 'MISS'."""

    def __init__(self) -> None:
        self.quote_calls = 0
        self.history_calls = 0

    def get_quote(self, symbol: str) -> Quote | None:
        self.quote_calls += 1
        return None if symbol == "MISS" else Quote(symbol=symbol, price=100.0)

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        self.history_calls += 1
        if symbol == "MISS":
            return []
        return [PriceBar(timestamp="2026-01-01", open=1.0, high=1.0, low=1.0, close=1.0)]


def test_cache_serves_repeats_from_memory() -> None:
    inner = _CountingProvider()
    cached = CachedMarketData(inner)
    for _ in range(3):
        assert cached.get_quote("AAPL") is not None
    assert inner.quote_calls == 1  # only the first reached upstream
    report = cached.usage_report()
    assert report["cache"]["hits"] == 2
    assert report["cache"]["misses"] == 1


def test_cache_does_not_cache_misses() -> None:
    inner = _CountingProvider()
    cached = CachedMarketData(inner)
    assert cached.get_quote("MISS") is None
    assert cached.get_quote("MISS") is None
    assert inner.quote_calls == 2  # None is not cached → retried


def test_history_cache_keyed_by_args() -> None:
    inner = _CountingProvider()
    cached = CachedMarketData(inner)
    cached.get_price_history("AAPL", days=30)
    cached.get_price_history("AAPL", days=30)  # cache hit
    cached.get_price_history("AAPL", days=90)  # different key → upstream
    assert inner.history_calls == 2


def test_usage_tracking_counts_calls() -> None:
    tracked = UsageTrackingMarketData(_CountingProvider(), "mboum")
    tracked.get_quote("X")
    tracked.get_quote("Y")
    tracked.get_price_history("Z")
    assert tracked.usage == {"provider": "mboum", "get_quote": 2, "get_price_history": 1}


def test_usage_report_aggregates_tracked_providers() -> None:
    mboum = UsageTrackingMarketData(_CountingProvider(), "mboum")
    cached = CachedMarketData(mboum, tracked=[mboum])
    cached.get_quote("AAPL")
    report = cached.usage_report()
    assert report["tracked_providers"][0]["provider"] == "mboum"
    assert report["tracked_providers"][0]["get_quote"] == 1


def test_usage_endpoint_reports_stats() -> None:
    market = CachedMarketData(
        _CountingProvider(),
        tracked=[UsageTrackingMarketData(_CountingProvider(), "mboum")],
    )
    market.get_quote("AAPL")  # one miss recorded
    app = FastAPI()
    app.include_router(build_router(engine=object(), market=market, macro=object()))  # type: ignore[arg-type]
    with TestClient(app) as client:
        r = client.get("/api/usage")
    assert r.status_code == 200
    body: dict[str, Any] = r.json()
    assert "cache" in body and body["cache"]["misses"] == 1
    assert body["tracked_providers"][0]["provider"] == "mboum"
    assert r.headers["cache-control"] == "public, max-age=30"


def test_usage_endpoint_empty_when_no_report() -> None:
    # A plain provider without usage_report → endpoint returns {} gracefully.
    app = FastAPI()
    app.include_router(build_router(engine=object(), market=_CountingProvider(), macro=object()))  # type: ignore[arg-type]
    with TestClient(app) as client:
        assert client.get("/api/usage").json() == {}
