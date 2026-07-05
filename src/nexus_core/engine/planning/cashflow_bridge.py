# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Cash-flow planning bridge calculations (educational).

Public-safe bridge math for turning a private monthly cash-flow close into
de-identified planning assumptions. These functions deliberately take only
derived numbers: no raw transactions, no merchant/payee strings, no account
nicknames, no household records, no notes, and no workflow state.

Pure and deterministic — plain numbers in, plain data out. The private PWOS /
pw-api layer owns ingestion, normalization, rule traces, advisor review, release,
and audit. Nexus Core only receives the resulting aggregates.
"""

from __future__ import annotations

import math
from typing import Any, Literal

SpendingVolatility = Literal["low", "medium", "high"]
ReserveStatus = Literal["underfunded", "on_track", "funded", "overfunded"]
PacingStatus = Literal["under", "on_track", "over"]
WarningLevel = Literal["none", "info", "warn", "alert"]

_MONTHS_PER_YEAR = 12.0
_LOW_SAVINGS_RATE = 0.05
_OVERFUNDED_MULTIPLE = 1.5
_PACING_BAND = 0.05
_ALERT_OVERAGE = 0.15
_VOLATILITY_BANDS: dict[SpendingVolatility, float] = {
    "low": 0.10,
    "medium": 0.20,
    "high": 0.30,
}


def _finite_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _non_negative(value: float, name: str) -> float:
    number = _finite_number(value, name)
    if number < 0.0:
        raise ValueError(f"{name} must be >= 0")
    return number


def _positive(value: float, name: str) -> float:
    number = _finite_number(value, name)
    if number <= 0.0:
        raise ValueError(f"{name} must be > 0")
    return number


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a positive integer")
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _round_money(value: float) -> float:
    return round(value, 2)


def cashflow_planning_bridge(
    *,
    months_analyzed: int,
    average_monthly_spending: float,
    essential_monthly_spending: float,
    lifestyle_monthly_spending: float,
    average_monthly_income: float,
    average_monthly_savings: float,
    current_cash_reserve: float,
    target_cash_reserve_months: float,
    one_time_expense_adjustment: float = 0.0,
    spending_volatility: SpendingVolatility = "medium",
) -> dict[str, Any]:
    """Translate de-identified monthly-close aggregates into planning inputs.

    Args:
        months_analyzed: Number of closed months in the aggregate (> 0).
        average_monthly_spending: Average total monthly spending (>= 0).
        essential_monthly_spending: Essential monthly spending floor (>= 0).
        lifestyle_monthly_spending: Discretionary/lifestyle monthly spending (>= 0).
        average_monthly_income: Average monthly income/inflow (>= 0).
        average_monthly_savings: Average monthly savings; may be negative for a
            deficit month pattern.
        current_cash_reserve: Current cash reserve balance (>= 0).
        target_cash_reserve_months: Essential-spending reserve target in months (> 0).
        one_time_expense_adjustment: One-time monthly adjustment to strip from
            normalized annual spend (>= 0), annualized before subtraction.
        spending_volatility: Monthly spending variability band.

    Returns:
        A PII-free planning bridge envelope with annualized inputs, cash-reserve
        target/gap, retirement spending bands, warnings, recommended next tools,
        and calculation assumptions.
    """
    months = _positive_int(months_analyzed, "months_analyzed")
    monthly_spend = _non_negative(average_monthly_spending, "average_monthly_spending")
    essential_monthly = _non_negative(essential_monthly_spending, "essential_monthly_spending")
    lifestyle_monthly = _non_negative(lifestyle_monthly_spending, "lifestyle_monthly_spending")
    monthly_income = _non_negative(average_monthly_income, "average_monthly_income")
    monthly_savings = _finite_number(average_monthly_savings, "average_monthly_savings")
    reserve = _non_negative(current_cash_reserve, "current_cash_reserve")
    target_months = _positive(target_cash_reserve_months, "target_cash_reserve_months")
    one_time_adjustment = _non_negative(one_time_expense_adjustment, "one_time_expense_adjustment")
    if spending_volatility not in _VOLATILITY_BANDS:
        raise ValueError("spending_volatility must be one of low, medium, high")

    annual_spend = monthly_spend * _MONTHS_PER_YEAR
    annual_one_time_adjustment = one_time_adjustment * _MONTHS_PER_YEAR
    normalized_annual_spend = max(annual_spend - annual_one_time_adjustment, 0.0)
    essential_annual_spend = essential_monthly * _MONTHS_PER_YEAR
    lifestyle_annual_spend = lifestyle_monthly * _MONTHS_PER_YEAR
    annual_income = monthly_income * _MONTHS_PER_YEAR
    annual_savings = monthly_savings * _MONTHS_PER_YEAR
    savings_rate = annual_savings / annual_income if annual_income > 0.0 else 0.0
    reserve_target = essential_monthly * target_months
    reserve_gap = max(reserve_target - reserve, 0.0)
    volatility_band = _VOLATILITY_BANDS[spending_volatility]
    lifestyle_band = {
        "lower": _round_money(max(lifestyle_annual_spend * (1.0 - volatility_band), 0.0)),
        "target": _round_money(lifestyle_annual_spend),
        "upper": _round_money(lifestyle_annual_spend * (1.0 + volatility_band)),
    }

    warnings: list[str] = []
    if reserve_gap > 0.0:
        warnings.append("cash_reserve_underfunded")
    if spending_volatility == "high":
        warnings.append("spending_volatility_high")
    if savings_rate <= 0.0:
        warnings.append("savings_rate_zero_or_negative")
    elif savings_rate < _LOW_SAVINGS_RATE:
        warnings.append("savings_rate_low")
    if one_time_adjustment > 0.0:
        warnings.append("one_time_expense_adjustment_applied")

    return {
        "monthsAnalyzed": months,
        "annualSpend": _round_money(annual_spend),
        "normalizedAnnualSpend": _round_money(normalized_annual_spend),
        "essentialAnnualSpend": _round_money(essential_annual_spend),
        "lifestyleAnnualSpend": _round_money(lifestyle_annual_spend),
        "annualIncome": _round_money(annual_income),
        "annualSavings": _round_money(annual_savings),
        "savingsRate": round(savings_rate, 4),
        "cashReserveTarget": _round_money(reserve_target),
        "cashReserveGap": _round_money(reserve_gap),
        "retirementIncomeFloor": _round_money(essential_annual_spend),
        "retirementLifestyleBand": lifestyle_band,
        "spendingVolatility": spending_volatility,
        "planningWarnings": warnings,
        "recommendedNextTools": [
            "project_cash_flow",
            "analyze_goals",
            "monte_carlo_decumulation",
            "build_planning_report",
        ],
        "assumptions": {
            "annualizationMonths": int(_MONTHS_PER_YEAR),
            "oneTimeExpenseAdjustmentAnnualized": _round_money(annual_one_time_adjustment),
            "cashReserveTargetBasis": "essential_monthly_spending",
            "retirementIncomeFloorBasis": "essential_annual_spending",
            "retirementLifestyleBandBasis": "lifestyle_annual_spending",
            "spendingVolatilityBandPct": round(volatility_band, 4),
        },
    }


def cash_reserve_analysis(
    *,
    monthly_essential_spending: float,
    monthly_total_spending: float,
    current_cash_reserve: float,
    target_months: float,
    secondary_target_months: float | None = None,
) -> dict[str, Any]:
    """Analyze cash reserve coverage against essential and optional total targets.

    The primary target uses essential spending. When supplied, the secondary
    target uses total spending to show a more conservative reserve level.
    """
    essential = _positive(monthly_essential_spending, "monthly_essential_spending")
    total = _positive(monthly_total_spending, "monthly_total_spending")
    if total < essential:
        raise ValueError("monthly_total_spending must be >= monthly_essential_spending")
    reserve = _non_negative(current_cash_reserve, "current_cash_reserve")
    target = _positive(target_months, "target_months")
    secondary_target = (
        _positive(secondary_target_months, "secondary_target_months")
        if secondary_target_months is not None
        else None
    )

    target_reserve = essential * target
    secondary_reserve = total * secondary_target if secondary_target is not None else None
    active_overfund_target = secondary_reserve if secondary_reserve is not None else target_reserve

    if reserve < target_reserve:
        status: ReserveStatus = "underfunded"
    elif secondary_reserve is not None and reserve < secondary_reserve:
        status = "on_track"
    elif reserve > active_overfund_target * _OVERFUNDED_MULTIPLE:
        status = "overfunded"
    else:
        status = "funded"

    return {
        "targetReserve": _round_money(target_reserve),
        "secondaryTargetReserve": (
            _round_money(secondary_reserve) if secondary_reserve is not None else None
        ),
        "currentReserve": _round_money(reserve),
        "gapToTarget": _round_money(max(target_reserve - reserve, 0.0)),
        "gapToSecondaryTarget": (
            _round_money(max(secondary_reserve - reserve, 0.0))
            if secondary_reserve is not None
            else None
        ),
        "monthsCoveredEssential": round(reserve / essential, 2),
        "monthsCoveredTotal": round(reserve / total, 2),
        "status": status,
    }


def budget_pacing_projection(
    *,
    month_day: int,
    days_in_month: int,
    month_to_date_spending: float,
    monthly_budget: float,
    recurring_remaining: float = 0.0,
    known_one_time_remaining: float = 0.0,
) -> dict[str, Any]:
    """Project month-end spending from month-to-date pace and future known items.

    ``recurring_remaining`` and ``known_one_time_remaining`` are added after the
    straight-line pace projection, so they must represent known future spend not
    already included in ``month_to_date_spending``. They are not raw
    transactions; callers aggregate them before invoking this pure function.
    """
    day = _positive_int(month_day, "month_day")
    days = _positive_int(days_in_month, "days_in_month")
    if days > 31:
        raise ValueError("days_in_month must be between 1 and 31")
    if day > days:
        raise ValueError("month_day must be between 1 and days_in_month")
    mtd_spending = _non_negative(month_to_date_spending, "month_to_date_spending")
    budget = _positive(monthly_budget, "monthly_budget")
    recurring = _non_negative(recurring_remaining, "recurring_remaining")
    one_time = _non_negative(known_one_time_remaining, "known_one_time_remaining")

    elapsed_ratio = day / days
    straight_line_projection = mtd_spending / elapsed_ratio
    projected = straight_line_projection + recurring + one_time
    variance = projected - budget
    variance_pct = variance / budget

    if variance_pct < -_PACING_BAND:
        pacing_status: PacingStatus = "under"
        warning_level: WarningLevel = "none"
    elif variance_pct <= _PACING_BAND:
        pacing_status = "on_track"
        warning_level = "none"
    else:
        pacing_status = "over"
        warning_level = "alert" if variance_pct > _ALERT_OVERAGE else "warn"

    return {
        "projectedMonthEndSpending": _round_money(projected),
        "projectedVariance": _round_money(variance),
        "budgetUsedPct": round(mtd_spending / budget, 4),
        "pacingStatus": pacing_status,
        "warningLevel": warning_level,
        "assumptions": {
            "elapsedDay": day,
            "daysInMonth": days,
            "elapsedMonthPct": round(elapsed_ratio, 4),
            "straightLineProjection": _round_money(straight_line_projection),
            "recurringRemaining": _round_money(recurring),
            "recurringRemainingBasis": (
                "known future recurring spend not yet included in month_to_date_spending"
            ),
            "knownOneTimeRemaining": _round_money(one_time),
            "knownOneTimeRemainingBasis": (
                "known future one-time spend not yet included in month_to_date_spending"
            ),
        },
    }


__all__ = [
    "budget_pacing_projection",
    "cash_reserve_analysis",
    "cashflow_planning_bridge",
]
