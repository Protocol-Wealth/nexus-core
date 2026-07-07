# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Social Security claiming-age calculator (educational).

Claiming before Full Retirement Age (FRA) permanently reduces the benefit;
delaying past FRA (to age 70) earns delayed-retirement credits. This computes the
benefit at each claim age 62–70 from the Primary Insurance Amount (PIA, the
benefit at FRA) using the SSA reduction / credit formulas, plus the breakeven
ages between the standard claiming strategies.

SSA rules applied (current statutory factors):
- Early: reduced 5/9 of 1% per month for the first 36 months before FRA, then
  5/12 of 1% per month for any additional months (so 30% at 62 when FRA is 67).
- Delayed: increased 2/3 of 1% per month after FRA (8%/year), to age 70 (so 124%
  at 70 when FRA is 67).

Documented simplifications (planning illustration, not advice): nominal dollars
(no COLA, no discounting) for the benefit and breakeven math; no earnings test,
taxation of benefits. Household helpers use simplified spousal/survivor rules
for deterministic planning illustrations. Pure + deterministic.
"""

from __future__ import annotations

from typing import Any, cast

_EARLY_FIRST_36 = 5.0 / 9.0 / 100.0  # per month, first 36 months early
_EARLY_BEYOND_36 = 5.0 / 12.0 / 100.0  # per month, beyond 36 months early
_DELAY_PER_MONTH = 2.0 / 3.0 / 100.0  # per month after FRA (8%/yr)
_SPOUSE_EARLY_FIRST_36 = 25.0 / 36.0 / 100.0  # per month, first 36 months early
_SPOUSE_EARLY_BEYOND_36 = 5.0 / 12.0 / 100.0  # per month, beyond 36 months early
_MIN_CLAIM_AGE = 62
_MAX_CLAIM_AGE = 70


def _benefit_factor(claim_age: int, fra_age: int) -> float:
    """PIA multiplier for claiming at ``claim_age`` given ``fra_age``."""
    if claim_age == fra_age:
        return 1.0
    if claim_age < fra_age:
        months_early = (fra_age - claim_age) * 12
        first = min(months_early, 36) * _EARLY_FIRST_36
        beyond = max(0, months_early - 36) * _EARLY_BEYOND_36
        return 1.0 - (first + beyond)
    months_late = (claim_age - fra_age) * 12
    return 1.0 + months_late * _DELAY_PER_MONTH


def _breakeven_age(
    earlier: int,
    monthly_earlier: float,
    later: int,
    monthly_later: float,
) -> float | None:
    """Age at which cumulative benefits from claiming ``later`` overtake ``earlier``.

    Nominal (no COLA/discount). None when the later claim never catches up.
    """
    if monthly_later <= monthly_earlier:
        return None
    # monthly_e * (T - earlier) == monthly_l * (T - later)  (the ×12 cancels)
    age = (monthly_later * later - monthly_earlier * earlier) / (monthly_later - monthly_earlier)
    return round(age, 1)


def _claim_row(result: dict[str, Any], claim_age: int, field: str) -> dict[str, Any]:
    for row in result["byClaimAge"]:
        if row["claimAge"] == claim_age:
            return cast(dict[str, Any], row)
    raise ValueError(f"{field} must be between {_MIN_CLAIM_AGE} and {_MAX_CLAIM_AGE}")


def spouse_benefit_reduction_factor(*, claim_age: int, fra_age: int) -> float:
    """Return the age-based spouse-benefit factor for whole-year claim ages."""

    if claim_age >= fra_age:
        return 1.0
    months_early = (fra_age - claim_age) * 12
    first = min(months_early, 36)
    beyond = max(0, months_early - 36)
    reduction = first * _SPOUSE_EARLY_FIRST_36 + beyond * _SPOUSE_EARLY_BEYOND_36
    return max(0.0, 1.0 - reduction)


def social_security_claiming(
    *,
    pia_monthly: float,
    fra_age: int = 67,
) -> dict[str, Any]:
    """Benefit by claim age (62–70) + breakeven ages for the standard strategies.

    Args:
        pia_monthly: Primary Insurance Amount — the monthly benefit at FRA (> 0).
        fra_age: Full Retirement Age (62 < fra <= 70; 67 for those born 1960+).

    Returns:
        ``fraAge``, ``pia``, ``byClaimAge`` (per age: ``claimAge``,
        ``monthlyBenefit``, ``annualBenefit``, ``pctOfPia``), and ``breakevens``
        (``earlier`` vs ``later`` crossover ages for 62-vs-FRA, FRA-vs-70,
        62-vs-70).

    Raises:
        ValueError: On a non-positive PIA or an FRA outside (62, 70].
    """
    if pia_monthly <= 0.0:
        raise ValueError("pia_monthly must be positive")
    if not _MIN_CLAIM_AGE < fra_age <= _MAX_CLAIM_AGE:
        raise ValueError("fra_age must be in (62, 70]")

    by_claim_age: list[dict[str, Any]] = []
    monthly_at: dict[int, float] = {}
    for claim_age in range(_MIN_CLAIM_AGE, _MAX_CLAIM_AGE + 1):
        factor = _benefit_factor(claim_age, fra_age)
        monthly = pia_monthly * factor
        monthly_at[claim_age] = monthly
        by_claim_age.append(
            {
                "claimAge": claim_age,
                "monthlyBenefit": round(monthly, 2),
                "annualBenefit": round(monthly * 12.0, 2),
                "pctOfPia": round(factor, 4),
            }
        )

    pairs = [(_MIN_CLAIM_AGE, fra_age), (fra_age, _MAX_CLAIM_AGE), (_MIN_CLAIM_AGE, _MAX_CLAIM_AGE)]
    breakevens = [
        {
            "earlier": a,
            "later": b,
            "breakevenAge": _breakeven_age(a, monthly_at[a], b, monthly_at[b]),
        }
        for a, b in pairs
        if a < b
    ]

    return {
        "fraAge": fra_age,
        "pia": round(pia_monthly, 2),
        "byClaimAge": by_claim_age,
        "breakevens": breakevens,
    }


def household_social_security_benefits(
    *,
    primary_pia_monthly: float,
    spouse_pia_monthly: float,
    primary_claim_age: int,
    spouse_claim_age: int,
    primary_fra_age: int = 67,
    spouse_fra_age: int = 67,
    spousal_rate: float = 0.5,
) -> dict[str, Any]:
    """Simplified two-person Social Security benefit snapshot.

    The helper is intentionally deterministic and PII-free. It computes each
    worker's own claimed benefit, a spouse benefit of up to ``spousal_rate`` of
    the primary worker's PIA reduced when the spouse claims before FRA, the
    household benefit while both are receiving benefits, and survivor monthly
    amounts if either worker dies. It does not model earnings tests, deemed
    filing, GPO/WEP, divorced spouse rules, or child-in-care rules.
    """

    if not 0.0 <= spousal_rate <= 1.0:
        raise ValueError("spousal_rate must be in [0, 1]")
    primary = social_security_claiming(pia_monthly=primary_pia_monthly, fra_age=primary_fra_age)
    spouse = social_security_claiming(pia_monthly=spouse_pia_monthly, fra_age=spouse_fra_age)
    primary_row = _claim_row(primary, primary_claim_age, "primary_claim_age")
    spouse_row = _claim_row(spouse, spouse_claim_age, "spouse_claim_age")
    primary_own = float(primary_row["monthlyBenefit"])
    spouse_own = float(spouse_row["monthlyBenefit"])
    spouse_factor = spouse_benefit_reduction_factor(
        claim_age=spouse_claim_age,
        fra_age=spouse_fra_age,
    )
    spouse_spousal = primary_pia_monthly * spousal_rate * spouse_factor
    spouse_payable = max(spouse_own, spouse_spousal)
    survivor_if_primary_dies = max(spouse_own, primary_own)
    survivor_if_spouse_dies = max(primary_own, spouse_own)
    return {
        "primary": {
            "claimAge": primary_claim_age,
            "fraAge": primary_fra_age,
            "ownMonthlyBenefit": round(primary_own, 2),
        },
        "spouse": {
            "claimAge": spouse_claim_age,
            "fraAge": spouse_fra_age,
            "ownMonthlyBenefit": round(spouse_own, 2),
            "spousalReductionFactor": round(spouse_factor, 6),
            "spousalMonthlyBenefit": round(spouse_spousal, 2),
            "payableMonthlyBenefit": round(spouse_payable, 2),
        },
        "householdMonthlyBenefit": round(primary_own + spouse_payable, 2),
        "survivorIfPrimaryDiesMonthlyBenefit": round(survivor_if_primary_dies, 2),
        "survivorIfSpouseDiesMonthlyBenefit": round(survivor_if_spouse_dies, 2),
        "notes": [
            "Simplified household Social Security illustration; not an SSA benefit determination.",
            "Spousal benefit is modeled as the larger of spouse own benefit or age-reduced 50% of primary PIA.",
            "Survivor benefit is modeled as the larger of the survivor's own benefit or the deceased worker's own claimed benefit.",
        ],
    }


__all__ = [
    "household_social_security_benefits",
    "social_security_claiming",
    "spouse_benefit_reduction_factor",
]
