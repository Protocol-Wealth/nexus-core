# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for planning tool wrapper input normalization."""

from __future__ import annotations

import pytest

from nexus_core.app.planning.contract import PlanningInputError
from nexus_core.app.planning.tools import (
    irmaa_headroom_tool,
    project_cash_flow_tool,
    rmd_tool,
    tax_aware_withdrawal_tool,
    tax_bracket_headroom_tool,
)


def test_rmd_tool_accepts_birth_year_policy() -> None:
    out = rmd_tool({"age": 73, "balance": 500_000, "birthYear": 1960})
    assert out["rmdStartAge"] == 75
    assert out["applies"] is False
    assert out["rmdAmount"] == 0.0


def test_tax_aware_withdrawal_tool_accepts_birth_year_policy() -> None:
    out = tax_aware_withdrawal_tool(
        {
            "year": 2026,
            "filingStatus": "single",
            "accounts": [
                {"type": "traditional", "balance": 1_000_000, "allocation": {"x": 1.0}},
                {"type": "taxable", "balance": 500_000, "allocation": {"x": 1.0}},
            ],
            "grossNeed": 10_000,
            "age": 73,
            "birthYear": 1960,
            "otherTaxableIncome": 0,
        }
    )
    assert out["rmdStartAge"] == 75
    assert out["withdrawals"][0]["type"] == "taxable"
    assert out["withdrawals"][0]["gross"] == 10_000
    assert out["taxTableVersion"] == "federal-income-tax-reference-2026-illustrative-v1"


def test_tax_aware_withdrawal_tool_accepts_state_tax_fields() -> None:
    out = tax_aware_withdrawal_tool(
        {
            "year": 2026,
            "filingStatus": "single",
            "accounts": [{"type": "traditional", "balance": 500_000, "allocation": {"x": 1.0}}],
            "grossNeed": 50_000,
            "age": 50,
            "otherTaxableIncome": 0,
            "state": "PA",
            "residencyChange": {"year": 2027, "from": "PA", "to": "FL"},
            "projectionYear": 2026,
        }
    )

    assert out["stateCode"] == "PA"
    assert out["stateTaxModeled"] is True
    assert out["stateTax"] > 0.0
    assert out["withdrawals"][0]["tax"] == pytest.approx(
        out["withdrawals"][0]["federalTax"] + out["withdrawals"][0]["stateTax"]
    )


def test_tax_bracket_headroom_tool_stamps_table_version() -> None:
    out = tax_bracket_headroom_tool(
        {"taxableIncome": 100_000, "filingStatus": "single", "year": 2026}
    )
    assert out["taxTableYear"] == 2026
    assert out["taxTableVersion"] == "federal-income-tax-reference-2026-illustrative-v1"


def test_tax_bracket_headroom_tool_rejects_unregistered_year() -> None:
    with pytest.raises(PlanningInputError, match="no reference federal tax table registered"):
        tax_bracket_headroom_tool(
            {"taxableIncome": 100_000, "filingStatus": "single", "year": 2027}
        )


def test_irmaa_headroom_tool_stamps_table_version() -> None:
    out = irmaa_headroom_tool(
        {
            "filing_status": "single",
            "source_year": 2025,
            "target_premium_year": 2027,
            "magi_ex_conversion": 95_000,
            "per_person": 1,
            "inflation": 0.03,
            "buffer": 0,
        }
    )
    assert out["irmaaTableVersion"] == "irmaa-reference-2025-single-illustrative-v1"


def test_irmaa_headroom_tool_rejects_unregistered_source_year() -> None:
    with pytest.raises(PlanningInputError, match="no reference IRMAA table registered"):
        irmaa_headroom_tool(
            {
                "filing_status": "single",
                "source_year": 2026,
                "target_premium_year": 2028,
                "magi_ex_conversion": 95_000,
                "per_person": 1,
                "inflation": 0.03,
                "buffer": 0,
            }
        )


def test_project_cash_flow_tool_stamps_tax_table_version() -> None:
    out = project_cash_flow_tool(
        {
            "currentAge": 40,
            "retirementAge": 65,
            "terminalAge": 41,
            "currentIncome": 100_000,
            "currentExpenses": 40_000,
            "currentPortfolio": 0,
            "filingStatus": "married_joint",
            "taxYear": 2026,
        }
    )
    assert out["assumptions"]["taxTableVersion"] == (
        "federal-income-tax-reference-2026-illustrative-v1"
    )


def test_project_cash_flow_tool_rejects_unregistered_tax_year() -> None:
    with pytest.raises(PlanningInputError, match="no reference federal tax table registered"):
        project_cash_flow_tool(
            {
                "currentAge": 40,
                "retirementAge": 65,
                "terminalAge": 41,
                "currentIncome": 100_000,
                "currentExpenses": 40_000,
                "currentPortfolio": 0,
                "taxYear": 2027,
            }
        )
