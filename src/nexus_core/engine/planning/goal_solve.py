# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Monotone goal solver — the multi-variable "what makes this goal succeed" core.

Pure, deterministic, engine-agnostic bisection over a single scalar decision
variable against a target success probability, given an INJECTED ``evaluate``
callback (variable value -> success probability in ``[0, 1]``) plus the direction
of monotonicity. The solver never touches market data or a Monte Carlo engine —
the caller closes ``evaluate`` over whatever simulation it wants (the planning
tool closes it over an in-process decumulation run with a pinned seed) — so this
module unit-tests against a synthetic monotone function with zero I/O.

Two domains:

- :func:`solve_monotone` — a continuous (float) variable (annual spend, annual
  contribution, initial savings): bisection to a domain tolerance.
- :func:`solve_integer_monotone` — an integer variable (retirement age): integer
  bisection over ``[lo, hi]``.

Feasibility is *reported*, never raised. When the target sits above the
achievable ceiling within the bounds, ``feasible`` is ``False`` and
``best_achievable`` carries the maximum success reachable in-bounds (so the
caller can say "the best this plan can do is 74%"). The returned
``success_curve`` is a monotonicity-enforced list of ``(x, success_probability)``
samples across the searched domain — the "what-if" curve a planning UI renders.

Educational scenario analysis only — not advice.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

#: Whether success rises with the variable (contribution / retirement-age /
#: initial-savings) or falls with it (annual spend). Drives which bound is the
#: achievable ceiling and which side of the target the solved value is taken from.
Direction = Literal["increasing", "decreasing"]

#: An injected candidate-value -> success-probability evaluator. Must be
#: (approximately) monotone in the declared ``Direction`` for the bisection to
#: converge; the caller pins any simulation seed so the curve is smooth.
Evaluate = Callable[[float], float]

_DEFAULT_ITERATIONS = 24
_DEFAULT_INT_ITERATIONS = 40


@dataclass(frozen=True)
class SolvePoint:
    """One sampled point on the success curve."""

    x: float
    success_probability: float


@dataclass(frozen=True)
class SolveResult:
    """Structured solver outcome (see the module docstring)."""

    feasible: bool
    solved_value: float
    achieved_success: float
    target_success: float
    direction: Direction
    iterations: int
    best_achievable: float | None
    success_curve: tuple[SolvePoint, ...]


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _build_curve(
    samples: dict[float, float], *, direction: Direction
) -> tuple[SolvePoint, ...]:
    """Sort the evaluated samples by x and enforce monotonicity in ``direction``.

    With a pinned simulation seed the raw samples are already (near-)monotone; the
    running-extreme envelope removes any residual sampling noise so the reported
    curve is a clean monotone what-if, as the contract promises.
    """
    running: float | None = None
    curve: list[SolvePoint] = []
    for x, raw in sorted(samples.items()):
        s = _clamp01(raw)
        if running is None:
            running = s
        elif direction == "increasing":
            running = max(running, s)
        else:
            running = min(running, s)
        curve.append(SolvePoint(x=float(x), success_probability=round(running, 4)))
    return tuple(curve)


def _result(
    *,
    feasible: bool,
    solved_value: float,
    achieved: float,
    target: float,
    direction: Direction,
    iterations: int,
    best: float | None,
    samples: dict[float, float],
) -> SolveResult:
    return SolveResult(
        feasible=feasible,
        solved_value=float(solved_value),
        achieved_success=round(_clamp01(achieved), 4),
        target_success=target,
        direction=direction,
        iterations=iterations,
        best_achievable=None if best is None else round(_clamp01(best), 4),
        success_curve=_build_curve(samples, direction=direction),
    )


def solve_monotone(
    *,
    evaluate: Evaluate,
    lo: float,
    hi: float,
    target: float,
    direction: Direction,
    iterations: int = _DEFAULT_ITERATIONS,
    tolerance: float | None = None,
) -> SolveResult:
    """Bisect a continuous monotone variable to ``target`` success.

    ``evaluate`` maps a candidate value to a success probability; ``direction``
    declares whether success rises or falls as the variable rises. Returns the
    boundary value that just meets ``target`` — the largest affordable value for a
    ``decreasing`` variable (spend), the smallest sufficient value for an
    ``increasing`` one (savings / initial balance) — or, when ``target`` is above
    the achievable ceiling within ``[lo, hi]``, ``feasible=False`` plus the
    ceiling in ``best_achievable`` (never raises).
    """
    if not hi > lo:
        raise ValueError("hi must be strictly greater than lo")
    if not 0.0 < target <= 1.0:
        raise ValueError("target must be in (0, 1]")
    tol = tolerance if tolerance is not None else max((hi - lo) * 1e-4, 1e-9)

    samples: dict[float, float] = {}

    def ev(x: float) -> float:
        xf = float(x)
        cached = samples.get(xf)
        if cached is None:
            cached = _clamp01(evaluate(xf))
            samples[xf] = cached
        return cached

    s_lo = ev(lo)
    s_hi = ev(hi)
    iters = 0

    if direction == "increasing":
        # The ceiling is at hi (the maximum variable -> the maximum success).
        if s_lo >= target:  # already met at the floor — nothing to raise
            return _result(
                feasible=True, solved_value=lo, achieved=s_lo, target=target,
                direction=direction, iterations=iters, best=None, samples=samples,
            )
        if s_hi < target:  # even the ceiling can't reach the target
            return _result(
                feasible=False, solved_value=hi, achieved=s_hi, target=target,
                direction=direction, iterations=iters, best=s_hi, samples=samples,
            )
        lo_x, hi_x = lo, hi  # invariant: ev(lo_x) < target <= ev(hi_x)
        while hi_x - lo_x > tol and iters < iterations:
            iters += 1
            mid = 0.5 * (lo_x + hi_x)
            if ev(mid) >= target:
                hi_x = mid
            else:
                lo_x = mid
        return _result(
            feasible=True, solved_value=hi_x, achieved=ev(hi_x), target=target,
            direction=direction, iterations=iters, best=None, samples=samples,
        )

    # decreasing: the ceiling is at lo (the minimum variable -> the maximum success).
    if s_hi >= target:  # even the ceiling of the variable still meets the target
        return _result(
            feasible=True, solved_value=hi, achieved=s_hi, target=target,
            direction=direction, iterations=iters, best=None, samples=samples,
        )
    if s_lo < target:  # even the minimum variable can't reach the target
        return _result(
            feasible=False, solved_value=lo, achieved=s_lo, target=target,
            direction=direction, iterations=iters, best=s_lo, samples=samples,
        )
    lo_x, hi_x = lo, hi  # invariant: ev(lo_x) >= target > ev(hi_x)
    while hi_x - lo_x > tol and iters < iterations:
        iters += 1
        mid = 0.5 * (lo_x + hi_x)
        if ev(mid) >= target:
            lo_x = mid
        else:
            hi_x = mid
    return _result(
        feasible=True, solved_value=lo_x, achieved=ev(lo_x), target=target,
        direction=direction, iterations=iters, best=None, samples=samples,
    )


def solve_integer_monotone(
    *,
    evaluate: Evaluate,
    lo: int,
    hi: int,
    target: float,
    direction: Direction,
    iterations: int = _DEFAULT_INT_ITERATIONS,
) -> SolveResult:
    """Integer-domain sibling of :func:`solve_monotone` (e.g. retirement age).

    Bisects the integer interval ``[lo, hi]`` — returning the smallest sufficient
    integer for an ``increasing`` variable (retire-later raises success) or the
    largest affordable integer for a ``decreasing`` one — with the same
    report-not-raise feasibility contract.
    """
    if hi < lo:
        raise ValueError("hi must be >= lo")
    if not 0.0 < target <= 1.0:
        raise ValueError("target must be in (0, 1]")

    samples: dict[float, float] = {}

    def ev(x: int) -> float:
        xf = float(x)
        cached = samples.get(xf)
        if cached is None:
            cached = _clamp01(evaluate(xf))
            samples[xf] = cached
        return cached

    s_lo = ev(lo)
    if lo == hi:
        feasible = s_lo >= target
        return _result(
            feasible=feasible, solved_value=lo, achieved=s_lo, target=target,
            direction=direction, iterations=0, best=None if feasible else s_lo,
            samples=samples,
        )
    s_hi = ev(hi)
    iters = 0

    if direction == "increasing":
        if s_lo >= target:
            return _result(
                feasible=True, solved_value=lo, achieved=s_lo, target=target,
                direction=direction, iterations=iters, best=None, samples=samples,
            )
        if s_hi < target:
            return _result(
                feasible=False, solved_value=hi, achieved=s_hi, target=target,
                direction=direction, iterations=iters, best=s_hi, samples=samples,
            )
        lo_i, hi_i = lo, hi  # invariant: ev(lo_i) < target <= ev(hi_i)
        while hi_i - lo_i > 1 and iters < iterations:
            iters += 1
            mid = (lo_i + hi_i) // 2
            if ev(mid) >= target:
                hi_i = mid
            else:
                lo_i = mid
        return _result(
            feasible=True, solved_value=hi_i, achieved=ev(hi_i), target=target,
            direction=direction, iterations=iters, best=None, samples=samples,
        )

    # decreasing
    if s_hi >= target:
        return _result(
            feasible=True, solved_value=hi, achieved=s_hi, target=target,
            direction=direction, iterations=iters, best=None, samples=samples,
        )
    if s_lo < target:
        return _result(
            feasible=False, solved_value=lo, achieved=s_lo, target=target,
            direction=direction, iterations=iters, best=s_lo, samples=samples,
        )
    lo_i, hi_i = lo, hi  # invariant: ev(lo_i) >= target > ev(hi_i)
    while hi_i - lo_i > 1 and iters < iterations:
        iters += 1
        mid = (lo_i + hi_i) // 2
        if ev(mid) >= target:
            lo_i = mid
        else:
            hi_i = mid
    return _result(
        feasible=True, solved_value=lo_i, achieved=ev(lo_i), target=target,
        direction=direction, iterations=iters, best=None, samples=samples,
    )


__all__ = [
    "Direction",
    "Evaluate",
    "SolvePoint",
    "SolveResult",
    "solve_integer_monotone",
    "solve_monotone",
]
