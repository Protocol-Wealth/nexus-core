# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the pure monotone goal solver (no market data, synthetic evaluate)."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import (
    SolveResult,
    solve_integer_monotone,
    solve_monotone,
)


def _increasing(x: float) -> float:
    """success rises linearly from 0 at x=0 to 1 at x=100."""
    return x / 100.0


def _decreasing(x: float) -> float:
    """success falls linearly from 1 at x=0 to 0 at x=100."""
    return 1.0 - x / 100.0


def test_increasing_finds_smallest_sufficient_value() -> None:
    r = solve_monotone(
        evaluate=_increasing, lo=0.0, hi=100.0, target=0.80, direction="increasing"
    )
    assert r.feasible is True
    assert r.best_achievable is None
    # smallest x with success >= 0.80 is x = 80 (conservative: rounds toward meeting)
    assert r.solved_value == pytest.approx(80.0, abs=0.05)
    assert r.achieved_success >= 0.80


def test_decreasing_finds_largest_affordable_value() -> None:
    r = solve_monotone(
        evaluate=_decreasing, lo=0.0, hi=100.0, target=0.80, direction="decreasing"
    )
    assert r.feasible is True
    assert r.best_achievable is None
    # largest x still meeting success >= 0.80 is x = 20
    assert r.solved_value == pytest.approx(20.0, abs=0.05)
    assert r.achieved_success >= 0.80


def test_increasing_infeasible_reports_best_achievable_not_raise() -> None:
    # ceiling at hi=100 is only 0.10 — target 0.80 is unreachable in-bounds.
    r = solve_monotone(
        evaluate=lambda x: x / 1000.0, lo=0.0, hi=100.0, target=0.80, direction="increasing"
    )
    assert r.feasible is False
    assert r.solved_value == 100.0  # the best (highest) value in-bounds
    assert r.best_achievable == pytest.approx(0.10, abs=1e-4)
    assert r.achieved_success == pytest.approx(0.10, abs=1e-4)


def test_decreasing_infeasible_when_even_floor_fails() -> None:
    # even x=0 (the min) only reaches 0.30 — target 0.80 unreachable.
    r = solve_monotone(
        evaluate=lambda x: 0.30 - x / 1000.0, lo=0.0, hi=100.0,
        target=0.80, direction="decreasing",
    )
    assert r.feasible is False
    assert r.solved_value == 0.0
    assert r.best_achievable == pytest.approx(0.30, abs=1e-4)


def test_increasing_already_met_at_floor() -> None:
    r = solve_monotone(
        evaluate=lambda x: 0.90 + x / 1000.0, lo=0.0, hi=100.0,
        target=0.80, direction="increasing",
    )
    assert r.feasible is True
    assert r.solved_value == 0.0  # nothing to raise — the floor already clears
    assert r.iterations == 0


def test_decreasing_met_even_at_ceiling() -> None:
    r = solve_monotone(
        evaluate=lambda x: 0.95 - x / 1000.0, lo=0.0, hi=100.0,
        target=0.80, direction="decreasing",
    )
    assert r.feasible is True
    assert r.solved_value == 100.0  # even the max variable still meets the target
    assert r.iterations == 0


def test_success_curve_is_monotone_despite_noise() -> None:
    # A noisy near-monotone evaluate; the reported curve must be clean monotone.
    def noisy(x: float) -> float:
        base = x / 100.0
        wobble = 0.03 * ((int(x) % 3) - 1)  # +/- sampling noise
        return base + wobble

    r = solve_monotone(evaluate=noisy, lo=0.0, hi=100.0, target=0.60, direction="increasing")
    curve = r.success_curve
    assert len(curve) >= 2
    xs = [p.x for p in curve]
    assert xs == sorted(xs)  # sorted by x
    probs = [p.success_probability for p in curve]
    assert probs == sorted(probs)  # non-decreasing for an increasing variable
    assert all(0.0 <= p <= 1.0 for p in probs)


def test_decreasing_curve_is_non_increasing() -> None:
    def noisy(x: float) -> float:
        return (1.0 - x / 100.0) + 0.02 * ((int(x) % 2) - 0.5)

    r = solve_monotone(evaluate=noisy, lo=0.0, hi=100.0, target=0.50, direction="decreasing")
    probs = [p.success_probability for p in r.success_curve]
    assert probs == sorted(probs, reverse=True)  # non-increasing


def test_integer_domain_finds_smallest_integer() -> None:
    # success rises from 0 at age 40 to 1 at age 80; target 0.5 -> age 60.
    r = solve_integer_monotone(
        evaluate=lambda age: (age - 40.0) / 40.0, lo=45, hi=95,
        target=0.50, direction="increasing",
    )
    assert r.feasible is True
    assert r.solved_value == 60.0
    assert float(r.solved_value).is_integer()
    assert all(float(p.x).is_integer() for p in r.success_curve)


def test_integer_domain_infeasible_reports_ceiling() -> None:
    r = solve_integer_monotone(
        evaluate=lambda age: (age - 40.0) / 400.0, lo=45, hi=95,
        target=0.90, direction="increasing",
    )
    assert r.feasible is False
    assert r.solved_value == 95.0
    assert r.best_achievable == pytest.approx((95 - 40) / 400.0, abs=1e-4)


def test_integer_increasing_already_met_at_floor() -> None:
    r = solve_integer_monotone(
        evaluate=lambda age: 0.9, lo=45, hi=95, target=0.80, direction="increasing"
    )
    assert r.feasible is True
    assert r.solved_value == 45.0
    assert r.iterations == 0


def test_integer_decreasing_finds_largest_affordable() -> None:
    # success falls with the variable; largest integer still meeting target.
    r = solve_integer_monotone(
        evaluate=lambda n: 1.0 - n / 100.0, lo=0, hi=100, target=0.70, direction="decreasing"
    )
    assert r.feasible is True
    assert r.solved_value == 30.0  # 1 - 30/100 = 0.70
    assert r.achieved_success >= 0.70
    probs = [p.success_probability for p in r.success_curve]
    assert probs == sorted(probs, reverse=True)  # non-increasing


def test_integer_decreasing_met_even_at_ceiling() -> None:
    r = solve_integer_monotone(
        evaluate=lambda n: 0.95 - n / 1000.0, lo=0, hi=100, target=0.80, direction="decreasing"
    )
    assert r.feasible is True
    assert r.solved_value == 100.0  # even the max integer still clears the target
    assert r.iterations == 0


def test_integer_decreasing_infeasible_when_floor_fails() -> None:
    r = solve_integer_monotone(
        evaluate=lambda n: 0.30 - n / 1000.0, lo=0, hi=100, target=0.80, direction="decreasing"
    )
    assert r.feasible is False
    assert r.solved_value == 0.0
    assert r.best_achievable == pytest.approx(0.30, abs=1e-4)


def test_integer_single_point_domain() -> None:
    r = solve_integer_monotone(
        evaluate=lambda age: 0.9, lo=65, hi=65, target=0.80, direction="increasing"
    )
    assert isinstance(r, SolveResult)
    assert r.feasible is True
    assert r.solved_value == 65.0


def test_determinism_same_inputs_identical_result() -> None:
    a = solve_monotone(
        evaluate=_increasing, lo=0.0, hi=100.0, target=0.72, direction="increasing"
    )
    b = solve_monotone(
        evaluate=_increasing, lo=0.0, hi=100.0, target=0.72, direction="increasing"
    )
    assert a == b


def test_rejects_bad_bounds_and_target() -> None:
    with pytest.raises(ValueError, match="hi must be strictly greater"):
        solve_monotone(evaluate=_increasing, lo=10.0, hi=10.0, target=0.5, direction="increasing")
    with pytest.raises(ValueError, match="target must be in"):
        solve_monotone(evaluate=_increasing, lo=0.0, hi=1.0, target=0.0, direction="increasing")
    with pytest.raises(ValueError, match="target must be in"):
        solve_monotone(evaluate=_increasing, lo=0.0, hi=1.0, target=1.5, direction="increasing")
    with pytest.raises(ValueError, match="hi must be >="):
        solve_integer_monotone(evaluate=_increasing, lo=70, hi=60, target=0.5, direction="increasing")
