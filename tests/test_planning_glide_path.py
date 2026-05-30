# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the pure glide-path engine."""

from __future__ import annotations

from typing import Any

import pytest

from nexus_core.engine.planning import compute_glide_path


def _path(**overrides: Any) -> dict[int, float]:
    base: dict[str, Any] = {
        "current_age": 45,
        "retirement_age": 65,
        "horizon_age": 95,
        "start_equity_weight": 0.7,
        "end_equity_weight": 0.3,
        "shape": "linear",
    }
    base.update(overrides)
    return compute_glide_path(**base)


def test_linear_endpoints_midpoint_and_length() -> None:
    path = _path(shape="linear")
    assert len(path) == 95 - 45 + 1
    assert path[45] == pytest.approx(0.7)
    assert path[95] == pytest.approx(0.3)
    assert path[70] == pytest.approx(0.5)  # halfway across 45..95


def test_linear_is_monotone_decreasing() -> None:
    path = _path(shape="linear")
    values = [path[age] for age in sorted(path)]
    assert all(values[i] >= values[i + 1] for i in range(len(values) - 1))


def test_to_through_reaches_end_at_retirement_then_flat() -> None:
    path = _path(shape="to_through")
    assert path[45] == pytest.approx(0.7)
    assert path[65] == pytest.approx(0.3)  # end reached at retirement
    assert path[80] == pytest.approx(0.3)  # flat through horizon
    assert path[95] == pytest.approx(0.3)


def test_rising_equity_is_u_shaped() -> None:
    path = _path(shape="rising_equity")
    assert path[45] == pytest.approx(0.7)
    assert path[65] == pytest.approx(0.3)  # trough at retirement
    assert path[95] == pytest.approx(0.7)  # rises back toward start
    assert path[65] < path[55]
    assert path[65] < path[80]


def test_weights_stay_within_unit_interval() -> None:
    for shape in ("linear", "to_through", "rising_equity"):
        path = _path(shape=shape, start_equity_weight=1.0, end_equity_weight=0.0)
        assert all(0.0 <= weight <= 1.0 for weight in path.values())


def test_invalid_shape_raises() -> None:
    with pytest.raises(ValueError, match="shape"):
        _path(shape="spiral")


def test_invalid_age_order_raises() -> None:
    with pytest.raises(ValueError, match="ages"):
        _path(current_age=70)  # current >= retirement


def test_weight_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="start_equity_weight"):
        _path(start_equity_weight=1.5)
