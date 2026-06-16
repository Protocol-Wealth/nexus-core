# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Unit tests for the deterministic cash-flow + net-worth projection engine."""

from __future__ import annotations

from typing import Any

import pytest

from nexus_core.engine.planning import project_cash_flow
from nexus_core.engine.planning.tax import ordinary_tax


def _project(**overrides: Any) -> dict[str, Any]:
    """A flat-growth accumulation projection; override per test."""
    params: dict[str, Any] = {
        "current_age": 40,
        "retirement_age": 65,
        "terminal_age": 41,  # two rows (ages 40, 41)
        "current_income": 100_000.0,
        "current_expenses": 40_000.0,
        "current_portfolio": 0.0,
        "filing_status": "married_joint",
        "income_growth_rate": 0.0,
        "expense_inflation_rate": 0.0,
        "expected_return": 0.0,
        "retirement_income": 0.0,
        "current_liabilities": 0.0,
    }
    params.update(overrides)
    return project_cash_flow(**params)


def test_structure_and_keys() -> None:
    result = _project(terminal_age=70)
    assert set(result) == {"years", "aggregate", "lifetimeTax", "assumptions"}
    assert len(result["years"]) == 70 - 40 + 1
    row = result["years"][0]
    assert set(row) == {
        "age", "year", "phase", "earnedIncome", "retirementIncome", "income",
        "expenses", "taxes", "netCashFlow", "portfolioBalance", "liabilities", "netWorth",
    }
    assert row["age"] == 40
    assert row["phase"] == "accumulation"


def test_accumulation_exact_arithmetic() -> None:
    # No growth/inflation/return: each working year nets income - tax - expenses,
    # saved into a non-growing portfolio, so it stacks linearly.
    result = _project()
    expected_tax = ordinary_tax(100_000.0, "married_joint")
    assert expected_tax == pytest.approx(7_923.0)
    expected_savings = 100_000.0 - expected_tax - 40_000.0  # 52_077
    y0, y1 = result["years"]
    assert y0["taxes"] == pytest.approx(7_923.0)
    assert y0["netCashFlow"] == pytest.approx(expected_savings)
    assert y0["portfolioBalance"] == pytest.approx(expected_savings)
    # Year 1: prior balance (no growth) + another year's savings.
    assert y1["portfolioBalance"] == pytest.approx(2 * expected_savings)
    assert y1["netWorth"] == pytest.approx(2 * expected_savings)


def test_accumulation_with_return_compounds() -> None:
    # With a positive return the prior balance grows before the new savings land.
    result = _project(expected_return=0.05)
    savings = 100_000.0 - ordinary_tax(100_000.0, "married_joint") - 40_000.0
    y0, y1 = result["years"]
    assert y0["portfolioBalance"] == pytest.approx(savings)  # 0 * 1.05 + savings
    assert y1["portfolioBalance"] == pytest.approx(savings * 1.05 + savings)


def test_liabilities_offset_net_worth() -> None:
    result = _project(current_portfolio=500_000.0, current_liabilities=200_000.0)
    assert result["aggregate"]["startingPortfolio"] == pytest.approx(500_000.0)
    assert result["aggregate"]["startingNetWorth"] == pytest.approx(300_000.0)
    for row in result["years"]:
        assert row["liabilities"] == pytest.approx(200_000.0)
        assert row["netWorth"] == pytest.approx(row["portfolioBalance"] - 200_000.0)


def test_lifetime_tax_rollup() -> None:
    result = _project()
    tax = result["lifetimeTax"]
    assert tax["totalIncome"] == pytest.approx(200_000.0)  # 100k x 2 years
    assert tax["totalTaxesPaid"] == pytest.approx(2 * 7_923.0)
    assert tax["effectiveRate"] == pytest.approx(round((2 * 7_923.0) / 200_000.0, 4))
    # Lifetime taxes equal the sum of the per-year taxes.
    assert tax["totalTaxesPaid"] == pytest.approx(sum(r["taxes"] for r in result["years"]))


def test_already_retired_has_no_earned_income() -> None:
    # retirement_age below current_age => every projected year is retirement.
    result = _project(
        current_age=70, retirement_age=65, terminal_age=73,
        current_income=0.0, retirement_income=20_000.0,
        current_expenses=60_000.0, current_portfolio=500_000.0,
    )
    for row in result["years"]:
        assert row["phase"] == "retirement"
        assert row["earnedIncome"] == 0.0
        assert row["retirementIncome"] > 0.0
        # Guaranteed income < expenses => a funded deficit each year.
        assert row["netCashFlow"] < 0.0
    # The portfolio is drawn down year over year.
    balances = [r["portfolioBalance"] for r in result["years"]]
    assert balances == sorted(balances, reverse=True)


def test_retirement_income_cola_grows() -> None:
    result = _project(
        current_age=66, retirement_age=65, terminal_age=68,
        current_income=0.0, retirement_income=30_000.0,
        current_expenses=20_000.0, current_portfolio=1_000_000.0,
        expense_inflation_rate=0.02,
    )
    incomes = [r["retirementIncome"] for r in result["years"]]
    assert incomes[0] == pytest.approx(30_000.0)
    assert incomes[1] == pytest.approx(30_000.0 * 1.02)
    assert incomes[2] == pytest.approx(30_000.0 * 1.02**2)


def test_deficit_withdrawal_is_grossed_up_for_tax() -> None:
    # A retired year where guaranteed income cannot cover spending: the withdrawal
    # must cover expenses AND the tax on the withdrawal itself.
    result = _project(
        current_age=70, retirement_age=65, terminal_age=71,
        current_income=0.0, retirement_income=20_000.0,
        current_expenses=60_000.0, current_portfolio=2_000_000.0,
        filing_status="single",
    )
    y0 = result["years"][0]
    # netCashFlow = income - tax - expenses is the (negative) deficit, and the
    # portfolio withdrawal that funds it is exactly its magnitude; so the
    # grossed-up identity income + withdrawal - tax == expenses must hold.
    withdrawal = -y0["netCashFlow"]
    assert y0["income"] + withdrawal - y0["taxes"] == pytest.approx(60_000.0, abs=0.05)
    assert y0["taxes"] == pytest.approx(ordinary_tax(y0["income"] + withdrawal, "single"), abs=0.05)


def test_depletion_marks_age_and_floors_at_zero() -> None:
    result = _project(
        current_age=80, retirement_age=65, terminal_age=85,
        current_income=0.0, retirement_income=10_000.0,
        current_expenses=80_000.0, current_portfolio=30_000.0,
        filing_status="single",
    )
    agg = result["aggregate"]
    assert agg["depletionAge"] == 80  # first year's deficit exceeds the portfolio
    assert agg["fundedThroughTerminal"] is False
    assert result["years"][0]["portfolioBalance"] == 0.0
    assert all(r["portfolioBalance"] >= 0.0 for r in result["years"])


def test_funded_through_terminal_true_when_no_depletion() -> None:
    result = _project(current_portfolio=100_000.0, terminal_age=60)
    assert result["aggregate"]["depletionAge"] is None
    assert result["aggregate"]["fundedThroughTerminal"] is True


def test_peak_net_worth_tracked() -> None:
    result = _project(terminal_age=64)  # all accumulation, monotonically rising
    agg = result["aggregate"]
    peak = max(r["netWorth"] for r in result["years"])
    assert agg["peakNetWorth"] == pytest.approx(peak)
    assert agg["peakNetWorthAge"] == result["years"][-1]["age"]


def test_base_year_maps_to_calendar_years() -> None:
    result = _project(terminal_age=43, base_year=2026)
    years = [r["year"] for r in result["years"]]
    assert years == [2026, 2027, 2028, 2029]
    # Without base_year the year is the 0-based index.
    idx = [r["year"] for r in _project(terminal_age=43)["years"]]
    assert idx == [0, 1, 2, 3]


def test_assumptions_echoed() -> None:
    result = _project(income_growth_rate=0.04, expected_return=0.06)
    a = result["assumptions"]
    assert a["filingStatus"] == "married_joint"
    assert a["incomeGrowthRate"] == pytest.approx(0.04)
    assert a["expectedReturn"] == pytest.approx(0.06)
    assert a["retirementIncomeGrowthRate"] == pytest.approx(a["expenseInflationRate"])


def test_determinism() -> None:
    assert _project(terminal_age=60) == _project(terminal_age=60)


@pytest.mark.parametrize(
    "overrides, fragment",
    [
        ({"terminal_age": 40}, "terminal_age must be greater"),
        ({"terminal_age": 39}, "terminal_age must be greater"),
        ({"current_age": -1}, "current_age must be in"),
        ({"current_age": 10, "terminal_age": 200}, "at most"),
        ({"current_income": -5.0}, "current_income must be a non-negative"),
        ({"current_portfolio": -1.0}, "current_portfolio must be a non-negative"),
        ({"expected_return": -1.5}, "expected_return must be a number > -1"),
        ({"filing_status": "joint"}, "filing_status must be one of"),
    ],
)
def test_validation_errors(overrides: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ValueError, match=fragment):
        _project(**overrides)
