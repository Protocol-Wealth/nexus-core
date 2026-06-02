# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the FIRE / Coast-FIRE engine."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import fire


def test_zero_growth_hand_values() -> None:
    # 25 years to retirement, no growth: arithmetic is exact.
    out = fire(
        current_age=40,
        retirement_age=65,
        current_balance=500_000,
        annual_contribution=20_000,
        growth_rate=0.0,
        annual_spend=40_000,
        swr=0.04,
    )
    assert out["fireNumber"] == 1_000_000.0  # 40k / 0.04
    assert out["coastNumber"] == 1_000_000.0  # no growth -> coast == FIRE
    assert out["coastReached"] is False  # 500k < 1.0M
    assert out["projectedBalanceAtRetirement"] == 1_000_000.0  # 500k + 20k*25
    assert out["surplusOrGapAtRetirement"] == 0.0
    assert out["yearsToFire"] == 25  # (1.0M - 500k) / 20k
    assert out["fireAge"] == 65


def test_coast_reached_with_growth() -> None:
    # 400k today, no contributions, 6% for 30 years already coasts past 1.5M.
    out = fire(
        current_age=35,
        retirement_age=65,
        current_balance=400_000,
        annual_contribution=0.0,
        growth_rate=0.06,
        annual_spend=60_000,
        swr=0.04,
    )
    assert out["fireNumber"] == 1_500_000.0
    assert out["coastNumber"] == pytest.approx(261_168.9, rel=1e-4)
    assert out["coastReached"] is True
    assert out["projectedBalanceAtRetirement"] == pytest.approx(2_297_396.4, rel=1e-4)
    assert out["surplusOrGapAtRetirement"] > 0
    assert out["yearsToFire"] == 23  # 400k * 1.06^23 first clears 1.5M
    assert out["fireAge"] == 58


def test_never_reaches_returns_null() -> None:
    out = fire(
        current_age=30,
        retirement_age=65,
        current_balance=10_000,
        annual_contribution=0.0,
        growth_rate=0.0,  # stuck at 10k forever
        annual_spend=80_000,
        swr=0.04,
    )
    assert out["fireNumber"] == 2_000_000.0
    assert out["yearsToFire"] is None
    assert out["fireAge"] is None


_BASE = {
    "current_age": 40,
    "retirement_age": 65,
    "current_balance": 1.0,
    "annual_contribution": 1.0,
    "growth_rate": 0.05,
    "annual_spend": 1.0,
    "swr": 0.04,
}


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"current_age": -1}, "current_age"),
        ({"retirement_age": 30}, "retirement_age"),
        ({"current_balance": -1.0}, "current_balance"),
        ({"annual_contribution": -1.0}, "annual_contribution"),
        ({"swr": 0.0}, "swr"),
        ({"growth_rate": -1.5}, "growth_rate"),
        ({"annual_spend": 0.0}, "annual_spend"),
    ],
)
def test_validation(overrides: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        fire(**{**_BASE, **overrides})
