# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""FIRE / Coast-FIRE accumulation math (educational).

Three numbers, no simulation:

* **FIRE number** — the portfolio that sustains the target spend at the chosen
  safe withdrawal rate (``annualSpend / swr``; the classic 4% rule ⇒ 25× spend).
* **Coast-FIRE number** — the balance needed *today* so that, with **no further
  contributions**, it compounds to the FIRE number by the retirement age. Below
  it you must keep saving; at/above it the existing balance "coasts".
* **Years to FIRE** — when the balance (existing + level contributions, both
  compounding) first reaches the FIRE number.

Pure and deterministic — plain numbers in, plain data out; a single nominal
growth rate (no market data, no tax, no regime). It is a planning illustration,
not a projection of any specific person's outcome, and not investment advice.
"""

from __future__ import annotations

from typing import Any

#: Cap on the year-by-year accumulation search (``yearsToFire`` is null beyond it).
_MAX_YEARS = 100


def fire(
    *,
    current_age: int,
    retirement_age: int,
    current_balance: float,
    annual_contribution: float,
    growth_rate: float,
    annual_spend: float,
    swr: float = 0.04,
) -> dict[str, Any]:
    """FIRE number, Coast-FIRE number, and years/age to financial independence.

    Args:
        current_age: Age today (>= 0).
        retirement_age: Target retirement age (>= ``current_age``).
        current_balance: Invested balance today (>= 0).
        annual_contribution: Level annual contribution while accumulating (>= 0).
        growth_rate: Nominal annual growth rate (> -1), e.g. ``0.06``.
        annual_spend: Target annual retirement spend (> 0), today's dollars.
        swr: Safe withdrawal rate used for the FIRE number (0 < swr < 1).

    Returns:
        ``fireNumber``, ``coastNumber``, ``coastReached`` (bool),
        ``projectedBalanceAtRetirement`` (existing + contributions compounded to
        ``retirement_age``), ``surplusOrGapAtRetirement`` (projected − FIRE; >0 is
        a surplus), ``yearsToFire`` / ``fireAge`` (null if not reached within
        ``_MAX_YEARS``).
    """
    if current_age < 0:
        raise ValueError("current_age must be >= 0")
    if retirement_age < current_age:
        raise ValueError("retirement_age must be >= current_age")
    if current_balance < 0:
        raise ValueError("current_balance must be >= 0")
    if annual_contribution < 0:
        raise ValueError("annual_contribution must be >= 0")
    if growth_rate <= -1:
        raise ValueError("growth_rate must be > -1")
    if annual_spend <= 0:
        raise ValueError("annual_spend must be > 0")
    if not 0 < swr < 1:
        raise ValueError("swr must be in (0, 1)")

    fire_number = annual_spend / swr
    years_to_retire = retirement_age - current_age
    growth_factor = (1.0 + growth_rate) ** years_to_retire
    coast_number = fire_number / growth_factor
    coast_reached = current_balance >= coast_number

    # Future value at retirement: existing balance grown + level contributions
    # (ordinary annuity). Closed form, with the growth_rate == 0 edge case.
    if growth_rate == 0:
        contributions_fv = annual_contribution * years_to_retire
    else:
        contributions_fv = annual_contribution * (growth_factor - 1.0) / growth_rate
    projected_at_retirement = current_balance * growth_factor + contributions_fv
    surplus_or_gap = projected_at_retirement - fire_number

    # Years until the accumulating balance first reaches the FIRE number.
    years_to_fire: int | None = None
    balance = current_balance
    if balance >= fire_number:
        years_to_fire = 0
    else:
        for year in range(1, _MAX_YEARS + 1):
            balance = balance * (1.0 + growth_rate) + annual_contribution
            if balance >= fire_number:
                years_to_fire = year
                break

    return {
        "fireNumber": round(fire_number, 2),
        "coastNumber": round(coast_number, 2),
        "coastReached": coast_reached,
        "projectedBalanceAtRetirement": round(projected_at_retirement, 2),
        "surplusOrGapAtRetirement": round(surplus_or_gap, 2),
        "yearsToFire": years_to_fire,
        "fireAge": current_age + years_to_fire if years_to_fire is not None else None,
    }


__all__ = ["fire"]
