# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the planning tool-gateway contract."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from nexus_core.app.planning import CONTRACT_VERSION, build_planning_router
from nexus_core.app.planning.contract import PlanningInputError
from nexus_core.app.planning.tools import _monte_carlo_decumulation_tool
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
    app.include_router(
        build_planning_router(market=_FakeMarket(), regime_engine=_FakeRegimeEngine())
    )
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
    assert "rmd" in body["tools"]
    assert "tax_bracket_headroom" in body["tools"]
    assert "social_security_claiming" in body["tools"]
    assert "regime_conditioned_swr" in body["tools"]
    assert "portfolio_xray" in body["tools"]
    assert "fire" in body["tools"]
    assert "risk_metrics" in body["tools"]
    assert "rebalance" in body["tools"]


_MC_PAYLOAD: dict[str, Any] = {
    "contractVersion": "0.1.0",
    "currentAge": 45,
    "retirementAge": 65,
    "horizonAge": 95,
    "accounts": [
        {
            "type": "traditional",
            "balance": 1200000,
            "allocation": {"us_equity": 0.6, "us_bonds": 0.4},
        },
        {"type": "roth", "balance": 300000, "allocation": {"us_equity": 0.8, "us_bonds": 0.2}},
    ],
    "assetClasses": [
        {
            "id": "us_equity",
            "label": "US Equity",
            "expectedReturn": 0.07,
            "volatility": 0.16,
            "lambda": 0.35,
        },
        {
            "id": "us_bonds",
            "label": "US Bonds",
            "expectedReturn": 0.03,
            "volatility": 0.05,
            "lambda": 0.10,
        },
    ],
    "correlations": None,
    "annualSpend": 120000,
    "spendColaRate": 0.025,
    "guaranteedIncome": [
        {"label": "Social Security", "annualAmount": 42000, "startAge": 67, "colaRate": 0.02}
    ],
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
    assert set(body["depletionStats"]["depletionAgePercentiles"]) == {"p10", "p50", "p90"}
    assert body["firstDecadeReturnVsOutcome"]["years"] == 10
    assert len(body["regimePathSummary"]) == 50  # emf_regime populated
    assert body["seedUsed"] == 12345


def test_monte_carlo_spend_schedule_late_ltc_bump_lowers_success() -> None:
    base_payload = {
        **_MC_PAYLOAD,
        "currentAge": 60,
        "retirementAge": 67,
        "horizonAge": 95,
        "accounts": [
            {
                "type": "traditional",
                "balance": 1200000,
                "allocation": {"us_equity": 0.6, "us_bonds": 0.4},
            }
        ],
        "annualSpend": 70000,
        "paths": 3000,
        "seed": 6789,
    }
    market = _FakeMarket()
    regime = _FakeRegimeEngine()
    base = _monte_carlo_decumulation_tool(base_payload, market, regime)
    shocked = _monte_carlo_decumulation_tool(
        {
            **base_payload,
            "spendSchedule": [
                {"mode": "delta", "startAge": 91, "endAge": 95, "amount": 70000}
            ],
        },
        market,
        regime,
    )
    assert shocked["successProbability"] < base["successProbability"]
    assert shocked["depletionStats"]["depletionAgePercentiles"]["p50"] >= 60


def test_monte_carlo_retirement_age_lifts_success() -> None:
    # Accumulating until 65 must beat withdrawing from 45 (the no-retirementAge case).
    with_ret = _client().post("/mcp/tools/monte_carlo_decumulation", json=_MC_PAYLOAD).json()
    no_ret = (
        _client()
        .post(
            "/mcp/tools/monte_carlo_decumulation",
            json={k: v for k, v in _MC_PAYLOAD.items() if k != "retirementAge"},
        )
        .json()
    )
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
        "accounts": [
            {
                "type": "traditional",
                "balance": 1000,
                "allocation": {"us_equity": 0.5, "us_bonds": 0.4},
            }
        ],
    }
    r = _client().post("/mcp/tools/monte_carlo_decumulation", json=bad)
    assert r.status_code == 400
    assert "sums to" in r.text


def test_monte_carlo_unknown_model_returns_400() -> None:
    r = _client().post(
        "/mcp/tools/monte_carlo_decumulation", json={**_MC_PAYLOAD, "returnModel": "crystal_ball"}
    )
    assert r.status_code == 400


def test_monte_carlo_invalid_spend_schedule_returns_400() -> None:
    with pytest.raises(PlanningInputError, match="spendSchedule mode"):
        _monte_carlo_decumulation_tool(
            {**_MC_PAYLOAD, "spendSchedule": [{"mode": "mystery", "startAge": 91, "amount": 1}]},
            _FakeMarket(),
            _FakeRegimeEngine(),
        )


def test_monte_carlo_too_many_asset_classes_returns_400() -> None:
    # SECURITY-AUDIT-2026-06-09 H8: the public, unauthenticated monte_carlo
    # surface allocated a (paths, years, n_assets) array + ran O(n^2)/O(n^3)
    # correlation/Cholesky on an UNBOUNDED asset count — a tiny body amplified
    # to a multi-GB allocation. The asset-count cap rejects it before any work.
    too_many = [
        {
            "id": f"asset_{i}",
            "label": f"Asset {i}",
            "expectedReturn": 0.05,
            "volatility": 0.10,
            "lambda": 0.10,
        }
        for i in range(65)  # > _MAX_ASSET_CLASSES (64)
    ]
    r = _client().post(
        "/mcp/tools/monte_carlo_decumulation",
        json={**_MC_PAYLOAD, "assetClasses": too_many},
    )
    assert r.status_code == 400
    assert "at most" in r.text  # "assetClasses must have at most 64 entries"


def test_regime_return_generator_live_regime_and_matrix() -> None:
    r = _client().post(
        "/mcp/tools/regime_return_generator",
        json={
            "contractVersion": "0.1.0",
            "assetClasses": [
                {
                    "id": "us_equity",
                    "label": "US Equity",
                    "expectedReturn": 0.07,
                    "volatility": 0.16,
                    "lambda": 0.35,
                }
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
            "assetClasses": [
                {
                    "id": "us_equity",
                    "label": "US Equity",
                    "expectedReturn": 0.07,
                    "volatility": 0.16,
                }
            ],
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
    r = _client().post("/mcp/tools/roth_conversion", json={**_ROTH, "filingStatus": "martian"})
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


def test_rmd_happy_path() -> None:
    r = _client().post(
        "/mcp/tools/rmd", json={"contractVersion": "0.1.0", "age": 73, "balance": 500_000}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["applies"] is True
    assert body["distributionPeriod"] == 26.5
    assert body["rmdAmount"] == round(500_000 / 26.5, 2)


def test_rmd_negative_balance_400() -> None:
    r = _client().post(
        "/mcp/tools/rmd", json={"contractVersion": "0.1.0", "age": 73, "balance": -1}
    )
    assert r.status_code == 400
    assert "balance" in r.text


def test_tax_bracket_headroom_happy_path() -> None:
    r = _client().post(
        "/mcp/tools/tax_bracket_headroom",
        json={
            "contractVersion": "0.1.0",
            "taxableIncome": 100_000,
            "filingStatus": "single",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["marginalRate"] == 0.22
    assert body["roomToNextBracket"] == 18_350.0
    assert body["nextRate"] == 0.24


def test_tax_bracket_headroom_bad_filing_400() -> None:
    r = _client().post(
        "/mcp/tools/tax_bracket_headroom",
        json={"contractVersion": "0.1.0", "taxableIncome": 100_000, "filingStatus": "x"},
    )
    assert r.status_code == 400
    assert "filingStatus" in r.text


def test_social_security_claiming_happy_path() -> None:
    r = _client().post(
        "/mcp/tools/social_security_claiming",
        json={"contractVersion": "0.1.0", "piaMonthly": 2_000, "fraAge": 67},
    )
    assert r.status_code == 200
    body = r.json()
    by_age = {row["claimAge"]: row for row in body["byClaimAge"]}
    assert by_age[62]["monthlyBenefit"] == 1_400.0
    assert by_age[70]["monthlyBenefit"] == 2_480.0
    assert len(body["breakevens"]) == 3


def test_social_security_bad_pia_400() -> None:
    r = _client().post(
        "/mcp/tools/social_security_claiming",
        json={"contractVersion": "0.1.0", "piaMonthly": 0},
    )
    assert r.status_code == 400
    assert "positive" in r.text


def test_regime_conditioned_swr_uses_live_regime() -> None:
    r = _client().post(
        "/mcp/tools/regime_conditioned_swr",
        json={"contractVersion": "0.1.0", "baseSwr": 0.04, "portfolioBalance": 1_000_000},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["regime"]  # a generic regime label from the live engine
    assert 0 < body["adjustedSwr"] < 1
    assert body["firstYearWithdrawal"] == round(1_000_000 * body["adjustedSwr"], 2)


def test_regime_conditioned_swr_bad_base_400() -> None:
    r = _client().post(
        "/mcp/tools/regime_conditioned_swr",
        json={"contractVersion": "0.1.0", "baseSwr": 1.5},
    )
    assert r.status_code == 400
    assert "base_swr" in r.text


_XRAY: dict[str, Any] = {
    "contractVersion": "0.1.0",
    "assetClasses": [
        {
            "id": "us_equity",
            "label": "US Equity",
            "expectedReturn": 0.07,
            "volatility": 0.16,
            "lambda": 0.35,
        },
        {
            "id": "us_bonds",
            "label": "US Bonds",
            "expectedReturn": 0.03,
            "volatility": 0.05,
            "lambda": 0.10,
        },
    ],
    "accounts": [
        {
            "type": "traditional",
            "balance": 700000,
            "allocation": {"us_equity": 0.65, "us_bonds": 0.35},
        },
        {"type": "roth", "balance": 300000, "allocation": {"us_equity": 0.65, "us_bonds": 0.35}},
    ],
}


def test_portfolio_xray_happy_path() -> None:
    r = _client().post("/mcp/tools/portfolio_xray", json=_XRAY)
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["regime"]  # live regime injected by the tool
    assert body["concentration"]["maxWeightAsset"] == "us_equity"
    assert body["accountMix"] == {"taxable": 0.0, "traditional": 0.7, "roth": 0.3}
    ids = {f["id"] for f in body["findings"]}
    assert {"concentration", "regime_sensitivity", "tax_location", "growth_posture"} <= ids


def test_portfolio_xray_bad_allocation_400() -> None:
    bad = {
        **_XRAY,
        "accounts": [
            {"type": "roth", "balance": 1000, "allocation": {"us_equity": 0.5, "us_bonds": 0.4}}
        ],
    }
    r = _client().post("/mcp/tools/portfolio_xray", json=bad)
    assert r.status_code == 400
    assert "sums to" in r.text


def test_fire_happy_path() -> None:
    r = _client().post(
        "/mcp/tools/fire",
        json={
            "contractVersion": "0.1.0",
            "currentAge": 40,
            "retirementAge": 65,
            "currentBalance": 300000,
            "annualContribution": 30000,
            "growthRate": 0.05,
            "annualSpend": 80000,
            "swr": 0.04,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["fireNumber"] == 2_000_000.0  # 80k / 0.04
    assert isinstance(body["coastReached"], bool)
    assert body["fireAge"] is None or body["fireAge"] >= 40


def test_fire_bad_swr_400() -> None:
    r = _client().post(
        "/mcp/tools/fire",
        json={
            "contractVersion": "0.1.0",
            "currentAge": 40,
            "retirementAge": 65,
            "currentBalance": 300000,
            "annualContribution": 30000,
            "growthRate": 0.05,
            "annualSpend": 80000,
            "swr": 1.5,
        },
    )
    assert r.status_code == 400
    assert "swr" in r.text


def test_risk_metrics_happy_path() -> None:
    r = _client().post(
        "/mcp/tools/risk_metrics",
        json={
            "contractVersion": "0.1.0",
            "returns": [0.12, -0.08, 0.15, -0.03, 0.06],
            "riskFreeRate": 0.02,
            "periodsPerYear": 1,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["periods"] == 5
    assert body["maxDrawdown"] <= 0.0
    assert body["valueAtRisk95"] >= 0.0


def test_risk_metrics_too_few_returns_400() -> None:
    r = _client().post(
        "/mcp/tools/risk_metrics",
        json={"contractVersion": "0.1.0", "returns": [0.1]},
    )
    assert r.status_code == 400
    assert "at least 2" in r.text


_REBALANCE: dict[str, Any] = {
    "contractVersion": "0.1.0",
    "assetClasses": [
        {"id": "us_equity", "label": "US Equity", "expectedReturn": 0.07, "volatility": 0.16},
        {"id": "us_bonds", "label": "US Bonds", "expectedReturn": 0.03, "volatility": 0.05},
    ],
    "accounts": [
        {"type": "taxable", "balance": 100000, "allocation": {"us_equity": 0.7, "us_bonds": 0.3}},
    ],
    "targetWeights": {"us_equity": 0.6, "us_bonds": 0.4},
}


def test_rebalance_happy_path() -> None:
    r = _client().post("/mcp/tools/rebalance", json=_REBALANCE)
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["totalValue"] == 100000.0
    rows = {row["id"]: row for row in body["perAsset"]}
    # 70% equity drifting to a 60% target -> sell 10k equity, buy 10k bonds.
    assert rows["us_equity"]["tradeAmount"] == -10000.0
    assert rows["us_bonds"]["tradeAmount"] == 10000.0
    assert body["turnover"] == 10000.0


def test_rebalance_targets_must_sum_to_one_400() -> None:
    bad = {**_REBALANCE, "targetWeights": {"us_equity": 0.6, "us_bonds": 0.3}}
    r = _client().post("/mcp/tools/rebalance", json=bad)
    assert r.status_code == 400
    assert "sum to 1" in r.text


# --- composite Roth/IRMAA tools (PlanningContract v1.0.0) ------------------

_ROTH_CONTRACT: dict[str, Any] = {
    "case_id": "gw-case-1",
    "tax_year": 2026,
    "filing_status": "mfj",
    "state_code": "PA",
    "birth_years": [1962, 1963],
    "medicare_enrolled": 2,
    "income_ex_conversion": {
        "pension": 30_000,
        "social_security_gross": 48_000,
        "taxable_interest": 5_000,
        "tax_exempt_interest": 8_000,
        "ordinary_dividends": 12_000,
        "qualified_dividends": 9_000,
        "long_term_gains": 10_000,
    },
    "accounts": {
        "trad_ira_aggregate": 1_400_000,
        "nondeductible_basis": 0,
        "roth_balance": 200_000,
        "taxable_liquidity": 250_000,
    },
    "intent": {"target_rule": "fill_to_irmaa_tier", "years": [2026, 2027]},
}


def test_analyze_roth_conversion_gateway() -> None:
    r = _client().post("/mcp/tools/analyze_roth_conversion", json={"contract": _ROTH_CONTRACT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contract_version"] == "1.1.0"
    assert len(body["years"]) == 2
    y0 = body["years"][0]
    assert y0["binding_constraint"] == "irmaa"
    assert y0["recommended_amount"] > 0
    # reference tables were used (no caller injection) -> snapshot says so.
    assert body["snapshot"]["irmaa_table_source"] == "engine_reference"
    assert body["disclaimer"]  # disclaimer attached


def test_sequence_conversions_gateway() -> None:
    r = _client().post("/mcp/tools/sequence_conversions", json={"contract": _ROTH_CONTRACT})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["recommended_by_year"]) == 2
    assert body["total_recommended"] > 0


def test_irmaa_headroom_gateway() -> None:
    r = _client().post(
        "/mcp/tools/irmaa_headroom",
        json={
            "filing_status": "mfj",
            "target_premium_year": 2028,
            "magi_ex_conversion": 150_000,
            "per_person": 2,
            "inflation": 0.03,
            "buffer": 5_000,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_premium_year"] == 2028
    assert body["tiers_source_year"] == 2025
    assert "irmaa_safe_headroom" in body


def test_new_tools_are_listed() -> None:
    tools = _client().get("/mcp/tools").json()["tools"]
    assert "analyze_roth_conversion" in tools
    assert "sequence_conversions" in tools
    assert "irmaa_headroom" in tools


def test_analyze_rejects_identity_in_contract() -> None:
    bad = {"contract": {**_ROTH_CONTRACT, "ssn": "123-45-6789"}}
    r = _client().post("/mcp/tools/analyze_roth_conversion", json=bad)
    assert r.status_code == 400
    assert "identity" in r.text.lower()


def test_analyze_caller_injected_state_rule_is_flagged() -> None:
    body = {
        "contract": _ROTH_CONTRACT,
        "state_rule": {"state_code": "PA", "treatment": "flat", "rate": 0.05},
    }
    r = _client().post("/mcp/tools/analyze_roth_conversion", json=body)
    assert r.status_code == 200, r.text
    assert r.json()["snapshot"]["state_rule_source"] == "caller_provided"
