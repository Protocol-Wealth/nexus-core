# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the planning correlation-matrix engine."""

from __future__ import annotations

import math

import pytest

from nexus_core.engine.planning import correlation_matrix


def _series() -> dict[str, list[float]]:
    # a, b strongly positively correlated; a, c negatively correlated.
    a = [0.01, -0.02, 0.03, -0.01, 0.02, -0.015, 0.025, -0.005, 0.012, -0.018]
    b = [0.012, -0.018, 0.028, -0.012, 0.022, -0.013, 0.024, -0.006, 0.011, -0.02]
    c = [-0.011, 0.02, -0.03, 0.012, -0.02, 0.014, -0.026, 0.004, -0.013, 0.017]
    return {"a": a, "b": b, "c": c}


def test_sample_correlation_is_symmetric_unit_diagonal() -> None:
    m = correlation_matrix(_series(), shrinkage=False)
    ids = list(m)
    for i in ids:
        assert m[i][i] == 1.0
        for j in ids:
            assert m[i][j] == pytest.approx(m[j][i])  # symmetric


def test_sample_correlation_signs_match_construction() -> None:
    m = correlation_matrix(_series(), shrinkage=False)
    assert m["a"]["b"] > 0.8  # strongly positive
    assert m["a"]["c"] < -0.8  # strongly negative
    assert -1.0 <= m["a"]["c"] <= 1.0


def test_shrinkage_pulls_offdiagonals_toward_average() -> None:
    sample = correlation_matrix(_series(), shrinkage=False)
    shrunk = correlation_matrix(_series(), shrinkage=True)
    # Diagonal preserved; matrix stays symmetric and within bounds.
    for i in shrunk:
        assert shrunk[i][i] == 1.0
        for j in shrunk:
            assert shrunk[i][j] == pytest.approx(shrunk[j][i], abs=1e-9)
            assert -1.0 <= shrunk[i][j] <= 1.0
    # Shrinkage moves each off-diagonal toward the sample average correlation
    # (i.e. no shrunk magnitude exceeds the corresponding sample magnitude).
    offdiag = [(i, j) for i in sample for j in sample if i != j]
    assert any(abs(shrunk[i][j]) < abs(sample[i][j]) for i, j in offdiag)
    for i, j in offdiag:
        assert abs(shrunk[i][j]) <= abs(sample[i][j]) + 1e-9


def test_single_asset_returns_unit_matrix() -> None:
    m = correlation_matrix({"only": [0.01, -0.02, 0.03, 0.0]}, shrinkage=True)
    assert m == {"only": {"only": 1.0}}


def test_unaligned_series_raises() -> None:
    with pytest.raises(ValueError, match="same length"):
        correlation_matrix({"a": [0.1, 0.2, 0.3], "b": [0.1, 0.2]}, shrinkage=False)


def test_too_short_series_raises() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        correlation_matrix({"a": [0.1], "b": [0.2]}, shrinkage=False)


def test_perfectly_correlated_inputs() -> None:
    s = [0.01, -0.02, 0.03, -0.01, 0.02]
    m = correlation_matrix({"x": s, "y": s}, shrinkage=False)
    assert m["x"]["y"] == pytest.approx(1.0)
    assert not math.isnan(m["x"]["y"])
