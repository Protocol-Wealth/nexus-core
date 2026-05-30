# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the planning tool-gateway contract."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from nexus_core.app.planning import CONTRACT_VERSION, build_planning_router
from nexus_core.data.providers import PriceBar


class _FakeMarket:
    """Canned daily closes for the proxy tickers used by correlation_matrix."""

    _DATES = [f"2026-01-{d:02d}T00:00:00Z" for d in range(1, 13)]
    _SERIES = {"VTI": (100.0, 1.0), "AGG": (50.0, -0.4)}  # base, drift sign

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        if symbol not in self._SERIES:
            return []
        base, k = self._SERIES[symbol]
        closes = [base + k * ((i % 3) - 1) + i * 0.1 for i in range(len(self._DATES))]
        return [
            PriceBar(timestamp=d, open=c, high=c + 1, low=c - 1, close=c, volume=10.0)
            for d, c in zip(self._DATES, closes, strict=True)
        ]


def _client(*, cors: bool = False) -> TestClient:
    app = FastAPI()
    if cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )
    app.include_router(build_planning_router(market=_FakeMarket()))
    return TestClient(app)


_GLIDE: dict[str, Any] = {
    "contractVersion": "0.1.0",
    "currentAge": 45,
    "retirementAge": 65,
    "horizonAge": 95,
    "startEquityWeight": 0.7,
    "endEquityWeight": 0.3,
    "shape": "linear",
}


def test_glide_path_happy_path() -> None:
    r = _client().post("/mcp/tools/glide_path", json=_GLIDE)
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    weights = body["equityWeightByAge"]
    assert weights["45"] == 0.7
    assert weights["95"] == 0.3
    assert len(weights) == 51  # currentAge..horizonAge inclusive


def test_list_tools_version_handshake() -> None:
    r = _client().get("/mcp/tools")
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert "glide_path" in body["tools"]
    assert "correlation_matrix" in body["tools"]


def test_correlation_matrix_happy_path() -> None:
    r = _client().post(
        "/mcp/tools/correlation_matrix",
        json={
            "contractVersion": "0.1.0",
            "assetClassIds": ["us_equity", "us_bonds"],
            "lookbackDays": 1260,
            "shrinkage": True,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    matrix = body["matrix"]
    assert matrix["us_equity"]["us_equity"] == 1.0
    assert matrix["us_bonds"]["us_bonds"] == 1.0
    assert matrix["us_equity"]["us_bonds"] == matrix["us_bonds"]["us_equity"]  # symmetric
    assert -1.0 <= matrix["us_equity"]["us_bonds"] <= 1.0
    assert body["asOf"] == "2026-01-12"  # latest aligned date


def test_correlation_matrix_unknown_asset_422() -> None:
    r = _client().post(
        "/mcp/tools/correlation_matrix",
        json={"assetClassIds": ["unobtanium"], "shrinkage": False},
    )
    assert r.status_code == 422
    assert "no return series available" in r.text


def test_correlation_matrix_bad_lookback_400() -> None:
    r = _client().post(
        "/mcp/tools/correlation_matrix",
        json={"assetClassIds": ["us_equity"], "lookbackDays": 5},
    )
    assert r.status_code == 400
    assert "lookbackDays" in r.text


def test_unknown_tool_returns_404() -> None:
    r = _client().post("/mcp/tools/monte_carlo_decumulation", json=_GLIDE)
    assert r.status_code == 404
    assert "unknown tool" in r.text


def test_identity_field_rejected_400() -> None:
    r = _client().post("/mcp/tools/glide_path", json={**_GLIDE, "email": "a@b.com"})
    assert r.status_code == 400
    assert "identity" in r.text.lower()


def test_nested_identity_field_rejected_400() -> None:
    body = {**_GLIDE, "accounts": [{"type": "roth", "owner": {"firstName": "X"}}]}
    r = _client().post("/mcp/tools/glide_path", json=body)
    assert r.status_code == 400
    assert "firstName" in r.text


def test_invalid_shape_returns_400() -> None:
    r = _client().post("/mcp/tools/glide_path", json={**_GLIDE, "shape": "spiral"})
    assert r.status_code == 400
    assert "shape" in r.text


def test_missing_field_returns_400_naming_the_field() -> None:
    incomplete = {k: v for k, v in _GLIDE.items() if k != "horizonAge"}
    r = _client().post("/mcp/tools/glide_path", json=incomplete)
    assert r.status_code == 400
    assert "horizonAge" in r.text


def test_invalid_age_order_returns_400() -> None:
    r = _client().post("/mcp/tools/glide_path", json={**_GLIDE, "currentAge": 70})
    assert r.status_code == 400


def test_non_json_body_returns_400() -> None:
    r = _client().post(
        "/mcp/tools/glide_path",
        content="not json",
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400


def test_cors_preflight_allows_custom_pw_headers() -> None:
    r = _client(cors=True).options(
        "/mcp/tools/glide_path",
        headers={
            "Origin": "https://pwplan.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-pw-contract-version,x-pw-audit-id,x-pw-subject-ref",
        },
    )
    assert r.status_code in (200, 204)
    allow = r.headers.get("access-control-allow-headers", "").lower()
    assert "x-pw-contract-version" in allow or allow == "*"
