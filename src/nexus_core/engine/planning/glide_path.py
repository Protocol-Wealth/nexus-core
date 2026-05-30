# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Equity glide-path construction.

A glide path is the planned equity weight at each age from ``current_age``
through ``horizon_age``. Three shapes are supported:

``linear``
    A straight line from ``start_equity_weight`` (at ``current_age``) to
    ``end_equity_weight`` (at ``horizon_age``). ``retirement_age`` is not used.

``to_through``
    Glide linearly from start to end across the accumulation window
    (``current_age`` -> ``retirement_age``), then hold ``end_equity_weight`` flat
    through ``horizon_age``. A conventional "de-risk to retirement" path.

``rising_equity``
    A U-shaped "bond-tent" / rising-equity path (Pfau-Kitces): glide from start
    down to end by ``retirement_age`` (the trough), then rise back from end
    toward start by ``horizon_age``. Equity is lowest around retirement and
    rises through it.

All weights are clamped to ``[0, 1]``. This is pure, deterministic scenario
math — educational only, not advice.
"""

from __future__ import annotations

from typing import Literal

GlidePathShape = Literal["linear", "to_through", "rising_equity"]

_SHAPES: tuple[GlidePathShape, ...] = ("linear", "to_through", "rising_equity")


def _lerp(start: float, end: float, fraction: float) -> float:
    """Linear interpolation; ``fraction`` is clamped to ``[0, 1]``."""
    f = min(1.0, max(0.0, fraction))
    return start + (end - start) * f


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def compute_glide_path(
    *,
    current_age: int,
    retirement_age: int,
    horizon_age: int,
    start_equity_weight: float,
    end_equity_weight: float,
    shape: GlidePathShape,
) -> dict[int, float]:
    """Return ``{age: equity_weight}`` for every age in ``[current_age, horizon_age]``.

    Args:
        current_age: First age in the path (inclusive).
        retirement_age: Pivot age for ``to_through`` / ``rising_equity``.
        horizon_age: Last age in the path (inclusive).
        start_equity_weight: Equity weight at ``current_age`` (``[0, 1]``).
        end_equity_weight: Target equity weight at the end / trough (``[0, 1]``).
        shape: One of ``linear``, ``to_through``, ``rising_equity``.

    Raises:
        ValueError: On an invalid shape, age ordering, or weight out of range.
    """
    if shape not in _SHAPES:
        raise ValueError(f"shape must be one of {', '.join(_SHAPES)}; got '{shape}'")
    if not current_age < retirement_age <= horizon_age:
        raise ValueError(
            "ages must satisfy current_age < retirement_age <= horizon_age "
            f"(got {current_age}, {retirement_age}, {horizon_age})"
        )
    for label, weight in (
        ("start_equity_weight", start_equity_weight),
        ("end_equity_weight", end_equity_weight),
    ):
        if not 0.0 <= weight <= 1.0:
            raise ValueError(f"{label} must be in [0, 1]; got {weight}")

    accumulation_span = retirement_age - current_age
    decumulation_span = horizon_age - retirement_age

    def _weight(age: int) -> float:
        if shape == "linear":
            return _lerp(
                start_equity_weight,
                end_equity_weight,
                (age - current_age) / (horizon_age - current_age),
            )
        # to_through and rising_equity glide identically down to the trough at retirement.
        if age <= retirement_age:
            return _lerp(
                start_equity_weight, end_equity_weight, (age - current_age) / accumulation_span
            )
        if shape == "to_through":
            return end_equity_weight
        # rising_equity, after retirement: rise back from the trough toward start.
        if decumulation_span > 0:
            return _lerp(
                end_equity_weight, start_equity_weight, (age - retirement_age) / decumulation_span
            )
        return end_equity_weight

    return {age: _clamp01(_weight(age)) for age in range(current_age, horizon_age + 1)}


__all__ = ["GlidePathShape", "compute_glide_path"]
