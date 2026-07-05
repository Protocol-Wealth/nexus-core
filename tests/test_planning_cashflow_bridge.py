# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for public-safe cash-flow planning bridge calculations."""

from __future__ import annotations

from typing import Any

import pytest

from nexus_core.app.planning.contract import find_identity_keys
from nexus_core.engine.planning import (
    budget_pacing_projection,
    cash_reserve_analysis,
    cashflow_planning_bridge,
)


def _bridge(**overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "months_analyzed": 6,
        "average_monthly_spending": 8_000.0,
        "essential_monthly_spending": 5_000.0,
        "lifestyle_monthly_spending": 3_000.0,
        "average_monthly_income": 12_000.0,
        "average_monthly_savings": 4_000.0,
        "current_cash_reserve": 25_000.0,
        "target_cash_reserve_months": 6.0,
        "one_time_expense_adjustment": 0.0,
        "spending_volatility": "medium",
    }
    params.update(overrides)
    return cashflow_planning_bridge(**params)


def _assert_no_pii_keys(payload: dict[str, Any]) -> None:
    assert find_identity_keys(payload) == []


def test_cashflow_planning_bridge_happy_path() -> None:
    out = _bridge()

    assert out["monthsAnalyzed"] == 6
    assert out["annualSpend"] == 96_000.0
    assert out["normalizedAnnualSpend"] == 96_000.0
    assert out["essentialAnnualSpend"] == 60_000.0
    assert out["lifestyleAnnualSpend"] == 36_000.0
    assert out["annualIncome"] == 144_000.0
    assert out["annualSavings"] == 48_000.0
    assert out["cashReserveTarget"] == 30_000.0
    assert out["cashReserveGap"] == 5_000.0
    assert out["retirementIncomeFloor"] == 60_000.0
    assert out["retirementLifestyleBand"] == {
        "lower": 28_800.0,
        "target": 36_000.0,
        "upper": 43_200.0,
    }
    assert out["recommendedNextTools"] == [
        "project_cash_flow",
        "analyze_goals",
        "monte_carlo_decumulation",
        "build_planning_report",
    ]
    _assert_no_pii_keys(out)


def test_one_time_expense_adjustment_lowers_normalized_annual_spend() -> None:
    out = _bridge(one_time_expense_adjustment=500.0)

    assert out["annualSpend"] == 96_000.0
    assert out["normalizedAnnualSpend"] == 90_000.0
    assert out["assumptions"]["oneTimeExpenseAdjustmentAnnualized"] == 6_000.0
    assert "one_time_expense_adjustment_applied" in out["planningWarnings"]


def test_normalized_annual_spend_floors_at_zero() -> None:
    out = _bridge(average_monthly_spending=1_000.0, one_time_expense_adjustment=2_000.0)

    assert out["annualSpend"] == 12_000.0
    assert out["normalizedAnnualSpend"] == 0.0
    assert "one_time_expense_adjustment_applied" in out["planningWarnings"]


def test_savings_rate_calculation() -> None:
    out = _bridge(average_monthly_income=10_000.0, average_monthly_savings=1_500.0)

    assert out["annualIncome"] == 120_000.0
    assert out["annualSavings"] == 18_000.0
    assert out["savingsRate"] == 0.15
    assert "savings_rate_low" not in out["planningWarnings"]


def test_zero_income_handling() -> None:
    out = _bridge(average_monthly_income=0.0, average_monthly_savings=0.0)

    assert out["annualIncome"] == 0.0
    assert out["savingsRate"] == 0.0
    assert "savings_rate_zero_or_negative" in out["planningWarnings"]


def test_underfunded_cash_reserve_warning() -> None:
    out = _bridge(current_cash_reserve=10_000.0, target_cash_reserve_months=6.0)

    assert out["cashReserveGap"] == 20_000.0
    assert "cash_reserve_underfunded" in out["planningWarnings"]


def test_funded_cash_reserve_has_no_reserve_warning() -> None:
    out = _bridge(current_cash_reserve=30_000.0, target_cash_reserve_months=6.0)

    assert out["cashReserveTarget"] == 30_000.0
    assert out["cashReserveGap"] == 0.0
    assert "cash_reserve_underfunded" not in out["planningWarnings"]


def test_high_volatility_warning() -> None:
    out = _bridge(spending_volatility="high")

    assert out["spendingVolatility"] == "high"
    assert out["retirementLifestyleBand"]["lower"] == 25_200.0
    assert out["retirementLifestyleBand"]["upper"] == 46_800.0
    assert "spending_volatility_high" in out["planningWarnings"]


def test_cash_reserve_underfunded_funded_and_overfunded_cases() -> None:
    underfunded = cash_reserve_analysis(
        monthly_essential_spending=5_000.0,
        monthly_total_spending=8_000.0,
        current_cash_reserve=10_000.0,
        target_months=6.0,
        secondary_target_months=6.0,
    )
    assert underfunded["targetReserve"] == 30_000.0
    assert underfunded["secondaryTargetReserve"] == 48_000.0
    assert underfunded["gapToTarget"] == 20_000.0
    assert underfunded["status"] == "underfunded"

    funded = cash_reserve_analysis(
        monthly_essential_spending=5_000.0,
        monthly_total_spending=8_000.0,
        current_cash_reserve=50_000.0,
        target_months=6.0,
        secondary_target_months=6.0,
    )
    assert funded["gapToTarget"] == 0.0
    assert funded["gapToSecondaryTarget"] == 0.0
    assert funded["monthsCoveredEssential"] == 10.0
    assert funded["monthsCoveredTotal"] == 6.25
    assert funded["status"] == "funded"

    overfunded = cash_reserve_analysis(
        monthly_essential_spending=5_000.0,
        monthly_total_spending=8_000.0,
        current_cash_reserve=80_000.0,
        target_months=6.0,
        secondary_target_months=6.0,
    )
    assert overfunded["status"] == "overfunded"
    _assert_no_pii_keys(overfunded)


def test_cash_reserve_on_track_before_secondary_target() -> None:
    out = cash_reserve_analysis(
        monthly_essential_spending=5_000.0,
        monthly_total_spending=8_000.0,
        current_cash_reserve=35_000.0,
        target_months=6.0,
        secondary_target_months=6.0,
    )

    assert out["gapToTarget"] == 0.0
    assert out["gapToSecondaryTarget"] == 13_000.0
    assert out["status"] == "on_track"


def test_budget_pacing_under_budget() -> None:
    out = budget_pacing_projection(
        month_day=15,
        days_in_month=30,
        month_to_date_spending=2_000.0,
        monthly_budget=5_000.0,
    )

    assert out["projectedMonthEndSpending"] == 4_000.0
    assert out["projectedVariance"] == -1_000.0
    assert out["budgetUsedPct"] == 0.4
    assert out["pacingStatus"] == "under"
    assert out["warningLevel"] == "none"
    _assert_no_pii_keys(out)


def test_budget_pacing_on_track() -> None:
    out = budget_pacing_projection(
        month_day=15,
        days_in_month=30,
        month_to_date_spending=2_500.0,
        monthly_budget=5_000.0,
    )

    assert out["projectedMonthEndSpending"] == 5_000.0
    assert out["projectedVariance"] == 0.0
    assert out["pacingStatus"] == "on_track"
    assert out["warningLevel"] == "none"


def test_budget_pacing_over_budget() -> None:
    out = budget_pacing_projection(
        month_day=10,
        days_in_month=30,
        month_to_date_spending=2_500.0,
        monthly_budget=5_000.0,
        recurring_remaining=500.0,
        known_one_time_remaining=250.0,
    )

    assert out["projectedMonthEndSpending"] == 8_250.0
    assert out["projectedVariance"] == 3_250.0
    assert out["pacingStatus"] == "over"
    assert out["warningLevel"] == "alert"


def test_budget_pacing_over_budget_warns_before_alert_threshold() -> None:
    out = budget_pacing_projection(
        month_day=15,
        days_in_month=30,
        month_to_date_spending=2_700.0,
        monthly_budget=5_000.0,
    )

    assert out["projectedMonthEndSpending"] == 5_400.0
    assert out["projectedVariance"] == 400.0
    assert out["pacingStatus"] == "over"
    assert out["warningLevel"] == "warn"


def test_budget_pacing_remaining_items_document_future_not_yet_included_basis() -> None:
    out = budget_pacing_projection(
        month_day=15,
        days_in_month=30,
        month_to_date_spending=2_500.0,
        monthly_budget=6_000.0,
        recurring_remaining=250.0,
        known_one_time_remaining=125.0,
    )

    assumptions = out["assumptions"]
    assert assumptions["recurringRemaining"] == 250.0
    assert "not yet included" in assumptions["recurringRemainingBasis"]
    assert assumptions["knownOneTimeRemaining"] == 125.0
    assert "not yet included" in assumptions["knownOneTimeRemainingBasis"]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"month_day": 0}, "month_day"),
        ({"month_day": 31, "days_in_month": 30}, "month_day"),
        ({"days_in_month": 32}, "days_in_month"),
    ],
)
def test_budget_pacing_invalid_date_inputs(kwargs: dict[str, Any], match: str) -> None:
    params: dict[str, Any] = {
        "month_day": 15,
        "days_in_month": 30,
        "month_to_date_spending": 2_500.0,
        "monthly_budget": 5_000.0,
    }
    params.update(kwargs)
    with pytest.raises(ValueError, match=match):
        budget_pacing_projection(**params)


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda: _bridge(months_analyzed=0), "months_analyzed"),
        (lambda: _bridge(average_monthly_spending=-1.0), "average_monthly_spending"),
        (lambda: _bridge(current_cash_reserve=-1.0), "current_cash_reserve"),
        (lambda: _bridge(target_cash_reserve_months=0.0), "target_cash_reserve_months"),
        (lambda: _bridge(average_monthly_income=float("nan")), "finite"),
        (lambda: _bridge(spending_volatility="extreme"), "spending_volatility"),
        (
            lambda: cash_reserve_analysis(
                monthly_essential_spending=0.0,
                monthly_total_spending=5_000.0,
                current_cash_reserve=10_000.0,
                target_months=6.0,
            ),
            "monthly_essential_spending",
        ),
        (
            lambda: cash_reserve_analysis(
                monthly_essential_spending=5_000.0,
                monthly_total_spending=4_000.0,
                current_cash_reserve=10_000.0,
                target_months=6.0,
            ),
            "monthly_total_spending",
        ),
        (
            lambda: budget_pacing_projection(
                month_day=15,
                days_in_month=30,
                month_to_date_spending=-1.0,
                monthly_budget=5_000.0,
            ),
            "month_to_date_spending",
        ),
        (
            lambda: budget_pacing_projection(
                month_day=15,
                days_in_month=30,
                month_to_date_spending=1_000.0,
                monthly_budget=float("inf"),
            ),
            "finite",
        ),
    ],
)
def test_invalid_negative_and_non_finite_inputs(call: Any, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        call()
