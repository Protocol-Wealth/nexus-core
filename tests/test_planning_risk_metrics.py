# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the return-series risk-metrics engine."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import risk_metrics


def test_hand_values_annual_series() -> None:
    # returns [0.10, -0.05, 0.10], annual, rf = 0. All values hand-derived.
    out = risk_metrics(returns=[0.10, -0.05, 0.10], risk_free_rate=0.0, periods_per_year=1)
    assert out["periods"] == 3
    assert out["annualizedReturn"] == 0.0475  # (1.1*0.95*1.1)^(1/3) - 1
    assert out["annualizedVolatility"] == 0.0866  # sample stdev of the three
    assert out["sharpe"] == 0.5489
    assert out["sortino"] == pytest.approx(1.6467, rel=1e-3)
    assert out["maxDrawdown"] == -0.05  # 1.10 -> 1.045 trough
    assert out["valueAtRisk95"] == 0.035  # 5% quantile interp between -0.05 and 0.10
    assert out["conditionalVaR95"] == 0.05  # mean of the worst-5% tail


def test_periods_per_year_annualization_is_geometric() -> None:
    # Twelve identical +1% months annualize geometrically; zero dispersion.
    out = risk_metrics(returns=[0.01] * 12, periods_per_year=12)
    assert out["annualizedReturn"] == 0.1268  # 1.01^12 - 1
    assert out["annualizedVolatility"] == 0.0
    assert out["sharpe"] == 0.0  # guarded: no volatility
    assert out["sortino"] == 0.0  # guarded: no downside
    assert out["maxDrawdown"] == 0.0  # monotonically increasing


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"returns": [0.1]}, "at least 2"),
        ({"returns": [0.1, -1.0]}, "> -1"),
        ({"returns": [0.1, 0.2], "periods_per_year": 0}, "periods_per_year"),
    ],
)
def test_validation(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        risk_metrics(**kwargs)
