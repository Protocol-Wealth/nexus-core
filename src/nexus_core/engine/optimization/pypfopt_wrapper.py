# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""PyPortfolioOpt wrapper with regime-aware parameter selection.

PyPortfolioOpt (MIT) provides the optimization primitives; this wrapper adds:

    1. A consistent Pythonic interface that doesn't leak library-specific types.
    2. Regime-aware parameter selection — different optimizers for different
       regimes (e.g., HRP in TRANSITION, Max Sharpe in GROWTH).
    3. Constraint defaults aligned with typical advisor risk budgets.

Install::

    pip install nexus-core[optimization]

Attribution:
    PyPortfolioOpt — Copyright 2018-2024 Robert Andrew Martin (MIT).
    https://github.com/robertmartin8/PyPortfolioOpt
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    import numpy as np
    import pandas as pd
    from pypfopt import EfficientFrontier, HRPOpt, expected_returns, risk_models
except ImportError:  # pragma: no cover
    np = pd = EfficientFrontier = HRPOpt = expected_returns = risk_models = None  # type: ignore[assignment,misc]


@dataclass
class OptimizationResult:
    """Outcome of a portfolio optimization run.

    Attributes:
        weights: Ticker -> weight (0-1, sum to 1).
        method: The optimizer used ("max_sharpe", "min_volatility", "hrp", ...).
        expected_return: Annualized expected return.
        expected_volatility: Annualized volatility.
        sharpe_ratio: (expected_return - rf) / volatility.
        metadata: Regime, constraints used, etc.
    """

    weights: dict[str, float]
    method: str
    expected_return: float | None = None
    expected_volatility: float | None = None
    sharpe_ratio: float | None = None
    metadata: dict[str, Any] | None = None


#: Default regime → optimizer method. Users can override per-regime.
REGIME_OPTIMIZER_MAP = {
    "GROWTH": "max_sharpe",
    "TRANSITION": "hrp",  # Robust when correlations change
    "HARD_ASSET": "min_volatility",
    "DEFLATION": "min_volatility",
    "REPRESSION": "max_sharpe",
}


def optimize(
    prices: Any,  # pd.DataFrame[date, ticker] -> price
    *,
    method: str = "max_sharpe",
    risk_free_rate: float = 0.045,
    weight_bounds: tuple[float, float] = (0.0, 1.0),
    target_return: float | None = None,
    target_volatility: float | None = None,
) -> OptimizationResult:
    """Run a portfolio optimization.

    Args:
        prices: ``pd.DataFrame`` of daily close prices, columns=tickers.
        method: ``max_sharpe``, ``min_volatility``, ``efficient_return``,
            ``efficient_risk``, or ``hrp`` (Hierarchical Risk Parity).
        risk_free_rate: Annual rate for Sharpe calculation.
        weight_bounds: Per-asset bounds (min, max).
        target_return: Required for ``efficient_return``.
        target_volatility: Required for ``efficient_risk``.
    """
    if pd is None:
        raise ImportError(
            "PyPortfolioOpt not installed. Install with: pip install nexus-core[optimization]"
        )

    mu = expected_returns.mean_historical_return(prices)
    sigma = risk_models.CovarianceShrinkage(prices).ledoit_wolf()

    if method == "hrp":
        returns = prices.pct_change().dropna()
        hrp = HRPOpt(returns=returns)
        hrp.optimize()
        weights = hrp.clean_weights()
        return OptimizationResult(
            weights=dict(weights),
            method="hrp",
            metadata={"note": "HRP is correlation-robust; no Sharpe computed"},
        )

    ef = EfficientFrontier(mu, sigma, weight_bounds=weight_bounds)

    if method == "max_sharpe":
        ef.max_sharpe(risk_free_rate=risk_free_rate)
    elif method == "min_volatility":
        ef.min_volatility()
    elif method == "efficient_return":
        if target_return is None:
            raise ValueError("target_return required for efficient_return")
        ef.efficient_return(target_return=target_return)
    elif method == "efficient_risk":
        if target_volatility is None:
            raise ValueError("target_volatility required for efficient_risk")
        ef.efficient_risk(target_volatility=target_volatility)
    else:
        raise ValueError(f"Unknown optimization method: {method}")

    weights = ef.clean_weights()
    ret, vol, sharpe = ef.portfolio_performance(risk_free_rate=risk_free_rate)

    return OptimizationResult(
        weights=dict(weights),
        method=method,
        expected_return=float(ret),
        expected_volatility=float(vol),
        sharpe_ratio=float(sharpe),
    )


def optimize_for_regime(
    prices: Any,
    regime: str,
    *,
    optimizer_map: dict[str, str] | None = None,
    **kwargs: Any,
) -> OptimizationResult:
    """Pick an optimizer based on regime and run it.

    Args:
        prices: Historical price DataFrame.
        regime: A regime code (``RegimeCode.value``).
        optimizer_map: Override the default regime→method mapping.
    """
    mapping = optimizer_map or REGIME_OPTIMIZER_MAP
    method = mapping.get(regime, "max_sharpe")
    result = optimize(prices, method=method, **kwargs)
    if result.metadata is None:
        result.metadata = {}
    result.metadata["regime"] = regime
    return result


__all__ = ["REGIME_OPTIMIZER_MAP", "OptimizationResult", "optimize", "optimize_for_regime"]
