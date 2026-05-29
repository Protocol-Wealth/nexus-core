# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Shape tests for nexus_core.engine.optimization.

These tests verify the package surface and lazy-import behavior — they
don't run the actual optimizers (which require the optional
``[optimization]`` extra). Live optimizer tests live under the ``live``
pytest marker and are skipped in CI.
"""

from __future__ import annotations

import pytest

from nexus_core.engine.optimization import (
    REGIME_OPTIMIZER_MAP,
    DiscreteAllocationResult,
    OptimizationResult,
    RiskfolioResult,
    absolute_view,
    relative_view,
)


def test_regime_optimizer_map_covers_canonical_codes():
    assert "GROWTH" in REGIME_OPTIMIZER_MAP
    assert "TRANSITION" in REGIME_OPTIMIZER_MAP
    assert "HARD_ASSET" in REGIME_OPTIMIZER_MAP
    assert "DEFLATION" in REGIME_OPTIMIZER_MAP
    assert "REPRESSION" in REGIME_OPTIMIZER_MAP


def test_optimization_result_carries_required_fields():
    result = OptimizationResult(
        weights={"AAPL": 0.5, "MSFT": 0.5},
        method="max_sharpe",
        expected_return=0.10,
        expected_volatility=0.15,
        sharpe_ratio=0.55,
    )
    assert result.weights["AAPL"] == 0.5
    assert result.method == "max_sharpe"


def test_riskfolio_result_carries_required_fields():
    result = RiskfolioResult(
        weights={"AAPL": 0.5, "MSFT": 0.5},
        method="risk_parity",
        risk_measure="MV",
    )
    assert result.risk_measure == "MV"


def test_discrete_allocation_result_carries_required_fields():
    result = DiscreteAllocationResult(
        shares={"AAPL": 10, "MSFT": 5},
        leftover_cash=42.50,
        method="lp",
        total_value=10_000.0,
    )
    assert result.shares["AAPL"] == 10
    assert result.method == "lp"


def test_absolute_view_builder():
    view = absolute_view("AAPL", 0.15, confidence=0.7)
    assert view.kind == "absolute"
    assert view.target_assets == ["AAPL"]
    assert view.comparison_assets == []
    assert view.expected_return == 0.15
    assert view.confidence == 0.7


def test_relative_view_builder():
    view = relative_view("AAPL", "MSFT", 0.05)
    assert view.kind == "relative"
    assert view.target_assets == ["AAPL"]
    assert view.comparison_assets == ["MSFT"]
    assert view.expected_return == 0.05


def test_view_is_immutable():
    view = absolute_view("AAPL", 0.10)
    with pytest.raises((AttributeError, TypeError)):
        view.kind = "relative"  # type: ignore[misc]
