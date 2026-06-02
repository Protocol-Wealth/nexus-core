# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the covered-call ladder + roll analytics."""

from __future__ import annotations

import pytest

from nexus_core.engine.pricing.overwrite import (
    LadderLeg,
    covered_call_ladder,
    roll_analysis,
)


def test_ladder_aggregates_hand_values() -> None:
    out = covered_call_ladder(
        spot=100_000,
        settlement="inverse",
        total_coins=10.0,
        legs=[
            LadderLeg(expiry_days=30, strike=120_000, coins=4.0, premium=0.02),
            LadderLeg(expiry_days=60, strike=130_000, coins=3.0, premium=0.03),
        ],
    )
    assert out.overwritten_coins == 7.0
    assert out.coverage_pct == 70.0  # 7 / 10
    assert out.total_premium_usd == 17_000.0  # 8000 + 9000
    assert out.total_coin_income == pytest.approx(0.17)  # 0.08 + 0.09
    # coins-weighted annualized: (4·24.333 + 3·18.25) / 7
    assert out.blended_annualized_yield_pct == pytest.approx(21.726, rel=1e-3)
    # coins-weighted distance: (4·20 + 3·30) / 7
    assert out.weighted_distance_to_strike_pct == pytest.approx(170 / 7, rel=1e-6)
    assert out.nearest_expiry_days == 30
    assert out.farthest_expiry_days == 60
    assert len(out.legs) == 2


def test_ladder_flags_overwrite_beyond_treasury() -> None:
    out = covered_call_ladder(
        spot=100_000,
        settlement="inverse",
        total_coins=5.0,
        legs=[
            LadderLeg(expiry_days=30, strike=120_000, coins=4.0, premium=0.02),
            LadderLeg(expiry_days=60, strike=130_000, coins=3.0, premium=0.03),
        ],
    )
    assert out.overwritten_coins == 7.0
    assert out.coverage_pct == 140.0
    assert any("over-written" in n for n in out.notes)


def test_roll_up_and_out_net_debit() -> None:
    out = roll_analysis(
        spot=100_000,
        settlement="inverse",
        coins=2.0,
        current_strike=110_000,
        current_expiry_days=5,
        current_entry_premium=0.03,
        current_close_premium=0.05,
        new_strike=120_000,
        new_expiry_days=35,
        new_open_premium=0.04,
    )
    assert out.roll_type == "roll up and out"
    assert out.close_cost_usd == 10_000.0  # 0.05 × 100k × 2
    assert out.open_credit_usd == 8_000.0  # 0.04 × 100k × 2
    assert out.realized_pnl_usd == -4_000.0  # 6000 entry − 10000 close
    assert out.net_credit_usd == -2_000.0  # 8000 − 10000
    assert out.net_credit_coin == pytest.approx(-0.01)  # (−2000/2) / 100k
    assert out.new_call.strike == 120_000
    assert any("debit" in n.lower() for n in out.notes)


def test_roll_type_labels() -> None:
    common = {
        "spot": 100_000.0,
        "settlement": "inverse",
        "coins": 1.0,
        "current_strike": 110_000.0,
        "current_expiry_days": 30,
        "current_entry_premium": 0.03,
        "current_close_premium": 0.02,
        "new_open_premium": 0.03,
    }
    # Same strike, later expiry -> pure calendar roll out.
    out = roll_analysis(**common, new_strike=110_000, new_expiry_days=60)
    assert out.roll_type == "roll out"
    # Lower strike, same expiry -> roll down.
    out = roll_analysis(**common, new_strike=100_000, new_expiry_days=30)
    assert out.roll_type == "roll down"
