# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Healthcare and long-term-care stress helpers.

Pure, public-safe planning math over de-identified assumptions only. The helper
accepts ages, dollar amounts, duration, and inflation rates; it deliberately
accepts no diagnosis, provider, claim, policy, account, household, or identity
fields.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LongTermCareShock:
    """A deterministic long-term-care cost event in current-dollar terms.

    ``annual_cost`` is stated in today's dollars. The schedule inflates it by
    ``cost_inflation`` from ``current_age`` through each active shock year.
    """

    onset_age: int
    annual_cost: float
    duration_years: int
    cost_inflation: float


def make_ltc_shock(
    *,
    onset_age: int,
    annual_cost: float,
    duration_years: int,
    cost_inflation: float,
) -> LongTermCareShock:
    """Validate and create a long-term-care stress event."""
    if not isinstance(onset_age, int) or isinstance(onset_age, bool) or not 0 < onset_age <= 130:
        raise ValueError("ltc_shock.onset_age must be an integer age in [1, 130]")
    if (
        isinstance(duration_years, bool)
        or not isinstance(duration_years, int)
        or not 1 <= duration_years <= 40
    ):
        raise ValueError("ltc_shock.duration_years must be an integer in [1, 40]")
    if (
        isinstance(annual_cost, bool)
        or not isinstance(annual_cost, (int, float))
        or not math.isfinite(float(annual_cost))
        or annual_cost < 0.0
    ):
        raise ValueError("ltc_shock.annual_cost must be non-negative")
    if (
        isinstance(cost_inflation, bool)
        or not isinstance(cost_inflation, (int, float))
        or not math.isfinite(float(cost_inflation))
        or cost_inflation <= -1.0
    ):
        raise ValueError("ltc_shock.cost_inflation must be > -1")
    return LongTermCareShock(
        onset_age=onset_age,
        annual_cost=float(annual_cost),
        duration_years=duration_years,
        cost_inflation=float(cost_inflation),
    )


def ltc_shock_cost_by_age(
    shock: LongTermCareShock | None,
    *,
    age: int,
    current_age: int,
) -> float:
    """Nominal shock cost for ``age`` under the current-dollar cost convention."""
    if shock is None:
        return 0.0
    if age < shock.onset_age or age >= shock.onset_age + shock.duration_years:
        return 0.0
    years_from_today = age - current_age
    if years_from_today < 0:
        return 0.0
    return shock.annual_cost * (1.0 + shock.cost_inflation) ** years_from_today


def ltc_shock_schedule(
    shock: LongTermCareShock | None,
    *,
    current_age: int,
    years: int,
) -> list[float]:
    """Nominal LTC costs for each projection year."""
    return [
        ltc_shock_cost_by_age(shock, age=current_age + year, current_age=current_age)
        for year in range(years)
    ]


def ltc_shock_summary(
    shock: LongTermCareShock,
    *,
    current_age: int,
    years: int,
) -> dict[str, Any]:
    """Wire-safe summary for report assumptions and stress-result metadata."""
    costs = ltc_shock_schedule(shock, current_age=current_age, years=years)
    active_years = [
        {
            "projectionYear": index + 1,
            "age": current_age + index,
            "cost": round(cost, 2),
        }
        for index, cost in enumerate(costs)
        if cost > 0.0
    ]
    return {
        "onsetAge": shock.onset_age,
        "annualCostToday": round(shock.annual_cost, 2),
        "durationYears": shock.duration_years,
        "costInflation": round(shock.cost_inflation, 6),
        "annualCostConvention": "current_year_dollars_inflated_to_each_active_age",
        "nominalTotalCost": round(sum(costs), 2),
        "activeYears": active_years,
    }


__all__ = [
    "LongTermCareShock",
    "ltc_shock_cost_by_age",
    "ltc_shock_schedule",
    "ltc_shock_summary",
    "make_ltc_shock",
]
