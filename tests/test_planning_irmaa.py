# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for irmaa_headroom — the projected-cliff calculator."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import irmaa_headroom
from nexus_core.engine.planning.tables import IrmaaTable, IrmaaTier


def _table(source_year: int = 2025) -> IrmaaTable:
    # Floors 0 / 100k / 130k; surcharges chosen for round annual numbers.
    return IrmaaTable(
        source_year=source_year,
        filing_status="single",
        tiers=[
            IrmaaTier(0.0, 0.0, 0.0),
            IrmaaTier(100_000.0, 70.0, 14.0),  # annual (70+14)*12 = 1008
            IrmaaTier(130_000.0, 180.0, 35.0),  # annual (180+35)*12 = 2580
        ],
    )


def test_just_under_a_tier_is_safe() -> None:
    out = irmaa_headroom(
        table=_table(), target_premium_year=2025, magi_ex_conversion=95_000.0,
        per_person=1, inflation=0.0, buffer=0.0,
    )
    assert out.current_tier_index == 0
    assert out.current_annual_surcharge == 0.0
    assert out.projected_next_floor == 100_000.0
    assert out.irmaa_safe_headroom == 5_000.0  # 100000 - 0 buffer - 95000
    assert out.cliff_cost_if_crossed == pytest.approx(1008.0)  # tier0 -> tier1 step
    assert out.in_top_tier is False


def test_just_over_a_tier_is_in_the_next_tier() -> None:
    out = irmaa_headroom(
        table=_table(), target_premium_year=2025, magi_ex_conversion=100_001.0,
        per_person=1, inflation=0.0, buffer=0.0,
    )
    assert out.current_tier_index == 1
    assert out.current_annual_surcharge == pytest.approx(1008.0)
    assert out.cliff_cost_if_crossed == pytest.approx(2580.0 - 1008.0)  # step into tier 2


def test_buffer_reduces_headroom() -> None:
    out = irmaa_headroom(
        table=_table(), target_premium_year=2025, magi_ex_conversion=95_000.0,
        per_person=1, inflation=0.0, buffer=2_000.0,
    )
    assert out.irmaa_safe_headroom == 3_000.0  # 100000 - 2000 - 95000
    assert out.buffer == 2_000.0


def test_projection_inflates_and_rounds_floors_to_1k() -> None:
    # Project 2 years forward at 3%: 100000 * 1.03^2 = 106090 -> rounds to 106000.
    out = irmaa_headroom(
        table=_table(source_year=2025), target_premium_year=2027,
        magi_ex_conversion=95_000.0, per_person=1, inflation=0.03, buffer=0.0,
    )
    assert out.tiers_source_year == 2025
    assert out.inflation_assumption == 0.03
    assert out.projected_next_floor == 106_000.0
    assert out.irmaa_safe_headroom == 11_000.0  # 106000 - 95000


def test_per_person_scales_the_surcharge_and_cliff() -> None:
    one = irmaa_headroom(
        table=_table(), target_premium_year=2025, magi_ex_conversion=100_001.0,
        per_person=1, inflation=0.0, buffer=0.0,
    )
    two = irmaa_headroom(
        table=_table(), target_premium_year=2025, magi_ex_conversion=100_001.0,
        per_person=2, inflation=0.0, buffer=0.0,
    )
    assert two.current_annual_surcharge == pytest.approx(2 * one.current_annual_surcharge)
    assert two.cliff_cost_if_crossed == pytest.approx(2 * one.cliff_cost_if_crossed)


def test_top_tier_has_no_upward_cliff() -> None:
    out = irmaa_headroom(
        table=_table(), target_premium_year=2025, magi_ex_conversion=200_000.0,
        per_person=1, inflation=0.0, buffer=0.0,
    )
    assert out.in_top_tier is True
    assert out.projected_next_floor is None
    assert out.irmaa_safe_headroom is None
    assert out.cliff_cost_if_crossed is None
    assert out.current_annual_surcharge == pytest.approx(2580.0)


def test_headroom_clamps_at_zero_when_inside_the_buffer() -> None:
    out = irmaa_headroom(
        table=_table(), target_premium_year=2025, magi_ex_conversion=99_000.0,
        per_person=1, inflation=0.0, buffer=5_000.0,
    )
    # 100000 - 5000 - 99000 = -4000 -> clamped to 0 (any conversion crosses).
    assert out.irmaa_safe_headroom == 0.0


def test_invalid_inputs_raise() -> None:
    with pytest.raises(ValueError, match="inflation"):
        irmaa_headroom(table=_table(), target_premium_year=2027, magi_ex_conversion=1.0,
                       per_person=1, inflation=-1.0, buffer=0.0)
    with pytest.raises(ValueError, match="buffer"):
        irmaa_headroom(table=_table(), target_premium_year=2027, magi_ex_conversion=1.0,
                       per_person=1, inflation=0.03, buffer=-1.0)
    with pytest.raises(ValueError, match="per_person"):
        irmaa_headroom(table=_table(), target_premium_year=2027, magi_ex_conversion=1.0,
                       per_person=-1, inflation=0.03, buffer=0.0)


def test_table_validation() -> None:
    from nexus_core.engine.planning.tables import TableError

    with pytest.raises(TableError, match="base tier"):
        IrmaaTable(source_year=2025, filing_status="single", tiers=[IrmaaTier(50_000.0, 0.0, 0.0)])
    with pytest.raises(TableError, match="ascending"):
        IrmaaTable(
            source_year=2025, filing_status="single",
            tiers=[IrmaaTier(0.0, 0.0, 0.0), IrmaaTier(50_000.0, 1.0, 1.0), IrmaaTier(40_000.0, 2.0, 2.0)],
        )
