# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the sequence-of-returns stress engine."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import sequence_of_returns_stress


def test_known_two_year_values() -> None:
    """Hand-computed: $100 start, $10/yr withdrawal, returns {+20%, 0%}.

    worst-first [0.0, 0.2]:  (100-10)*1.0=90,  (90-10)*1.2=96
    best-first  [0.2, 0.0]:  (100-10)*1.2=108, (108-10)*1.0=98
    as-given    [0.2, 0.0]:  same as best-first here = 98
    """
    out = sequence_of_returns_stress(
        initial_balance=100.0,
        net_spend_by_year=[10.0, 10.0],
        annual_returns=[0.2, 0.0],
    )
    assert out["years"] == 2
    assert out["meanAnnualReturn"] == 0.1
    assert out["worstFirst"] == {"terminalBalance": 96.0, "depletedYear": None}
    assert out["bestFirst"] == {"terminalBalance": 98.0, "depletedYear": None}
    assert out["asGiven"] == {"terminalBalance": 98.0, "depletedYear": None}
    assert out["sequenceRiskGap"] == 2.0


def test_no_withdrawals_is_order_invariant() -> None:
    """The defining invariant: with no cashflows, ordering cannot matter.

    Balance is initial * prod(1 + r), which commutes — so every ordering ends
    identically and the sequence-risk gap is exactly zero.
    """
    out = sequence_of_returns_stress(
        initial_balance=100.0,
        net_spend_by_year=[0.0, 0.0, 0.0],
        annual_returns=[0.1, -0.05, 0.2],
    )
    # 100 * 1.1 * 0.95 * 1.2 = 125.4
    assert out["worstFirst"]["terminalBalance"] == 125.4
    assert out["bestFirst"]["terminalBalance"] == 125.4
    assert out["asGiven"]["terminalBalance"] == 125.4
    assert out["sequenceRiskGap"] == 0.0


def test_identical_returns_have_zero_gap() -> None:
    out = sequence_of_returns_stress(
        initial_balance=500_000.0,
        net_spend_by_year=[40_000.0] * 10,
        annual_returns=[0.05] * 10,
    )
    assert out["sequenceRiskGap"] == 0.0
    assert out["worstFirst"] == out["bestFirst"] == out["asGiven"]


def test_best_first_never_worse_than_worst_first() -> None:
    """With withdrawals, best-first ordering can only help vs. worst-first."""
    out = sequence_of_returns_stress(
        initial_balance=1_000_000.0,
        net_spend_by_year=[50_000.0] * 30,
        annual_returns=[(-0.1 if y % 3 == 0 else 0.08) for y in range(30)],
    )
    assert out["bestFirst"]["terminalBalance"] >= out["worstFirst"]["terminalBalance"]
    assert out["sequenceRiskGap"] >= 0.0


def test_worst_first_can_deplete_while_best_first_survives() -> None:
    """$100 start, $50/yr, returns {+50%, -40%} (mean +5%).

    worst-first [-0.4, 0.5]: (100-50)*0.6=30, (30-50)*1.5<0  -> depleted year 1
    best-first  [0.5, -0.4]: (100-50)*1.5=75, (75-50)*0.6=15 -> survives
    """
    out = sequence_of_returns_stress(
        initial_balance=100.0,
        net_spend_by_year=[50.0, 50.0],
        annual_returns=[0.5, -0.4],
    )
    assert out["worstFirst"] == {"terminalBalance": 0.0, "depletedYear": 1}
    assert out["bestFirst"] == {"terminalBalance": 15.0, "depletedYear": None}
    assert out["sequenceRiskGap"] == 15.0


def test_mean_annual_return_is_reported() -> None:
    out = sequence_of_returns_stress(
        initial_balance=100.0,
        net_spend_by_year=[0.0, 0.0, 0.0, 0.0],
        annual_returns=[0.0, 0.10, 0.20, 0.30],
    )
    assert out["meanAnnualReturn"] == 0.15


def test_deterministic_repeat() -> None:
    kwargs = {
        "initial_balance": 750_000.0,
        "net_spend_by_year": [30_000.0] * 20,
        "annual_returns": [0.04 * (1 if y % 2 else -1) for y in range(20)],
    }
    assert sequence_of_returns_stress(**kwargs) == sequence_of_returns_stress(**kwargs)


def test_rejects_empty_returns() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        sequence_of_returns_stress(
            initial_balance=100.0, net_spend_by_year=[], annual_returns=[]
        )


def test_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="same length"):
        sequence_of_returns_stress(
            initial_balance=100.0,
            net_spend_by_year=[10.0, 10.0],
            annual_returns=[0.05],
        )


def test_rejects_non_positive_initial_balance() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        sequence_of_returns_stress(
            initial_balance=0.0, net_spend_by_year=[0.0], annual_returns=[0.05]
        )


def test_rejects_return_at_or_below_negative_one() -> None:
    with pytest.raises(ValueError, match="greater than -1"):
        sequence_of_returns_stress(
            initial_balance=100.0,
            net_spend_by_year=[0.0, 0.0],
            annual_returns=[0.05, -1.0],
        )
