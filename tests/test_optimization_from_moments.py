# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Live tests for ``optimize_from_moments`` (the CMA-driven optimizer entry).

These exercise the real PyPortfolioOpt solver, so they require the optimizer
dependency. It is part of the ``serve`` extra (and therefore installed in CI),
but a core-only local checkout skips this module.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pypfopt")

from nexus_core.engine.optimization import (  # noqa: E402  (after importorskip)
    MOMENT_OBJECTIVES,
    optimize_from_moments,
)

# A small, well-conditioned 3-asset toy: equity / bonds / gold.
_IDS = ["eq", "bond", "gold"]
_MU = {"eq": 0.07, "bond": 0.04, "gold": 0.035}
_VOLS = {"eq": 0.16, "bond": 0.05, "gold": 0.15}
_CORR = {
    "eq": {"eq": 1.0, "bond": 0.1, "gold": 0.0},
    "bond": {"eq": 0.1, "bond": 1.0, "gold": -0.1},
    "gold": {"eq": 0.0, "bond": -0.1, "gold": 1.0},
}
_COV = [[_CORR[r][c] * _VOLS[r] * _VOLS[c] for c in _IDS] for r in _IDS]


def test_moment_objectives_are_the_supported_set() -> None:
    assert sorted(MOMENT_OBJECTIVES) == [
        "efficient_return",
        "efficient_risk",
        "max_quadratic_utility",
        "max_sharpe",
        "min_volatility",
    ]


def test_weights_sum_to_one_and_are_bounded() -> None:
    result = optimize_from_moments(_MU, _COV, _IDS, objective="max_quadratic_utility", risk_aversion=3.0)
    assert set(result.weights) == set(_IDS)
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-4)
    assert all(-1e-9 <= w <= 1.0 + 1e-9 for w in result.weights.values())
    assert result.method == "max_quadratic_utility"
    assert result.metadata is not None and result.metadata["riskAversion"] == 3.0


def test_min_volatility_is_bond_tilted() -> None:
    result = optimize_from_moments(_MU, _COV, _IDS, objective="min_volatility")
    # Bonds carry the lowest variance, so the min-vol portfolio must lean on them.
    assert result.weights["bond"] > result.weights["eq"]
    assert result.weights["bond"] > result.weights["gold"]


def test_risk_aversion_is_monotonic_in_volatility() -> None:
    # Higher risk-aversion (lambda) must not raise portfolio volatility.
    vols = [
        optimize_from_moments(
            _MU, _COV, _IDS, objective="max_quadratic_utility", risk_aversion=la
        ).expected_volatility
        for la in (1.0, 3.0, 8.0)
    ]
    assert vols[0] is not None and vols[1] is not None and vols[2] is not None
    assert vols[0] >= vols[1] >= vols[2]


def test_weight_bounds_are_respected() -> None:
    result = optimize_from_moments(
        _MU, _COV, _IDS, objective="max_sharpe", weight_bounds=(0.0, 0.5)
    )
    assert all(w <= 0.5 + 1e-6 for w in result.weights.values())


def test_efficient_return_hits_target() -> None:
    result = optimize_from_moments(
        _MU, _COV, _IDS, objective="efficient_return", target_return=0.05
    )
    assert result.expected_return == pytest.approx(0.05, abs=1e-3)


def test_unknown_objective_raises() -> None:
    with pytest.raises(ValueError, match="unknown objective"):
        optimize_from_moments(_MU, _COV, _IDS, objective="nope")


def test_non_square_cov_raises() -> None:
    with pytest.raises(ValueError, match="square"):
        optimize_from_moments(_MU, [[0.1, 0.0]], _IDS, objective="min_volatility")


def test_missing_expected_return_raises() -> None:
    with pytest.raises(ValueError, match="missing"):
        optimize_from_moments({"eq": 0.07}, _COV, _IDS, objective="min_volatility")


def test_efficient_return_without_target_raises() -> None:
    with pytest.raises(ValueError, match="target_return required"):
        optimize_from_moments(_MU, _COV, _IDS, objective="efficient_return")


def test_non_positive_risk_aversion_raises() -> None:
    with pytest.raises(ValueError, match="risk_aversion"):
        optimize_from_moments(
            _MU, _COV, _IDS, objective="max_quadratic_utility", risk_aversion=0.0
        )


def test_efficient_risk_hits_target_volatility() -> None:
    result = optimize_from_moments(
        _MU, _COV, _IDS, objective="efficient_risk", target_volatility=0.08
    )
    assert result.expected_volatility == pytest.approx(0.08, abs=1e-3)


def test_efficient_risk_without_target_raises() -> None:
    with pytest.raises(ValueError, match="target_volatility required"):
        optimize_from_moments(_MU, _COV, _IDS, objective="efficient_risk")


def test_empty_asset_ids_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        optimize_from_moments({}, [], [], objective="min_volatility")


def test_solver_failure_surfaces_as_valueerror() -> None:
    # A target volatility below the achievable minimum makes PyPortfolioOpt raise
    # OptimizationError (an Exception subclass, NOT a ValueError). The wrapper must
    # re-raise it as ValueError so callers can map it to "infeasible" uniformly.
    cov = [[0.16**2, 0.9 * 0.16 * 0.15], [0.9 * 0.16 * 0.15, 0.15**2]]
    with pytest.raises(ValueError):
        optimize_from_moments(
            {"a": 0.06, "b": 0.07},
            cov,
            ["a", "b"],
            objective="efficient_risk",
            target_volatility=0.001,
        )
