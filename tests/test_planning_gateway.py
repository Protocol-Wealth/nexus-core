# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the planning tool-gateway contract."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.testclient import TestClient

from nexus_core.app.planning import CONTRACT_VERSION, build_planning_router
from nexus_core.app.planning import gateway as planning_gateway
from nexus_core.app.planning.contract import PlanningInfeasibleError, PlanningInputError
from nexus_core.app.planning.tools import _monte_carlo_decumulation_tool, _solve_goal_tool
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


def _planning_router():
    return build_planning_router(market=_FakeMarket(), regime_engine=_FakeRegimeEngine())


def _route_endpoint(path: str) -> Any:
    router = _planning_router()
    return next(route.endpoint for route in router.routes if route.path == path)


def _list_gateway_tools() -> dict[str, Any]:
    endpoint = _route_endpoint("/mcp/tools")
    return endpoint()


class _JsonRequest:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        return self._payload


def _call_gateway_tool(tool_id: str, payload: dict[str, Any]) -> JSONResponse | PlainTextResponse:
    endpoint = _route_endpoint("/mcp/tools/{tool_id}")
    return asyncio.run(endpoint(tool_id, _JsonRequest(payload)))


def _response_json(response: JSONResponse) -> dict[str, Any]:
    return json.loads(response.body)


def _response_text(response: JSONResponse | PlainTextResponse) -> str:
    return response.body.decode()


def test_planning_error_public_messages_are_sanitized() -> None:
    assert PlanningInputError("  field 'age' must be a number  ").public_message == (
        "field 'age' must be a number"
    )
    assert PlanningInputError(
        "Traceback (most recent call last):\n  File \"engine.py\", line 1"
    ).public_message == "invalid planning request"
    assert PlanningInfeasibleError(
        "Traceback (most recent call last):\n  File \"solver.py\", line 1"
    ).public_message == "planning request infeasible"


def test_planning_input_error_response_uses_public_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Request:
        async def json(self) -> dict[str, Any]:
            return {"contractVersion": "0.1.0"}

    def _bad_input(_body: dict[str, Any]) -> dict[str, Any]:
        raise PlanningInputError("Traceback (most recent call last):\n  File \"engine.py\"")

    monkeypatch.setattr(
        planning_gateway,
        "build_tool_handlers",
        lambda *, market, regime_engine: {"bad_input": _bad_input},
    )
    router = planning_gateway.build_planning_router(
        market=_FakeMarket(), regime_engine=_FakeRegimeEngine()
    )
    endpoint = next(route.endpoint for route in router.routes if route.path == "/mcp/tools/{tool_id}")

    response = asyncio.run(endpoint("bad_input", _Request()))

    assert response.status_code == 400
    assert response.body == b"invalid planning request"


def test_internal_engine_error_logs_without_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    class _Request:
        async def json(self) -> dict[str, Any]:
            return {"contractVersion": "0.1.0"}

    def _boom(_body: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("sensitive stack detail")

    monkeypatch.setattr(
        planning_gateway,
        "build_tool_handlers",
        lambda *, market, regime_engine: {"explode": _boom},
    )
    router = planning_gateway.build_planning_router(
        market=_FakeMarket(), regime_engine=_FakeRegimeEngine()
    )
    endpoint = next(route.endpoint for route in router.routes if route.path == "/mcp/tools/{tool_id}")

    with caplog.at_level(logging.WARNING, logger=planning_gateway.__name__):
        response = asyncio.run(endpoint("explode", _Request()))

    assert response.status_code == 500
    assert response.body == b"internal planning engine error"
    records = [record for record in caplog.records if record.name == planning_gateway.__name__]
    assert len(records) == 1
    assert records[0].exc_info is None
    assert "sensitive stack detail" not in records[0].getMessage()
    assert "explode" in records[0].getMessage()


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
    body = _list_gateway_tools()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert len(body["tools"]) == 27
    assert "glide_path" in body["tools"]
    assert "correlation_matrix" in body["tools"]
    assert "capital_market_assumptions" in body["tools"]
    assert "tax_aware_withdrawal" in body["tools"]
    assert "regime_return_generator" in body["tools"]
    assert "monte_carlo_decumulation" in body["tools"]
    assert "solve_goal" in body["tools"]
    assert "roth_conversion" in body["tools"]
    assert "sequence_of_returns_stress" in body["tools"]
    assert "rmd" in body["tools"]
    assert "tax_bracket_headroom" in body["tools"]
    assert "social_security_claiming" in body["tools"]
    assert "regime_conditioned_swr" in body["tools"]
    assert "portfolio_xray" in body["tools"]
    assert "optimize_allocation" in body["tools"]
    assert "build_planning_report" in body["tools"]
    assert "project_cash_flow" in body["tools"]
    assert "fire" in body["tools"]
    assert "risk_metrics" in body["tools"]
    assert "rebalance" in body["tools"]
    assert "cashflow_planning_bridge" in body["tools"]
    assert "cash_reserve_analysis" in body["tools"]
    assert "budget_pacing_projection" in body["tools"]


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


def test_monte_carlo_guardrails_end_to_end() -> None:
    # A guardrails request returns the dynamic-withdrawal fields end-to-end.
    r = _client().post(
        "/mcp/tools/monte_carlo_decumulation",
        json={**_MC_PAYLOAD, "guardrails": {"rule": "guyton_klinger"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["withdrawalRule"] == "guyton_klinger"
    assert set(body["spendingByYear"]) == {"p10", "p50", "p90"}
    assert len(body["spendingByYear"]["p50"]) == 50
    assert set(body["guardrailActivity"]) == {
        "pathsWithCut",
        "pathsWithRaise",
        "band",
        "cut",
        "raise",
    }


def test_monte_carlo_without_guardrails_omits_the_dynamic_fields() -> None:
    body = _client().post("/mcp/tools/monte_carlo_decumulation", json=_MC_PAYLOAD).json()
    assert "withdrawalRule" not in body
    assert "spendingByYear" not in body


def test_monte_carlo_invalid_guardrails_return_400() -> None:
    for bad, match in (
        ({"rule": "vpw"}, "guyton_klinger"),
        ({"band": 1.5}, "band must be in"),
        ({"cut": -0.1}, "raise and guardrails.cut"),
        ({"inflation": float("nan")}, "inflation must be finite"),
        ({"preservationFinalYears": -2}, "preservationFinalYears"),
        ({"freezeAfterLoss": "yes"}, "freezeAfterLoss"),
    ):
        with pytest.raises(PlanningInputError, match=match):
            _monte_carlo_decumulation_tool(
                {**_MC_PAYLOAD, "guardrails": bad}, _FakeMarket(), _FakeRegimeEngine()
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
    assert r.status_code == 200, _response_text(r)
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


def test_rest_planning_alias_matches_legacy_mcp_tools() -> None:
    c = _client()
    assert c.get("/api/planning/tools").json() == c.get("/mcp/tools").json()
    body = {"contractVersion": CONTRACT_VERSION, "age": 73, "balance": 500_000}
    legacy = c.post("/mcp/tools/rmd", json=body)
    rest = c.post("/api/planning/tools/rmd", json=body)
    assert rest.status_code == legacy.status_code == 200
    assert rest.json() == legacy.json()


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


def test_analyze_goals_happy_path() -> None:
    payload = {
        "contractVersion": "0.1.0",
        "goals": [
            {
                "id": "college-1",
                "kind": "education",
                "priority": 1,
                "targetAmount": 200_000,
                "yearsToGoal": 10,
                "currentAssets": 40_000,
                "monthlyContribution": 500,
                "fundingYears": 4,
                "inflationRate": 0.05,
                "expectedReturn": 0.06,
            },
            {
                "id": "home-1",
                "kind": "home",
                "priority": 2,
                "targetAmount": 150_000,
                "yearsToGoal": 5,
            },
        ],
        "sharedFundingPool": {"currentAssets": 50_000, "monthlyContribution": 250},
    }
    r = _client().post("/mcp/tools/analyze_goals", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert len(body["goals"]) == 2
    first = body["goals"][0]
    assert first["id"] == "college-1"  # opaque id echoed; no label in the contract
    assert first["priority"] == 1
    assert first["fundingYears"] == 4
    assert 0.0 <= first["fundedPct"] <= 100.0
    assert first["status"] in {"funded", "on_track", "underfunded"}
    assert body["aggregate"]["goalCount"] == 2
    assert 0.0 <= body["aggregate"]["overallFundedPct"] <= 100.0
    assert body["priorityAllocation"]["mode"] == "priority_ordered_shared_pool"
    assert body["priorityAllocation"]["order"][0] == {
        "id": "college-1",
        "priority": 1,
        "inputOrder": 0,
    }
    assert body["priorityAllocation"]["summary"]["goalCount"] == 2


def test_analyze_goals_bad_target_400() -> None:
    r = _client().post(
        "/mcp/tools/analyze_goals",
        json={
            "contractVersion": "0.1.0",
            "goals": [{"id": "g", "targetAmount": -1, "yearsToGoal": 5}],
        },
    )
    assert r.status_code == 400
    assert "target_amount" in r.text


def test_analyze_goals_empty_list_400() -> None:
    r = _client().post(
        "/mcp/tools/analyze_goals",
        json={"contractVersion": "0.1.0", "goals": []},
    )
    assert r.status_code == 400


def test_project_cash_flow_happy_path() -> None:
    payload = {
        "contractVersion": "0.1.0",
        "currentAge": 45,
        "retirementAge": 65,
        "terminalAge": 90,
        "currentIncome": 180_000,
        "currentExpenses": 90_000,
        "currentPortfolio": 600_000,
        "filingStatus": "married_joint",
        "retirementIncome": 45_000,
        "currentLiabilities": 250_000,
        "baseYear": 2026,
    }
    r = _client().post("/mcp/tools/project_cash_flow", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert len(body["years"]) == 90 - 45 + 1
    first = body["years"][0]
    assert first["age"] == 45
    assert first["year"] == 2026
    assert first["phase"] == "accumulation"
    assert body["aggregate"]["startingNetWorth"] == 600_000 - 250_000
    assert 0.0 <= body["lifetimeTax"]["effectiveRate"] <= 1.0
    assert body["assumptions"]["filingStatus"] == "married_joint"


def test_project_cash_flow_bad_horizon_400() -> None:
    r = _client().post(
        "/mcp/tools/project_cash_flow",
        json={
            "contractVersion": "0.1.0",
            "currentAge": 60,
            "retirementAge": 65,
            "terminalAge": 55,
            "currentIncome": 100_000,
            "currentExpenses": 50_000,
            "currentPortfolio": 100_000,
        },
    )
    assert r.status_code == 400
    assert "terminal_age" in r.text


def test_project_cash_flow_bad_filing_status_400() -> None:
    r = _client().post(
        "/mcp/tools/project_cash_flow",
        json={
            "contractVersion": "0.1.0",
            "currentAge": 40,
            "retirementAge": 65,
            "terminalAge": 90,
            "currentIncome": 100_000,
            "currentExpenses": 50_000,
            "currentPortfolio": 100_000,
            "filingStatus": "joint",
        },
    )
    assert r.status_code == 400
    assert "filing_status" in r.text


def test_cashflow_planning_bridge_gateway() -> None:
    r = _call_gateway_tool(
        "cashflow_planning_bridge",
        {
            "contractVersion": "0.1.0",
            "monthsAnalyzed": 6,
            "averageMonthlySpending": 8_000,
            "essentialMonthlySpending": 5_000,
            "lifestyleMonthlySpending": 3_000,
            "averageMonthlyIncome": 12_000,
            "averageMonthlySavings": 4_000,
            "currentCashReserve": 25_000,
            "targetCashReserveMonths": 6,
            "oneTimeExpenseAdjustment": 500,
            "spendingVolatility": "high",
        },
    )
    assert r.status_code == 200, r.text
    assert isinstance(r, JSONResponse)
    body = _response_json(r)
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["normalizedAnnualSpend"] == 90_000.0
    assert body["cashReserveGap"] == 5_000.0
    assert "spending_volatility_high" in body["planningWarnings"]
    assert "project_cash_flow" in body["recommendedNextTools"]
    assert body["disclaimer"]


def test_cashflow_planning_bridge_bad_volatility_400() -> None:
    r = _call_gateway_tool(
        "cashflow_planning_bridge",
        {
            "monthsAnalyzed": 6,
            "averageMonthlySpending": 8_000,
            "essentialMonthlySpending": 5_000,
            "lifestyleMonthlySpending": 3_000,
            "averageMonthlyIncome": 12_000,
            "averageMonthlySavings": 4_000,
            "currentCashReserve": 25_000,
            "targetCashReserveMonths": 6,
            "spendingVolatility": "extreme",
        },
    )
    assert r.status_code == 400
    assert "spending_volatility" in _response_text(r)


def test_cash_reserve_analysis_gateway() -> None:
    r = _call_gateway_tool(
        "cash_reserve_analysis",
        {
            "monthlyEssentialSpending": 5_000,
            "monthlyTotalSpending": 8_000,
            "currentCashReserve": 35_000,
            "targetMonths": 6,
            "secondaryTargetMonths": 6,
        },
    )
    assert r.status_code == 200, _response_text(r)
    assert isinstance(r, JSONResponse)
    body = _response_json(r)
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["targetReserve"] == 30_000.0
    assert body["gapToSecondaryTarget"] == 13_000.0
    assert body["status"] == "on_track"


def test_cash_reserve_analysis_malformed_input_400() -> None:
    r = _call_gateway_tool(
        "cash_reserve_analysis",
        {
            "monthlyEssentialSpending": 5_000,
            "monthlyTotalSpending": 4_000,
            "currentCashReserve": 35_000,
            "targetMonths": 6,
        },
    )
    assert r.status_code == 400
    assert "monthly_total_spending" in _response_text(r)


def test_budget_pacing_projection_gateway() -> None:
    r = _call_gateway_tool(
        "budget_pacing_projection",
        {
            "monthDay": 15,
            "daysInMonth": 30,
            "monthToDateSpending": 2_700,
            "monthlyBudget": 5_000,
            "recurringRemaining": 250,
            "knownOneTimeRemaining": 125,
        },
    )
    assert r.status_code == 200, _response_text(r)
    assert isinstance(r, JSONResponse)
    body = _response_json(r)
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["projectedMonthEndSpending"] == 5_775.0
    assert body["pacingStatus"] == "over"
    assert body["warningLevel"] == "alert"
    assert "not yet included" in body["assumptions"]["recurringRemainingBasis"]


def test_budget_pacing_projection_invalid_date_400() -> None:
    r = _call_gateway_tool(
        "budget_pacing_projection",
        {
            "monthDay": 31,
            "daysInMonth": 30,
            "monthToDateSpending": 2_700,
            "monthlyBudget": 5_000,
        },
    )
    assert r.status_code == 400
    assert "month_day" in _response_text(r)


@pytest.mark.parametrize(
    ("tool_id", "payload"),
    [
        (
            "cashflow_planning_bridge",
            {
                "monthsAnalyzed": 6,
                "averageMonthlySpending": 8_000,
                "essentialMonthlySpending": 5_000,
                "lifestyleMonthlySpending": 3_000,
                "averageMonthlyIncome": 12_000,
                "averageMonthlySavings": 4_000,
                "currentCashReserve": 25_000,
                "targetCashReserveMonths": 6,
            },
        ),
        (
            "cash_reserve_analysis",
            {
                "monthlyEssentialSpending": 5_000,
                "monthlyTotalSpending": 8_000,
                "currentCashReserve": 35_000,
                "targetMonths": 6,
            },
        ),
        (
            "budget_pacing_projection",
            {
                "monthDay": 15,
                "daysInMonth": 30,
                "monthToDateSpending": 2_700,
                "monthlyBudget": 5_000,
            },
        ),
    ],
)
def test_cashflow_bridge_tools_reject_identity_keys(
    tool_id: str, payload: dict[str, Any]
) -> None:
    r = _call_gateway_tool(tool_id, {**payload, "email": "client@example.com"})
    assert r.status_code == 400
    assert "identity" in _response_text(r).lower()


# ── solve_goal (multi-variable goal solver) ──────────────────────────────────

# A lean base body (fewer paths, deterministic MVN model) so the ~14-iteration
# search stays fast. Seed is pinned by the tool when omitted.
_SOLVE_BASE: dict[str, Any] = {
    "contractVersion": "0.1.0",
    "currentAge": 45,
    "retirementAge": 65,
    "horizonAge": 95,
    "accounts": [
        {"type": "traditional", "balance": 1_200_000, "allocation": {"us_equity": 0.6, "us_bonds": 0.4}},
        {"type": "roth", "balance": 300_000, "allocation": {"us_equity": 0.8, "us_bonds": 0.2}},
    ],
    "assetClasses": [
        {"id": "us_equity", "expectedReturn": 0.07, "volatility": 0.16, "lambda": 0.35},
        {"id": "us_bonds", "expectedReturn": 0.03, "volatility": 0.05, "lambda": 0.10},
    ],
    "correlations": None,
    "annualSpend": 120_000,
    "spendColaRate": 0.025,
    "guaranteedIncome": [
        {"label": "Social Security", "annualAmount": 42_000, "startAge": 67, "colaRate": 0.02}
    ],
    "returnModel": "multivariate_normal",
    "paths": 800,
}


def _solve(**overrides: Any) -> dict[str, Any]:
    return _monte_carlo_free_client_solve({**_SOLVE_BASE, **overrides})


def _monte_carlo_free_client_solve(body: dict[str, Any]) -> dict[str, Any]:
    r = _client().post("/mcp/tools/solve_goal", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_solve_goal_annual_spend_end_to_end() -> None:
    body = _solve(solveFor="annual_spend", targetSuccess=0.80)
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["disclaimer"]  # gateway attaches the MC disclaimer
    assert body["solveFor"] == "annual_spend"
    assert body["targetSuccess"] == 0.80
    assert isinstance(body["feasible"], bool)
    assert body["direction"] == "decreasing"
    assert body["seedUsed"] == 4242421  # the pinned solve seed
    assert body["bounds"]["min"] <= body["solvedValue"] <= body["bounds"]["max"]
    assert 0.0 <= body["achievedSuccess"] <= 1.0
    assert body["pathsSearch"] == 800
    assert body["pathsConfirm"] == 800
    assert set(body["terminalValues"]) == {"p10", "p25", "p50", "p75", "p90"}


def test_solve_goal_success_curve_is_monotone_for_spend() -> None:
    body = _solve(solveFor="annual_spend", targetSuccess=0.75)
    curve = body["successCurve"]
    assert len(curve) >= 2
    xs = [pt["x"] for pt in curve]
    assert xs == sorted(xs)  # sorted by the variable
    probs = [pt["successProbability"] for pt in curve]
    assert probs == sorted(probs, reverse=True)  # spend up -> success down (non-increasing)
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_solve_goal_retirement_age_returns_integer() -> None:
    body = _solve(solveFor="retirement_age", targetSuccess=0.80)
    assert body["direction"] == "increasing"
    assert isinstance(body["solvedValue"], int)
    assert 45 <= body["solvedValue"] <= 95
    assert all(isinstance(pt["x"], int) for pt in body["successCurve"])


def test_solve_goal_contribution_labels_inflow_method() -> None:
    body = _solve(solveFor="annual_contribution", targetSuccess=0.80)
    assert body["direction"] == "increasing"
    assert body["savingsMethod"] == "net_spend_inflow"  # exact in-engine run, not an approximation
    assert body["solvedValue"] >= 0.0


def test_solve_goal_initial_savings_increasing() -> None:
    body = _solve(solveFor="initial_savings", targetSuccess=0.80)
    assert body["direction"] == "increasing"
    assert body["solvedValue"] >= 0.0


def test_solve_goal_savings_rate_requires_income() -> None:
    with pytest.raises(PlanningInputError, match="annualIncome"):
        _solve_goal_tool(
            {**_SOLVE_BASE, "solveFor": "savings_rate", "targetSuccess": 0.80},
            _FakeMarket(),
            _FakeRegimeEngine(),
        )
    # with a positive income it solves a rate in [0, 1]
    body = _solve(solveFor="savings_rate", targetSuccess=0.80, annualIncome=200_000)
    assert body["savingsMethod"] == "net_spend_inflow"
    assert 0.0 <= body["solvedValue"] <= 1.0


def test_solve_goal_infeasible_reports_best_achievable() -> None:
    # A stressed plan (high spend) with an unreachable target — the least spend in
    # bounds ($0) still can't hit 99.9% here; solver reports best-achievable, not raise.
    body = _solve(
        solveFor="annual_spend",
        annualSpend=400_000,
        accounts=[
            {"type": "traditional", "balance": 500_000, "allocation": {"us_equity": 0.9, "us_bonds": 0.1}}
        ],
        targetSuccess=0.999,
        bounds={"min": 350_000, "max": 800_000},
    )
    assert body["feasible"] is False
    assert "bestAchievable" in body
    assert body["bestAchievable"] == body["achievedSuccess"]
    assert body["bestAchievable"] < 0.999


def test_solve_goal_bad_solve_for_400() -> None:
    r = _client().post(
        "/mcp/tools/solve_goal", json={**_SOLVE_BASE, "solveFor": "crystal_ball", "targetSuccess": 0.8}
    )
    assert r.status_code == 400
    assert "solveFor" in r.text


def test_solve_goal_bad_target_400() -> None:
    for bad in (0.0, 1.5, -0.2):
        r = _client().post(
            "/mcp/tools/solve_goal", json={**_SOLVE_BASE, "solveFor": "annual_spend", "targetSuccess": bad}
        )
        assert r.status_code == 400
        assert "targetSuccess" in r.text


def test_solve_goal_bad_retirement_age_bounds_400() -> None:
    with pytest.raises(PlanningInputError, match="retirement_age bounds"):
        _solve_goal_tool(
            {
                **_SOLVE_BASE,
                "solveFor": "retirement_age",
                "targetSuccess": 0.80,
                "bounds": {"min": 40, "max": 70},  # 40 < currentAge 45
            },
            _FakeMarket(),
            _FakeRegimeEngine(),
        )


def test_solve_goal_deterministic() -> None:
    a = _solve(solveFor="annual_spend", targetSuccess=0.80)
    b = _solve(solveFor="annual_spend", targetSuccess=0.80)
    assert a == b  # pinned seed -> identical solve


def test_solve_goal_rejects_invalid_base_body_400() -> None:
    # The base body is still a full MC body — a bad allocation is rejected as usual.
    bad = {
        **_SOLVE_BASE,
        "solveFor": "annual_spend",
        "targetSuccess": 0.80,
        "accounts": [
            {"type": "traditional", "balance": 1000, "allocation": {"us_equity": 0.5, "us_bonds": 0.4}}
        ],
    }
    r = _client().post("/mcp/tools/solve_goal", json=bad)
    assert r.status_code == 400
    assert "sums to" in r.text
