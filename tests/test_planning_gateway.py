# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the planning tool-gateway contract."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from nexus_core.app.planning import CONTRACT_VERSION, build_planning_router
from nexus_core.data.providers import PriceBar


class _FakeRegimeEngine:
    """Duck-typed RegimeEngine returning a fixed live classification."""

    def __init__(self, regime: str = "GROWTH") -> None:
        self._regime = regime

    def classify(self) -> SimpleNamespace:
        return SimpleNamespace(regime=self._regime, confidence_score=80)


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
    app.include_router(build_planning_router(market=_FakeMarket(), regime_engine=_FakeRegimeEngine()))
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


def test_planning_response_carries_disclaimer() -> None:
    # Every planning result must carry the educational/not-a-projection disclaimer.
    body = _client().post("/mcp/tools/glide_path", json=_GLIDE).json()
    disclaimer = body["disclaimer"].lower()
    assert "not investment, tax, legal, or financial advice" in disclaimer
    assert "not predictions" in disclaimer  # MC variant: illustrative, not a forecast


def test_list_tools_version_handshake() -> None:
    r = _client().get("/mcp/tools")
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert "glide_path" in body["tools"]
    assert "correlation_matrix" in body["tools"]
    assert "capital_market_assumptions" in body["tools"]
    assert "tax_aware_withdrawal" in body["tools"]
    assert "regime_return_generator" in body["tools"]
    assert "monte_carlo_decumulation" in body["tools"]
    assert "roth_conversion" in body["tools"]
    assert "sequence_of_returns_stress" in body["tools"]


_MC_PAYLOAD: dict[str, Any] = {
    "contractVersion": "0.1.0",
    "currentAge": 45,
    "retirementAge": 65,
    "horizonAge": 95,
    "accounts": [
        {"type": "traditional", "balance": 1200000, "allocation": {"us_equity": 0.6, "us_bonds": 0.4}},
        {"type": "roth", "balance": 300000, "allocation": {"us_equity": 0.8, "us_bonds": 0.2}},
    ],
    "assetClasses": [
        {"id": "us_equity", "label": "US Equity", "expectedReturn": 0.07, "volatility": 0.16, "lambda": 0.35},
        {"id": "us_bonds", "label": "US Bonds", "expectedReturn": 0.03, "volatility": 0.05, "lambda": 0.10},
    ],
    "correlations": None,
    "annualSpend": 120000,
    "spendColaRate": 0.025,
    "guaranteedIncome": [{"label": "Social Security", "annualAmount": 42000, "startAge": 67, "colaRate": 0.02}],
    "filingStatus": "married_joint",
    "returnModel": "emf_regime",
    "paths": 3000,
    "seed": 12345,
    "pathCacheKey": None,
}


def test_monte_carlo_default_scenario_non_degenerate() -> None:
    # §5.2 default with retirementAge 65 (accumulate 45→65, then decumulate):
    # a plausible, non-degenerate result.
    r = _client().post("/mcp/tools/monte_carlo_decumulation", json=_MC_PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert 0.0 < body["successProbability"] <= 1.0
    assert set(body["terminalValues"]) == {"p10", "p25", "p50", "p75", "p90"}
    assert body["terminalValues"]["p90"] > 0  # upside paths retain wealth
    assert len(body["medianBalanceByYear"]) == 50  # horizonAge - currentAge
    assert len(body["regimePathSummary"]) == 50  # emf_regime populated
    assert body["seedUsed"] == 12345


def test_monte_carlo_retirement_age_lifts_success() -> None:
    # Accumulating until 65 must beat withdrawing from 45 (the no-retirementAge case).
    with_ret = _client().post("/mcp/tools/monte_carlo_decumulation", json=_MC_PAYLOAD).json()
    no_ret = _client().post(
        "/mcp/tools/monte_carlo_decumulation",
        json={k: v for k, v in _MC_PAYLOAD.items() if k != "retirementAge"},
    ).json()
    assert with_ret["successProbability"] > no_ret["successProbability"]


def test_monte_carlo_deterministic() -> None:
    a = _client().post("/mcp/tools/monte_carlo_decumulation", json=_MC_PAYLOAD).json()
    b = _client().post("/mcp/tools/monte_carlo_decumulation", json=_MC_PAYLOAD).json()
    assert a == b  # same payload + seed ⇒ identical


def test_monte_carlo_pathcachekey_reuse_not_an_error() -> None:
    r = _client().post(
        "/mcp/tools/monte_carlo_decumulation", json={**_MC_PAYLOAD, "pathCacheKey": "emf-v1-777"}
    )
    assert r.status_code == 200  # reuses seed 777; a stale/unknown key is never an error


def test_monte_carlo_bad_allocation_returns_400() -> None:
    bad = {
        **_MC_PAYLOAD,
        "accounts": [{"type": "traditional", "balance": 1000, "allocation": {"us_equity": 0.5, "us_bonds": 0.4}}],
    }
    r = _client().post("/mcp/tools/monte_carlo_decumulation", json=bad)
    assert r.status_code == 400
    assert "sums to" in r.text


def test_monte_carlo_unknown_model_returns_400() -> None:
    r = _client().post(
        "/mcp/tools/monte_carlo_decumulation", json={**_MC_PAYLOAD, "returnModel": "crystal_ball"}
    )
    assert r.status_code == 400


def test_regime_return_generator_live_regime_and_matrix() -> None:
    r = _client().post(
        "/mcp/tools/regime_return_generator",
        json={
            "contractVersion": "0.1.0",
            "assetClasses": [
                {"id": "us_equity", "label": "US Equity", "expectedReturn": 0.07, "volatility": 0.16, "lambda": 0.35}
            ],
            "horizonYears": 50,
            "paths": 1000,
            "seed": 42,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["currentRegime"] == "expansion"  # fake GROWTH → expansion
    regimes = ["expansion", "inflationary", "deflationary", "stagflation", "crisis"]
    tm = body["transitionMatrix"]
    assert set(tm) == set(regimes)
    for frm in regimes:
        assert set(tm[frm]) == set(regimes)
        assert abs(sum(tm[frm].values()) - 1.0) < 1e-9  # rows sum to 1
    assert body["pathCacheKey"] == "emf-v1-42"  # encodes the seed
    assert body["seedUsed"] == 42


def test_regime_return_generator_requires_lambda() -> None:
    r = _client().post(
        "/mcp/tools/regime_return_generator",
        json={
            "assetClasses": [{"id": "us_equity", "label": "US Equity", "expectedReturn": 0.07, "volatility": 0.16}],
            "horizonYears": 50,
        },
    )
    assert r.status_code == 400
    assert "lambda" in r.text


def test_tax_aware_withdrawal_happy_path() -> None:
    r = _client().post(
        "/mcp/tools/tax_aware_withdrawal",
        json={
            "contractVersion": "0.1.0",
            "year": 2026,
            "filingStatus": "married_joint",
            "accounts": [
                {"type": "taxable", "balance": 200000, "allocation": {"us_equity": 1.0}},
                {"type": "traditional", "balance": 800000, "allocation": {"us_equity": 1.0}},
            ],
            "grossNeed": 120000,
            "age": 65,
            "otherTaxableIncome": 0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["withdrawals"][0]["type"] == "taxable"
    assert "totalTax" in body and "effectiveRate" in body and body["rmdSatisfied"] is True


def test_tax_aware_withdrawal_infeasible_returns_422() -> None:
    r = _client().post(
        "/mcp/tools/tax_aware_withdrawal",
        json={
            "year": 2026,
            "filingStatus": "single",
            "accounts": [{"type": "roth", "balance": 1000, "allocation": {"x": 1.0}}],
            "grossNeed": 50000,
            "age": 65,
        },
    )
    assert r.status_code == 422
    assert "insufficient" in r.text.lower()


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
    r = _client().post("/mcp/tools/not_a_real_planning_tool", json=_GLIDE)
    assert r.status_code == 404
    assert "unknown tool" in r.text


def test_identity_field_rejected_400() -> None:
    r = _client().post("/mcp/tools/glide_path", json={**_GLIDE, "email": "a@b.com"})
    assert r.status_code == 400
    assert "identity" in r.text.lower()


_ROTH: dict[str, Any] = {
    "contractVersion": "0.1.0",
    "currentTaxableIncome": 100_000,
    "filingStatus": "single",
    "conversionAmount": 10_000,
    "growthRate": 0.05,
    "years": 10,
    "retirementMarginalRate": 0.24,
    "taxesPaidFromConversion": True,
}


def test_roth_conversion_happy_path() -> None:
    r = _client().post("/mcp/tools/roth_conversion", json=_ROTH)
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["conversionTax"] == 2_200.0  # 10k inside the 22% bracket
    assert body["effectiveConversionRate"] == 0.22
    assert body["rothSeed"] == 7_800.0
    # retirement rate (24%) > effective conversion rate (22%) -> converting wins
    assert body["netBenefit"] > 0


def test_roth_conversion_bad_filing_status_400() -> None:
    r = _client().post(
        "/mcp/tools/roth_conversion", json={**_ROTH, "filingStatus": "martian"}
    )
    assert r.status_code == 400
    assert "filingStatus" in r.text


_SOR: dict[str, Any] = {
    "contractVersion": "0.1.0",
    "initialBalance": 100.0,
    "netSpendByYear": [50.0, 50.0],
    "annualReturns": [0.5, -0.4],
}


def test_sequence_of_returns_stress_happy_path() -> None:
    r = _client().post("/mcp/tools/sequence_of_returns_stress", json=_SOR)
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    # worst-first depletes by year 1; best-first survives (see engine tests).
    assert body["worstFirst"] == {"terminalBalance": 0.0, "depletedYear": 1}
    assert body["bestFirst"]["depletedYear"] is None
    assert body["sequenceRiskGap"] > 0


def test_sequence_of_returns_stress_length_mismatch_400() -> None:
    r = _client().post(
        "/mcp/tools/sequence_of_returns_stress",
        json={**_SOR, "annualReturns": [0.5]},
    )
    assert r.status_code == 400
    assert "same length" in r.text


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
