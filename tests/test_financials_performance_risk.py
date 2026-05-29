# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for nexus_core.financials.performance + risk."""

from __future__ import annotations

from nexus_core.financials.performance import (
    all_performance,
    alpha_beta,
    information_ratio,
    sharpe_ratio,
    treynor_ratio,
)
from nexus_core.financials.risk import (
    all_risk,
    cornish_fisher_var,
    cvar_historical,
    downside_volatility,
    gaussian_var,
    historical_var,
    max_drawdown,
)


def test_sharpe_ratio_basic():
    # Returns with positive excess and non-zero stdev
    returns = [0.01, 0.02, -0.01, 0.015, 0.005, 0.0]
    out = sharpe_ratio(returns)
    assert out is not None
    assert out > 0


def test_sharpe_ratio_returns_none_for_short_series():
    assert sharpe_ratio([0.01]) is None


def test_treynor_ratio_basic():
    p = [0.02, 0.01, 0.03, -0.01, 0.015]
    b = [0.015, 0.01, 0.02, -0.005, 0.012]
    out = treynor_ratio(p, b)
    assert out is None or isinstance(out, float)


def test_information_ratio_basic():
    p = [0.02, 0.01, 0.03, -0.01, 0.015]
    b = [0.018, 0.005, 0.025, -0.012, 0.013]
    out = information_ratio(p, b)
    assert out is not None


def test_alpha_beta_basic():
    p = [0.02, 0.01, 0.03, -0.01, 0.015]
    b = [0.015, 0.01, 0.02, -0.005, 0.012]
    alpha, beta = alpha_beta(p, b)
    assert alpha is not None
    assert beta is not None


def test_all_performance_compose():
    p = [0.02, 0.01, 0.03, -0.01, 0.015]
    b = [0.015, 0.01, 0.02, -0.005, 0.012]
    out = all_performance(p, b)
    assert out.sharpe is not None
    assert out.alpha is not None


def test_historical_var_basic():
    returns = [-0.05, -0.03, -0.01, 0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
    out = historical_var(returns, alpha=0.10)
    assert out is not None
    assert out <= 0


def test_gaussian_var_basic():
    returns = [-0.02, 0.01, 0.0, 0.005, -0.01, 0.015, -0.005]
    out = gaussian_var(returns, alpha=0.05)
    assert out is not None


def test_cornish_fisher_var_basic():
    returns = [-0.02, 0.01, 0.0, 0.005, -0.01, 0.015, -0.005, -0.03, 0.02]
    out = cornish_fisher_var(returns, alpha=0.05)
    assert out is not None


def test_cvar_historical_basic():
    returns = [-0.05, -0.03, -0.01, 0.0, 0.01, 0.02]
    out = cvar_historical(returns, alpha=0.34)  # bottom third
    assert out is not None
    # cvar should be at least as bad as VaR (more negative or equal)
    var = historical_var(returns, alpha=0.34)
    if out is not None and var is not None:
        assert out <= var


def test_downside_volatility_zero_when_no_below_target():
    assert downside_volatility([0.01, 0.02, 0.03], target=0.0) == 0.0


def test_max_drawdown_basic():
    returns = [0.10, -0.20, 0.05, -0.05, 0.10]
    out = max_drawdown(returns)
    assert out is not None
    assert out < 0


def test_all_risk_composes():
    returns = [-0.02, 0.01, 0.0, 0.005, -0.01, 0.015, -0.005, -0.03, 0.02]
    out = all_risk(returns)
    assert out.var_historical_5 is not None
    assert out.var_gaussian_5 is not None
    assert out.cvar_5 is not None
    assert out.max_drawdown is not None
