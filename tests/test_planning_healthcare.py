# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for healthcare / long-term-care planning helpers."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import (
    ltc_shock_schedule,
    ltc_shock_summary,
    make_ltc_shock,
)


def test_ltc_shock_schedule_inflates_from_current_age() -> None:
    shock = make_ltc_shock(
        onset_age=80,
        annual_cost=100_000.0,
        duration_years=3,
        cost_inflation=0.04,
    )

    schedule = ltc_shock_schedule(shock, current_age=78, years=6)

    assert schedule[0] == 0.0
    assert schedule[1] == 0.0
    assert round(schedule[2], 2) == 108_160.0
    assert round(schedule[4], 2) == 116_985.86
    assert schedule[5] == 0.0


def test_ltc_shock_summary_is_wire_safe() -> None:
    shock = make_ltc_shock(
        onset_age=80,
        annual_cost=100_000.0,
        duration_years=2,
        cost_inflation=0.04,
    )

    summary = ltc_shock_summary(shock, current_age=79, years=4)

    assert summary["annualCostConvention"] == "current_year_dollars_inflated_to_each_active_age"
    assert summary["nominalTotalCost"] == 212_160.0
    assert [row["age"] for row in summary["activeYears"]] == [80, 81]


def test_ltc_shock_rejects_invalid_duration() -> None:
    with pytest.raises(ValueError, match="duration_years"):
        make_ltc_shock(
            onset_age=80,
            annual_cost=100_000.0,
            duration_years=0,
            cost_inflation=0.04,
        )
