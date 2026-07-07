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
from nexus_core.app.landing import render_landing
from nexus_core.app.mcp_guide import render_mcp_guide
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

    def get_series_observation(self, series_id: str) -> tuple[float, str] | None:
        value = self.get_series(series_id)
        return (value, "2026-01-05") if value is not None else None

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


def test_mcp_guide_page_served() -> None:
    with _rest_client() as client:
        response = client.get("/mcp-guide")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Connect to the MCP server" in response.text


def test_mcp_guide_connection_details() -> None:
    html = render_mcp_guide()
    assert "nexusmcp.site/mcp" in html  # hosted endpoint
    assert "nexus-core mcp" in html  # local stdio command
    assert "claude_desktop_config" in html  # Claude Desktop setup
    assert "not investment, tax, legal, or financial advice" in html.lower()


def test_mcp_guide_documents_pwplan_core_integration() -> None:
    html = render_mcp_guide()
    assert "Connecting pwplan-core to nexus-core" in html
    # All planning tool ids are listed for the browser consumer.
    for tool_id in (
        "monte_carlo_decumulation",
        "solve_goal",
        "analyze_goals",
        "project_cash_flow",
        "cashflow_planning_bridge",
        "cash_reserve_analysis",
        "budget_pacing_projection",
        "education_funding",
        "education_vehicle_rules",
        "glide_path",
        "tax_aware_withdrawal",
        "correlation_matrix",
        "capital_market_assumptions",
        "regime_return_generator",
        "roth_conversion",
        "sequence_of_returns_stress",
        "rmd",
        "tax_bracket_headroom",
        "social_security_claiming",
        "regime_conditioned_swr",
        "portfolio_xray",
        "optimize_allocation",
        "fire",
        "risk_metrics",
        "rebalance",
        "irmaa_headroom",
        "analyze_roth_conversion",
        "sequence_conversions",
        "build_planning_report",
    ):
        assert tool_id in html, tool_id
    assert '"contractVersion": "0.1.0"' in html  # version handshake documented
    assert "retirementAge" in html  # the MC contract delta is called out


def test_landing_advertises_guide_when_mcp_enabled() -> None:
    assert "/mcp-guide" in render_landing(mcp_enabled=True)
    assert "MCP setup guide" in render_landing(mcp_enabled=True)
    assert "/mcp-guide" not in render_landing(mcp_enabled=False)


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
    assert "/mcp/tools" in paths
    assert "/api/lp/uniswap-v3/{chain}/positions" in paths


def test_openapi_has_servers_and_tag_descriptions() -> None:
    with _rest_client() as client:
        spec = client.get("/openapi.json").json()
    assert any("nexusmcp.site" in s["url"] for s in spec.get("servers", []))
    tags = {t["name"]: t.get("description", "") for t in spec.get("tags", [])}
    assert tags.get("planning") and tags.get("regime")


def test_landing_has_curl_quickstart() -> None:
    html = render_landing(mcp_enabled=True)
    assert "Try it" in html
    assert "curl" in html
    assert "Authorization: Bearer $NEXUS_SERVICE_API_KEY" in html
    assert "/api/planning/tools/glide_path" in html


def test_mcp_guide_has_troubleshooting() -> None:
    html = render_mcp_guide()
    assert "Tools not showing up" in html


def test_mcp_guide_documents_claude_code_setup() -> None:
    html = render_mcp_guide()
    # CLI one-liner + the shareable project-config form, both over HTTP.
    assert "claude mcp add --transport http nexus-core" in html
    assert '"type": "http"' in html


def test_mcp_guide_has_example_prompts() -> None:
    html = render_mcp_guide()
    assert "Try it — example prompts" in html
    # A prompt that drives the regime engine and one that drives the planning tools.
    assert "What macro regime are we in right now" in html
    assert "Monte Carlo decumulation" in html
    # The native planning tools take the request as a JSON `body` argument.
    assert "<code>body</code>" in html


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
    body = response.json()
    assert body["value"] == 4.31
    assert body["as_of"] == "2026-01-05"  # observation date, not fetch time
    assert body["source"] == "FRED"


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


def test_cache_control_headers() -> None:
    """Public GET endpoints advertise an edge-cacheable TTL; /health is no-store."""
    with _rest_client() as client:
        assert client.get("/api/regime").headers.get("cache-control") == "public, max-age=900"
        assert (
            client.get("/api/regime/signals").headers.get("cache-control") == "public, max-age=900"
        )
        assert (
            client.get("/api/market/quote/SPY").headers.get("cache-control")
            == "public, max-age=300"
        )
        assert (
            client.get("/api/market/history/SPY").headers.get("cache-control")
            == "public, max-age=3600"
        )
        assert (
            client.get("/api/economic/DGS10").headers.get("cache-control") == "public, max-age=3600"
        )
        assert client.get("/health").headers.get("cache-control") == "no-store"
