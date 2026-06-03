# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""IRMAA headroom — room before the next Medicare income-surcharge cliff.

IRMAA (the Income-Related Monthly Adjustment Amount) raises Medicare Part B + D
premiums once MAGI crosses a tier floor. Two facts make it the binding constraint
for a 60-something Roth conversion, ahead of the tax bracket:

1. **It is a cliff, not a ramp.** One dollar over a floor applies the *entire*
   tier's surcharge for the whole year, per beneficiary.
2. **It runs on a two-year MAGI lookback.** A conversion in calendar year N drives
   premiums in year N+2. CMS does not publish the N+2 tier floors until ~late
   N+1, so a forward-looking plan must **project** them.

This function therefore projects the target-year (N+2) tier floors from the
latest published tiers + an inflation assumption, finds where the
before-conversion MAGI sits, and reports the safe headroom **net of a buffer**
held below the projected next floor (because the projection is an estimate). It
returns the projection inputs (source year, inflation, buffer) so the caller can
snapshot them into a signed record.

Pure + deterministic; no I/O. Educational scenario analysis only, not tax advice.
"""

from __future__ import annotations

from .analysis import IrmaaHeadroom
from .tables import IrmaaTable


def _project_floor(floor: float, factor: float) -> float:
    """Inflate a tier floor and round to the nearest $1,000 (CMS convention)."""
    if floor <= 0.0:
        return 0.0
    return round(floor * factor / 1000.0) * 1000.0


def irmaa_headroom(
    *,
    table: IrmaaTable,
    target_premium_year: int,
    magi_ex_conversion: float,
    per_person: int,
    inflation: float,
    buffer: float,
) -> IrmaaHeadroom:
    """Room before the next projected IRMAA cliff in ``target_premium_year``.

    Args:
        table: Ascending IRMAA tiers + their published ``source_year`` (injected,
            snapshot-able; see :mod:`.tables`).
        target_premium_year: The premium year the surcharge would apply to —
            i.e. ``conversion_year + 2`` (the two-year MAGI lookback).
        magi_ex_conversion: MAGI for the conversion year, **before** any
            conversion (AGI + tax-exempt interest).
        per_person: Number of Medicare beneficiaries the surcharge applies to in
            the target year (IRMAA is per beneficiary).
        inflation: Annual assumption used to project the source-year floors
            forward to the target year (decimal, > -1).
        buffer: Dollars held below the projected next floor as a safety margin
            against the projection (>= 0).

    Returns:
        An :class:`IrmaaHeadroom`. ``irmaa_safe_headroom`` /
        ``projected_next_floor`` / ``cliff_cost_if_crossed`` are ``None`` when the
        MAGI is already in the top tier (IRMAA no longer binds upward).

    Raises:
        ValueError: On ``inflation <= -1``, ``buffer < 0``, or ``per_person < 0``.
    """
    if inflation <= -1.0:
        raise ValueError("inflation must be greater than -1")
    if buffer < 0.0:
        raise ValueError("buffer must be non-negative")
    if per_person < 0:
        raise ValueError("per_person must be non-negative")

    years_forward = max(0, target_premium_year - table.source_year)
    factor = (1.0 + inflation) ** years_forward
    projected = [_project_floor(t.magi_floor, factor) for t in table.tiers]

    # Current tier = the highest tier whose projected floor the MAGI clears.
    current_index = 0
    for i, floor in enumerate(projected):
        if magi_ex_conversion >= floor:
            current_index = i
        else:
            break

    current_tier = table.tiers[current_index]
    current_surcharge = round(current_tier.annual_surcharge_per_person * per_person, 2)
    in_top_tier = current_index == len(table.tiers) - 1

    next_floor: float | None = None
    headroom: float | None = None
    cliff_cost: float | None = None
    if not in_top_tier:
        next_floor = projected[current_index + 1]
        next_tier = table.tiers[current_index + 1]
        step = next_tier.annual_surcharge_per_person - current_tier.annual_surcharge_per_person
        cliff_cost = round(step * per_person, 2)
        headroom = round(max(0.0, next_floor - buffer - magi_ex_conversion), 2)

    return IrmaaHeadroom(
        target_premium_year=target_premium_year,
        tiers_source_year=table.source_year,
        inflation_assumption=inflation,
        buffer=buffer,
        per_person=per_person,
        current_tier_index=current_index,
        in_top_tier=in_top_tier,
        projected_current_floor=projected[current_index],
        projected_next_floor=next_floor,
        irmaa_safe_headroom=headroom,
        current_annual_surcharge=current_surcharge,
        cliff_cost_if_crossed=cliff_cost,
    )


__all__ = ["irmaa_headroom"]
