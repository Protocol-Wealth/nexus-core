# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the nexus-core FastAPI application.

Hermetic — fake data providers are injected and the MCP transport is disabled
for the REST-only tests. The regime tests reuse the shared ``conftest.py``
stub providers, exercising the real classification pipeline against fixed data.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nexus_core.app import create_app
from nexus_core.data.providers import PriceBar, Quote


class _FakeMarket:
    """Market data provider returning canned values for app tests."""

    def get_quote(self, symbol: str) -> Quote | None:
        if symbol == "UNKNOWN":
            return None
        return Quote(symbol=symbol, price=123.45, timestamp="2026-01-05T00:00:00Z")

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        if symbol == "UNKNOWN":
            return []
        return [
            PriceBar(timestamp="2026-01-02", open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0),
            PriceBar(timestamp="2026-01-03", open=1.5, high=2.5, low=1.0, close=2.0, volume=20.0),
        ]


class _FakeMacro:
    """Macro data provider returning canned values for app tests."""

    def __init__(self, *, configured: bool = True) -> None:
        self._configured = configured

    def get_series(self, series_id: str) -> float | None:
        return 4.31 if series_id == "DGS10" else None

    def is_configured(self) -> bool:
        return self._configured


def _rest_client(macro: _FakeMacro | None = None) -> TestClient:
    app = create_app(
        market=_FakeMarket(),
        macro=macro if macro is not None else _FakeMacro(),
        enable_mcp=False,
    )
    return TestClient(app)


def test_landing_page() -> None:
    with _rest_client() as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Nexus Core" in response.text
    assert "text/html" in response.headers["content-type"]


def test_health() -> None:
    with _rest_client() as client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "nexus-core"


def test_openapi_schema_lists_endpoints() -> None:
    with _rest_client() as client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/regime" in paths
    assert "/api/market/quote/{symbol}" in paths
    assert "/api/economic/{series_id}" in paths


def test_quote_endpoint() -> None:
    with _rest_client() as client:
        response = client.get("/api/market/quote/SPY")
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "SPY"
    assert body["price"] == 123.45


def test_quote_not_found() -> None:
    with _rest_client() as client:
        response = client.get("/api/market/quote/UNKNOWN")
    assert response.status_code == 404


def test_history_endpoint() -> None:
    with _rest_client() as client:
        response = client.get("/api/market/history/SPY", params={"days": 30})
    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "SPY"
    assert len(body["bars"]) == 2
    assert body["bars"][0]["close"] == 1.5


def test_economic_endpoint() -> None:
    with _rest_client() as client:
        response = client.get("/api/economic/DGS10")
    assert response.status_code == 200
    assert response.json()["value"] == 4.31


def test_economic_unconfigured_returns_503() -> None:
    with _rest_client(macro=_FakeMacro(configured=False)) as client:
        response = client.get("/api/economic/DGS10")
    assert response.status_code == 503


def test_regime_endpoint(stub_market: object, stub_fred: object) -> None:
    app = create_app(market=stub_market, macro=stub_fred, enable_mcp=False)  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.get("/api/regime")
    assert response.status_code == 200
    body = response.json()
    assert "regime" in body
    assert "confidence_score" in body
    assert isinstance(body["signal_statuses"], list)


def test_regime_signals_endpoint(stub_market: object, stub_fred: object) -> None:
    app = create_app(market=stub_market, macro=stub_fred, enable_mcp=False)  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.get("/api/regime/signals")
    assert response.status_code == 200
    assert "vix" in response.json()


def test_cors_header_present() -> None:
    with _rest_client() as client:
        response = client.get("/health", headers={"Origin": "https://example.com"})
    assert response.headers.get("access-control-allow-origin") == "*"


def test_rate_limit_returns_429(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_RATE_LIMIT_PER_MIN", "3")
    app = create_app(market=_FakeMarket(), macro=_FakeMacro(), enable_mcp=False)
    with TestClient(app) as client:
        statuses = [client.get("/").status_code for _ in range(4)]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429


def test_health_exempt_from_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXUS_RATE_LIMIT_PER_MIN", "2")
    app = create_app(market=_FakeMarket(), macro=_FakeMacro(), enable_mcp=False)
    with TestClient(app) as client:
        statuses = [client.get("/health").status_code for _ in range(5)]
    assert statuses == [200, 200, 200, 200, 200]


def test_mcp_transport_mounted() -> None:
    app = create_app(market=_FakeMarket(), macro=_FakeMacro(), enable_mcp=True)
    mounted = {getattr(route, "path", None) for route in app.routes}
    assert "/mcp" in mounted
