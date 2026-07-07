# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the education-funding planning tools."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI

from nexus_core.app.planning import build_planning_router
from nexus_core.data.providers import PriceBar
from nexus_core.engine.planning import (
    EducationStudentCase,
    education_cost_fv,
    education_funding,
    education_funding_result_schema,
    education_savings_need,
    education_savings_projection,
    education_vehicle_rules_result_schema,
    reference_education_vehicle_rules,
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
    if response.media_type == "application/json":
        return response.status_code, json.loads(body)
    return response.status_code, body


def test_education_cost_schedule_goal_start_values() -> None:
    result = education_cost_fv(
        annual_cost=50_000.0,
        tuition_inflation=0.05,
        years_until_start=10,
        funding_years=4,
    )

    first = 50_000.0 * 1.05**10
    assert result.first_year_cost == pytest.approx(round(first, 2))
    assert [row.years_from_now for row in result.cost_schedule] == [10, 11, 12, 13]
    assert {row.cost_at_goal_start for row in result.cost_schedule} == {round(first, 2)}
    assert result.total_cost_at_goal_start == pytest.approx(round(first * 4, 2))


def test_education_savings_closed_form_round_trip() -> None:
    target = 240_000.0
    current = 25_000.0
    annual_return = 0.055
    years = 12

    need = education_savings_need(
        target_fv=target,
        current_savings=current,
        after_tax_return=annual_return,
        years_until_start=years,
    )
    projection = education_savings_projection(
        current_savings=current,
        monthly_contribution=need.monthly,
        after_tax_return=annual_return,
        years=years,
    )

    assert projection.future_value == pytest.approx(target, abs=1.25)
    assert need.annual == pytest.approx(round(need.monthly * 12.0, 2))
    assert need.lump_sum < target


def test_education_savings_need_immediate_goal_reports_gap_once() -> None:
    need = education_savings_need(
        target_fv=40_000.0,
        current_savings=10_000.0,
        after_tax_return=0.05,
        years_until_start=0,
    )

    assert need.monthly == 30_000.0
    assert need.annual == 30_000.0
    assert need.lump_sum == 30_000.0


def test_education_funding_multi_student_totals() -> None:
    result = education_funding(
        students=[
            EducationStudentCase("student-1", 35_000.0, 6, 4, current_savings=10_000.0),
            EducationStudentCase("student-2", 25_000.0, 9, 2, monthly_contribution=200.0),
        ],
        tuition_inflation=0.04,
        after_tax_return=0.05,
    )

    assert [student.subject_ref for student in result.students] == ["student-1", "student-2"]
    assert result.household_totals["totalCostAtGoalStart"] == pytest.approx(
        round(sum(student.cost.total_cost_at_goal_start for student in result.students), 2)
    )
    assert result.household_totals["savingsNeed"]["monthly"] == pytest.approx(
        round(sum(student.savings_need.monthly for student in result.students), 2)
    )


def test_education_funding_rejects_identity_shaped_subject_ref() -> None:
    with pytest.raises(ValueError, match="opaque token"):
        education_funding(
            students=[EducationStudentCase("Jane Student", 35_000.0, 6, 4)],
            tuition_inflation=0.04,
            after_tax_return=0.05,
        )


def test_reference_education_vehicle_rules_2026() -> None:
    rules = reference_education_vehicle_rules(2026)
    by_vehicle = {rule.vehicle: rule for rule in rules}

    assert set(by_vehicle) == {"529", "coverdell_esa", "ugma_utma"}
    assert by_vehicle["529"].annual_gift_exclusion == 19_000.0
    assert by_vehicle["529"].five_year_superfunding_single == 95_000.0
    assert by_vehicle["coverdell_esa"].contribution_limit == 2_000.0
    assert by_vehicle["coverdell_esa"].magi_phaseout_single == (95_000.0, 110_000.0)


def test_education_funding_tool_happy_path_and_disclaimer() -> None:
    status, body = _call_gateway_tool(
        "education_funding",
        {
            "students": [
                {
                    "subjectRef": "student-1",
                    "annualCost": 45_000,
                    "yearsUntilStart": 8,
                    "fundingYears": 4,
                    "currentSavings": 15_000,
                    "monthlyContribution": 500,
                }
            ],
            "tuitionInflation": 0.05,
            "afterTaxReturn": 0.055,
        },
    )

    assert status == 200
    assert body["students"][0]["subjectRef"] == "student-1"
    assert body["students"][0]["cost"]["fundingYears"] == 4
    assert len(body["students"][0]["cost"]["costSchedule"]) == 4
    assert body["householdTotals"]["savingsNeed"]["monthly"] > 0
    assert "not predictions" in body["disclaimer"]


def test_education_vehicle_rules_tool_happy_path() -> None:
    status, body = _call_gateway_tool("education_vehicle_rules", {"taxYear": 2026})

    assert status == 200
    assert body["taxYear"] == 2026
    assert body["tableVersion"].startswith("education-vehicle-reference-2026")
    assert [rule["vehicle"] for rule in body["rules"]] == [
        "529",
        "coverdell_esa",
        "ugma_utma",
    ]


def test_education_result_schemas_expose_wire_shapes() -> None:
    funding_schema = education_funding_result_schema()
    rules_schema = education_vehicle_rules_result_schema()

    assert funding_schema["title"] == "EducationFundingResult"
    assert "householdTotals" in funding_schema["properties"]
    student_props = funding_schema["properties"]["students"]["items"]["properties"]
    assert "subjectRef" in student_props
    assert rules_schema["title"] == "EducationVehicleRulesResult"
    rule_props = rules_schema["properties"]["rules"]["items"]["properties"]
    assert "fiveYearSuperfundingSingle" in rule_props


def test_education_gateway_rejects_identity_keys() -> None:
    status, body = _call_gateway_tool(
        "education_funding",
        {
            "students": [
                {
                    "name": "Jane Student",
                    "annualCost": 45_000,
                    "yearsUntilStart": 8,
                    "fundingYears": 4,
                }
            ],
            "tuitionInflation": 0.05,
            "afterTaxReturn": 0.055,
        },
    )

    assert status == 400
    assert "identity fields are not accepted" in body


def test_education_gateway_rejects_subject_ref_with_identity_shape() -> None:
    status, body = _call_gateway_tool(
        "education_funding",
        {
            "students": [
                {
                    "subjectRef": "Jane Student",
                    "annualCost": 45_000,
                    "yearsUntilStart": 8,
                    "fundingYears": 4,
                }
            ],
            "tuitionInflation": 0.05,
            "afterTaxReturn": 0.055,
        },
    )

    assert status == 400
    assert "opaque token" in body
