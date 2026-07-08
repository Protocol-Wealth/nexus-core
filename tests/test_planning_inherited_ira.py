# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for inherited IRA beneficiary distribution illustrations."""

from __future__ import annotations

import jsonschema
import pytest

from nexus_core.app.planning.contract import PlanningInputError
from nexus_core.app.planning.tools import inherited_ira_analysis_tool
from nexus_core.engine.planning import (
    classify_inherited_ira_beneficiary,
    inherited_ira_analysis,
    inherited_ira_analysis_result_schema,
)


def _run(**overrides: object) -> dict[str, object]:
    args = {
        "inherited_balance": 500_000.0,
        "beneficiary_ordinary_income": 140_000.0,
        "filing_status": "single",
        "tax_year": 2026,
        "years_remaining": 10,
        "annual_return": 0.05,
        "target_rate": 0.24,
    }
    args.update(overrides)
    return inherited_ira_analysis(**args)  # type: ignore[arg-type]


def _strategy(body: dict[str, object], name: str) -> dict[str, object]:
    strategies = body["strategies"]
    assert isinstance(strategies, list)
    found = next(item for item in strategies if item["strategy"] == name)
    assert isinstance(found, dict)
    return found


def test_beneficiary_carveout_classification_by_type_and_age() -> None:
    spouse = classify_inherited_ira_beneficiary(beneficiary_type="spouse")
    assert spouse["eligibleDesignatedBeneficiary"] is True

    implied = classify_inherited_ira_beneficiary(
        beneficiary_type="other_designated_beneficiary",
        beneficiary_age=71,
        decedent_age=80,
    )
    assert implied["beneficiaryType"] == "not_more_than_10_years_younger"
    assert implied["eligibleDesignatedBeneficiary"] is True

    ordinary = classify_inherited_ira_beneficiary(
        beneficiary_type="other_designated_beneficiary",
        beneficiary_age=45,
        decedent_age=80,
    )
    assert ordinary["eligibleDesignatedBeneficiary"] is False
    assert any("10-year" in note for note in ordinary["notes"])


def test_strategies_deplete_account_and_rank_by_after_tax_value() -> None:
    body = _run()
    assert body["taxTableVersion"] == "federal-income-tax-reference-2026-illustrative-v1"
    assert body["beneficiaryClassification"]["eligibleDesignatedBeneficiary"] is False  # type: ignore[index]
    rankings = body["strategyRankings"]
    assert isinstance(rankings, list)
    assert rankings[-1]["strategy"] == "lump_sum"
    assert [row["netAfterTaxReceived"] for row in rankings] == sorted(
        [row["netAfterTaxReceived"] for row in rankings],
        reverse=True,
    )

    for name in ("lump_sum", "equal_annual", "bracket_smoothed"):
        strategy = _strategy(body, name)
        totals = strategy["totals"]
        assert isinstance(totals, dict)
        assert totals["endingBalance"] == 0.0
        assert totals["totalDistributed"] >= 500_000.0
        assert totals["netAfterTaxReceived"] > 0.0


def test_bracket_smoothed_strategy_uses_target_room_when_available() -> None:
    body = _run(beneficiary_ordinary_income=60_000.0, inherited_balance=250_000.0)
    smoothed = _strategy(body, "bracket_smoothed")
    equal = _strategy(body, "equal_annual")
    smoothed_years = smoothed["years"]
    equal_years = equal["years"]
    assert isinstance(smoothed_years, list)
    assert isinstance(equal_years, list)

    # The smoothed strategy fills more of the 24% bracket early, while still
    # ending at zero by year 10.
    assert smoothed_years[0]["distribution"] > equal_years[0]["distribution"]
    assert smoothed["totals"]["endingBalance"] == 0.0  # type: ignore[index]


def test_schema_validates_wire_result() -> None:
    body = _run()
    body["contractVersion"] = "0.1.0"
    jsonschema.validate(instance=body, schema=inherited_ira_analysis_result_schema())


def test_tool_wrapper_happy_path_and_unknown_field_rejection() -> None:
    body = inherited_ira_analysis_tool(
        {
            "contractVersion": "0.1.0",
            "inheritedBalance": 300_000.0,
            "beneficiaryOrdinaryIncome": 90_000.0,
            "beneficiaryOrdinaryIncomeByYear": [90_000.0, 95_000.0],
            "filingStatus": "single",
            "annualReturn": 0.04,
            "beneficiaryType": "other_designated_beneficiary",
        }
    )
    assert body["yearsRemaining"] == 10
    assert body["assumptions"]["taxScope"] == "federal_ordinary_income_only"
    assert "does not calculate separate" in body["assumptions"]["annualRmdScope"]
    assert "disclaimer" in body

    with pytest.raises(PlanningInputError, match="only accepts"):
        inherited_ira_analysis_tool(
            {
                "inheritedBalance": 300_000.0,
                "beneficiaryOrdinaryIncome": 90_000.0,
                "filingStatus": "single",
                "beneficiaryName": "Jane",
            }
        )


def test_tool_wrapper_rejects_unsupported_beneficiary_type() -> None:
    with pytest.raises(PlanningInputError, match="beneficiaryType"):
        inherited_ira_analysis_tool(
            {
                "inheritedBalance": 300_000.0,
                "beneficiaryOrdinaryIncome": 90_000.0,
                "filingStatus": "single",
                "beneficiaryType": "friend",
            }
        )


def test_tool_wrapper_rejects_non_designated_beneficiary_rankings() -> None:
    with pytest.raises(PlanningInputError, match="does not rank non_designated_beneficiary"):
        inherited_ira_analysis_tool(
            {
                "inheritedBalance": 300_000.0,
                "beneficiaryOrdinaryIncome": 90_000.0,
                "filingStatus": "single",
                "beneficiaryType": "non_designated_beneficiary",
            }
        )


def test_tool_wrapper_does_not_default_explicit_zero_years_remaining() -> None:
    with pytest.raises(PlanningInputError, match="years_remaining must be between 1 and 10"):
        inherited_ira_analysis_tool(
            {
                "inheritedBalance": 300_000.0,
                "beneficiaryOrdinaryIncome": 90_000.0,
                "filingStatus": "single",
                "yearsRemaining": 0,
            }
        )
