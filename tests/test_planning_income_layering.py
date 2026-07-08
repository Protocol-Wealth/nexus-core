# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the income-layering planning tool."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from nexus_core.app.planning import build_planning_router
from nexus_core.data.providers import PriceBar
from nexus_core.engine.planning import (
    IncomeStream,
    SocialSecurityIncome,
    StateResidencyChange,
    income_layering,
    income_layering_result_schema,
    project_cash_flow,
)


class _FakeMarket:
    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        return []


class _FakeRegime:
    def classify(self) -> SimpleNamespace:
        return SimpleNamespace(regime="GROWTH", confidence_score=80)


class _JsonRequest:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        return self._payload


def _call_gateway_tool(tool_id: str, payload: dict[str, Any]) -> tuple[int, Any]:
    app = FastAPI()
    router = build_planning_router(market=_FakeMarket(), regime_engine=_FakeRegime())
    app.include_router(router)
    endpoint = next(
        route.endpoint for route in router.routes if route.path == "/mcp/tools/{tool_id}"
    )
    response = asyncio.run(endpoint(tool_id, _JsonRequest(payload)))
    body = response.body.decode()
    if isinstance(response, JSONResponse):
        return response.status_code, json.loads(body)
    return response.status_code, body


def _sources(row: dict[str, Any]) -> list[str]:
    return [layer["source"] for layer in row["layers"]]


def test_social_security_claim_age_changes_layer_amount() -> None:
    early = income_layering(
        current_age=70,
        terminal_age=71,
        spending_target=0.0,
        social_security=SocialSecurityIncome(pia_monthly=2_000.0, claim_age=62),
    )
    delayed = income_layering(
        current_age=70,
        terminal_age=71,
        spending_target=0.0,
        social_security=SocialSecurityIncome(pia_monthly=2_000.0, claim_age=70),
    )

    early_ss = next(
        layer for layer in early["years"][0]["layers"] if layer["source"] == "social_security"
    )
    delayed_ss = next(
        layer for layer in delayed["years"][0]["layers"] if layer["source"] == "social_security"
    )
    assert delayed_ss["gross"] > early_ss["gross"]
    assert early_ss["tax"] == 0.0
    assert delayed_ss["tax"] == 0.0
    assert delayed["assumptions"]["socialSecurityClaimAge"] == 70


def test_rmd_layer_precedes_discretionary_withdrawals() -> None:
    result = income_layering(
        current_age=75,
        terminal_age=76,
        spending_target=80_000.0,
        filing_status="single",
        account_balances={"taxable": 0.0, "traditional": 1_000_000.0, "roth": 0.0},
        account_returns={"taxable": 0.0, "traditional": 0.0, "roth": 0.0},
        birth_year=1951,
    )

    first = result["years"][0]
    sources = _sources(first)
    assert "rmd" in sources
    assert "traditional_withdrawal" in sources
    assert sources.index("rmd") < sources.index("traditional_withdrawal")
    rmd_layer = next(layer for layer in first["layers"] if layer["source"] == "rmd")
    assert rmd_layer["gross"] == pytest.approx(round(1_000_000.0 / 24.6, 2), abs=0.02)
    assert result["rollups"]["rmdStartAgePolicyVersion"] == "secure2.0-goodfaith-73-per-89FR58644"


def test_rmd_withdrawal_increases_taxable_social_security() -> None:
    result = income_layering(
        current_age=75,
        terminal_age=76,
        spending_target=0.0,
        filing_status="single",
        social_security=SocialSecurityIncome(pia_monthly=2_500.0, claim_age=67),
        account_balances={"taxable": 0.0, "traditional": 1_000_000.0, "roth": 0.0},
        account_returns={"taxable": 0.0, "traditional": 0.0, "roth": 0.0},
        birth_year=1951,
    )

    first = result["years"][0]
    ss_layer = next(layer for layer in first["layers"] if layer["source"] == "social_security")
    rmd_layer = next(layer for layer in first["layers"] if layer["source"] == "rmd")
    assert rmd_layer["gross"] > 40_000.0
    assert ss_layer["tax"] > 0.0
    assert first["totalTax"] > 5_000.0


def test_household_social_security_survivor_step_down_and_filing_status() -> None:
    result = income_layering(
        current_age=67,
        terminal_age=70,
        spending_target=0.0,
        filing_status="married_joint",
        base_year=2026,
        social_security=SocialSecurityIncome(pia_monthly=3_000.0, claim_age=67),
        spouse_social_security=SocialSecurityIncome(pia_monthly=800.0, claim_age=67),
        survivor_year=2028,
        survivor_filing_status="single",
    )

    first_ss = next(
        layer for layer in result["years"][0]["layers"] if layer["source"] == "social_security"
    )
    survivor_ss = next(
        layer for layer in result["years"][2]["layers"] if layer["source"] == "social_security"
    )
    assert first_ss["gross"] == pytest.approx(54_000.0)
    assert survivor_ss["gross"] == pytest.approx(36_000.0)
    assert result["years"][0]["filingStatus"] == "married_joint"
    assert result["years"][2]["filingStatus"] == "single"
    assert result["years"][2]["survivorActive"] is True


def test_survivor_year_uses_tax_year_when_base_year_is_omitted() -> None:
    result = income_layering(
        current_age=67,
        terminal_age=70,
        spending_target=0.0,
        filing_status="married_joint",
        tax_year=2026,
        social_security=SocialSecurityIncome(pia_monthly=3_000.0, claim_age=67),
        spouse_social_security=SocialSecurityIncome(pia_monthly=800.0, claim_age=67),
        survivor_year=2028,
        survivor_filing_status="single",
    )

    survivor_ss = next(
        layer for layer in result["years"][2]["layers"] if layer["source"] == "social_security"
    )
    assert result["years"][2]["year"] == 2
    assert survivor_ss["gross"] == pytest.approx(36_000.0)
    assert result["years"][2]["filingStatus"] == "single"
    assert result["years"][2]["survivorActive"] is True


def test_survivor_single_filing_status_increases_tax_vs_joint() -> None:
    common = {
        "current_age": 67,
        "terminal_age": 70,
        "spending_target": 0.0,
        "filing_status": "married_joint",
        "base_year": 2026,
        "income_streams": (IncomeStream("pension", 150_000.0, 67),),
        "social_security": SocialSecurityIncome(pia_monthly=3_000.0, claim_age=67),
        "spouse_social_security": SocialSecurityIncome(pia_monthly=800.0, claim_age=67),
        "survivor_year": 2028,
    }
    single = income_layering(**common, survivor_filing_status="single")
    joint = income_layering(**common, survivor_filing_status="married_joint")

    assert single["years"][2]["totalTax"] > joint["years"][2]["totalTax"]


def test_state_tax_layers_pa_excludes_retirement_income() -> None:
    pa = income_layering(
        current_age=65,
        terminal_age=66,
        spending_target=0.0,
        filing_status="single",
        income_streams=(IncomeStream("pension", 60_000.0, 65),),
        state="PA",
        base_year=2026,
    )
    va = income_layering(
        current_age=65,
        terminal_age=66,
        spending_target=0.0,
        filing_status="single",
        income_streams=(IncomeStream("pension", 60_000.0, 65),),
        state="VA",
        base_year=2026,
    )

    assert pa["years"][0]["stateCode"] == "PA"
    assert pa["years"][0]["stateTaxModeled"] is True
    assert pa["years"][0]["stateTax"] == 0.0
    assert va["years"][0]["stateCode"] == "VA"
    assert va["years"][0]["stateTax"] > 0.0
    assert va["rollups"]["totalTax"] == pytest.approx(
        va["rollups"]["totalFederalTax"] + va["rollups"]["totalStateTax"]
    )


def test_state_tax_residency_change_switches_income_layering_year() -> None:
    result = income_layering(
        current_age=50,
        terminal_age=51,
        spending_target=50_000.0,
        filing_status="single",
        tax_year=2026,
        base_year=2026,
        account_balances={"taxable": 0.0, "traditional": 200_000.0, "roth": 0.0},
        account_returns={"taxable": 0.0, "traditional": 0.0, "roth": 0.0},
        state="PA",
        residency_change=StateResidencyChange(year=2027, from_state="PA", to_state="FL"),
    )

    first, second = result["years"]
    assert first["stateCode"] == "PA"
    assert first["stateTax"] > 0.0
    assert second["stateCode"] == "FL"
    assert second["stateTax"] == 0.0


def test_state_tax_gross_up_prevents_artificial_gap() -> None:
    result = income_layering(
        current_age=50,
        terminal_age=51,
        spending_target=50_000.0,
        filing_status="single",
        tax_year=2026,
        base_year=2026,
        account_balances={"taxable": 0.0, "traditional": 250_000.0, "roth": 0.0},
        account_returns={"taxable": 0.0, "traditional": 0.0, "roth": 0.0},
        state="VA",
    )

    first = result["years"][0]
    assert first["stateTax"] > 0.0
    assert first["gap"] == pytest.approx(0.0, abs=1.0)
    assert first["netIncome"] >= first["spendingTarget"] - 1.0


def test_bracket_fill_adds_optional_traditional_layer() -> None:
    base = income_layering(
        current_age=65,
        terminal_age=66,
        spending_target=20_000.0,
        filing_status="single",
        income_streams=(IncomeStream("pension", 50_000.0, 65),),
        account_balances={"taxable": 0.0, "traditional": 500_000.0, "roth": 0.0},
        account_returns={"taxable": 0.0, "traditional": 0.0, "roth": 0.0},
    )
    filled = income_layering(
        current_age=65,
        terminal_age=66,
        spending_target=20_000.0,
        filing_status="single",
        income_streams=(IncomeStream("pension", 50_000.0, 65),),
        account_balances={"taxable": 0.0, "traditional": 500_000.0, "roth": 0.0},
        account_returns={"taxable": 0.0, "traditional": 0.0, "roth": 0.0},
        bracket_fill_target_rate=0.12,
    )

    assert "bracket_fill" not in _sources(base["years"][0])
    assert "bracket_fill" in _sources(filled["years"][0])
    assert (
        filled["rollups"]["endingAccountBalances"]["traditional"]
        < base["rollups"]["endingAccountBalances"]["traditional"]
    )


def test_bracket_fill_accounts_for_social_security_torpedo() -> None:
    filled = income_layering(
        current_age=67,
        terminal_age=68,
        spending_target=0.0,
        filing_status="single",
        social_security=SocialSecurityIncome(pia_monthly=2_500.0, claim_age=67),
        account_balances={"taxable": 0.0, "traditional": 500_000.0, "roth": 0.0},
        account_returns={"taxable": 0.0, "traditional": 0.0, "roth": 0.0},
        bracket_fill_target_rate=0.12,
    )

    first = filled["years"][0]
    assert "bracket_fill" in _sources(first)
    ss_layer = next(layer for layer in first["layers"] if layer["source"] == "social_security")
    assert ss_layer["tax"] > 0.0


def test_degenerate_case_reconciles_with_cash_flow_projection() -> None:
    common = {
        "current_age": 65,
        "retirement_age": 65,
        "terminal_age": 68,
        "filing_status": "single",
        "tax_year": 2026,
        "expected_return": 0.0,
        "account_balances": {"taxable": 0.0, "traditional": 500_000.0, "roth": 0.0},
        "account_returns": {"taxable": 0.0, "traditional": 0.0, "roth": 0.0},
    }
    cash_flow = project_cash_flow(
        **common,
        current_income=0.0,
        current_expenses=60_000.0,
        current_portfolio=500_000.0,
        retirement_income=20_000.0,
        early_withdrawal_penalty_rate=0.0,
    )
    layered = income_layering(
        **common,
        spending_target=60_000.0,
        income_streams=(IncomeStream("pension", 20_000.0, 65, cola_rate=0.025),),
        birth_year=1960,
    )

    for cf_row, il_row in zip(cash_flow["years"], layered["years"], strict=True):
        cf_withdrawals = sum(cf_row["withdrawalsByAccount"].values())
        assert il_row["totalGross"] == pytest.approx(cf_row["income"] + cf_withdrawals, abs=1.0)
        assert il_row["totalTax"] == pytest.approx(cf_row["taxes"], abs=1.0)
        assert sum(il_row["endingAccountBalances"].values()) == pytest.approx(
            cf_row["portfolioBalance"], abs=5.0
        )


def test_income_layering_gateway_happy_path_and_disclaimer() -> None:
    status, body = _call_gateway_tool(
        "income_layering",
        {
            "currentAge": 64,
            "terminalAge": 67,
            "retirementAge": 65,
            "earnedIncome": 120_000,
            "spendingTarget": 70_000,
            "filingStatus": "single",
            "socialSecurity": {"piaMonthly": 2_000, "claimAge": 67},
            "incomeStreams": [{"kind": "pension", "annualAmount": 12_000, "startAge": 65}],
            "accountBalances": {"taxable": 50_000, "traditional": 250_000, "roth": 25_000},
            "accountReturns": {"taxable": 0.03, "traditional": 0.03, "roth": 0.03},
            "baseYear": 2026,
        },
    )

    assert status == 200
    assert body["contractVersion"] == "0.1.0"
    assert body["years"][0]["year"] == 2026
    assert body["assumptions"]["withdrawalOrder"] == ["rmd", "taxable", "traditional", "roth"]
    assert body["assumptions"]["taxTableSource"].startswith("IRS Rev. Proc.")
    assert body["assumptions"]["taxTableLastVerified"] == "2026-07-08"
    assert "not predictions" in body["disclaimer"]


def test_income_layering_gateway_accepts_state_and_residency_change() -> None:
    status, body = _call_gateway_tool(
        "income_layering",
        {
            "currentAge": 50,
            "terminalAge": 51,
            "spendingTarget": 50_000,
            "filingStatus": "single",
            "taxYear": 2026,
            "baseYear": 2026,
            "accountBalances": {"taxable": 0, "traditional": 200_000, "roth": 0},
            "accountReturns": {"taxable": 0, "traditional": 0, "roth": 0},
            "state": "PA",
            "residencyChange": {"year": 2027, "from": "PA", "to": "FL"},
        },
    )

    assert status == 200
    assert body["years"][0]["stateCode"] == "PA"
    assert body["years"][0]["stateTax"] > 0.0
    assert body["years"][1]["stateCode"] == "FL"
    assert body["years"][1]["stateTax"] == 0.0
    assert body["assumptions"]["residencyChange"] == {"year": 2027, "from": "PA", "to": "FL"}


def test_income_layering_gateway_accepts_spouse_and_survivor_fields() -> None:
    status, body = _call_gateway_tool(
        "income_layering",
        {
            "currentAge": 67,
            "terminalAge": 70,
            "spendingTarget": 0,
            "filingStatus": "married_joint",
            "baseYear": 2026,
            "socialSecurity": {"piaMonthly": 3_000, "claimAge": 67},
            "spouseSocialSecurity": {"piaMonthly": 800, "claimAge": 67},
            "survivorYear": 2028,
            "survivorFilingStatus": "single",
        },
    )

    assert status == 200
    assert body["years"][2]["survivorActive"] is True
    assert body["years"][2]["filingStatus"] == "single"
    assert body["assumptions"]["spouseSocialSecurityClaimAge"] == 67
    assert body["assumptions"]["survivorYear"] == 2028


def test_income_layering_gateway_rejects_stream_labels() -> None:
    status, body = _call_gateway_tool(
        "income_layering",
        {
            "currentAge": 65,
            "terminalAge": 66,
            "spendingTarget": 60_000,
            "incomeStreams": [
                {
                    "kind": "pension",
                    "label": "Former employer pension",
                    "annualAmount": 20_000,
                    "startAge": 65,
                }
            ],
        },
    )

    assert status == 400
    assert "only accepts" in body


def test_income_layering_gateway_rejects_unknown_top_level_fields() -> None:
    status, body = _call_gateway_tool(
        "income_layering",
        {
            "currentAge": 65,
            "terminalAge": 66,
            "spendingTarget": 60_000,
            "clientName": "Nick",
        },
    )

    assert status == 400
    assert "income_layering only accepts" in body


def test_income_layering_gateway_rejects_extra_residency_change_fields() -> None:
    status, body = _call_gateway_tool(
        "income_layering",
        {
            "currentAge": 65,
            "terminalAge": 66,
            "spendingTarget": 60_000,
            "state": "PA",
            "residencyChange": {
                "year": 2027,
                "from": "PA",
                "to": "FL",
                "address": "123 Main St",
            },
        },
    )

    assert status == 400
    assert "identity fields are not accepted" in body


def test_income_layering_gateway_rejects_spouse_identity_fields() -> None:
    status, body = _call_gateway_tool(
        "income_layering",
        {
            "currentAge": 67,
            "terminalAge": 68,
            "spendingTarget": 0,
            "socialSecurity": {"piaMonthly": 3_000, "claimAge": 67},
            "spouseSocialSecurity": {"piaMonthly": 800, "claimAge": 67, "name": "Spouse"},
        },
    )

    assert status == 400
    assert "identity fields are not accepted" in body


def test_income_layering_gateway_rejects_explicit_invalid_fra_age() -> None:
    status, body = _call_gateway_tool(
        "income_layering",
        {
            "currentAge": 65,
            "terminalAge": 66,
            "spendingTarget": 60_000,
            "socialSecurity": {"piaMonthly": 2_000, "claimAge": 67, "fraAge": 0},
        },
    )

    assert status == 400
    assert "fra_age" in body


def test_income_layering_schema_exposes_wire_shape() -> None:
    schema = income_layering_result_schema()

    assert schema["title"] == "IncomeLayeringResult"
    assert schema["$id"].endswith("income-layering-result-0.1.3.json")
    assert "years" in schema["properties"]
    assert "rollups" in schema["properties"]
    layer_props = schema["properties"]["years"]["items"]["properties"]["layers"]["items"][
        "properties"
    ]
    assert "source" in layer_props
    assert "stateTax" in schema["properties"]["years"]["items"]["properties"]
    assert "stateTaxTableSource" in schema["properties"]["years"]["items"]["properties"]
    assert "taxTableSource" in schema["properties"]["assumptions"]["properties"]
    assert "residencyChange" in schema["properties"]["assumptions"]["properties"]
    assert "survivorActive" in schema["properties"]["years"]["items"]["properties"]
    assert "spouseSocialSecurityClaimAge" in schema["properties"]["assumptions"]["properties"]
