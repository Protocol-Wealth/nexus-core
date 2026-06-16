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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

try:
    import pandas as pd
    from pypfopt import EfficientFrontier, HRPOpt, expected_returns, risk_models
except ImportError:  # pragma: no cover
    pd = EfficientFrontier = HRPOpt = expected_returns = risk_models = None


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


#: Objectives that ``optimize_from_moments`` can solve directly from (mu, Sigma).
#: ``hrp`` is intentionally excluded — Hierarchical Risk Parity clusters a *return
#: series*, not summary moments, so it has no moments-only form.
MOMENT_OBJECTIVES = frozenset(
    {"max_sharpe", "min_volatility", "max_quadratic_utility", "efficient_return", "efficient_risk"}
)


def optimize_from_moments(
    expected_returns_by_asset: Mapping[str, float],
    cov_matrix: Sequence[Sequence[float]],
    asset_ids: Sequence[str],
    *,
    objective: str = "max_sharpe",
    risk_aversion: float = 1.0,
    target_return: float | None = None,
    target_volatility: float | None = None,
    weight_bounds: tuple[float, float] = (0.0, 1.0),
    risk_free_rate: float = 0.045,
) -> OptimizationResult:
    """Optimize directly from forward moments (expected returns + covariance).

    Unlike :func:`optimize`, which estimates ``mu``/``Sigma`` from a price
    history, this entry point takes the moments as inputs — so it can be driven
    by *forward* capital-market assumptions (a house view) rather than realized
    history. The covariance is an annualized matrix aligned to ``asset_ids``
    (row/column order), e.g. ``Sigma[i][j] = corr[i][j] * vol_i * vol_j``.

    Args:
        expected_returns_by_asset: Annualized expected return per asset id.
        cov_matrix: Annualized covariance matrix; ``cov_matrix[i][j]`` pairs
            ``asset_ids[i]`` with ``asset_ids[j]`` (must be square + symmetric).
        asset_ids: The asset order shared by ``cov_matrix`` rows/columns and the
            returned weights.
        objective: One of :data:`MOMENT_OBJECTIVES`. ``max_quadratic_utility``
            maximizes ``mu'w - (risk_aversion/2) w'Sigma w`` — the canonical
            mean-variance utility whose ``risk_aversion`` knob spans the frontier
            (high = conservative/low-variance, low = aggressive/high-return).
        risk_aversion: Risk-aversion coefficient for ``max_quadratic_utility``
            (must be > 0).
        target_return: Required for ``efficient_return``.
        target_volatility: Required for ``efficient_risk``.
        weight_bounds: Per-asset (min, max) bounds.
        risk_free_rate: Annual rate for Sharpe + ``max_sharpe``.

    Raises:
        ImportError: If PyPortfolioOpt is not installed (``[optimization]`` extra).
        ValueError: On a bad objective, mismatched shapes, or missing target.
    """
    if pd is None:
        raise ImportError(
            "PyPortfolioOpt not installed. Install with: pip install nexus-core[optimization]"
        )
    if objective not in MOMENT_OBJECTIVES:
        raise ValueError(
            f"unknown objective {objective!r}; expected one of {sorted(MOMENT_OBJECTIVES)}"
        )

    ids = list(asset_ids)
    n = len(ids)
    if n == 0:
        raise ValueError("asset_ids must be non-empty")
    if len(cov_matrix) != n or any(len(row) != n for row in cov_matrix):
        raise ValueError("cov_matrix must be square and aligned to asset_ids")
    missing = [a for a in ids if a not in expected_returns_by_asset]
    if missing:
        raise ValueError(f"expected returns missing for: {', '.join(missing)}")

    # Past the pd guard PyPortfolioOpt is installed, so this import is safe.
    from pypfopt.exceptions import OptimizationError

    mu = pd.Series([float(expected_returns_by_asset[a]) for a in ids], index=ids)
    sigma = pd.DataFrame([[float(c) for c in row] for row in cov_matrix], index=ids, columns=ids)

    ef = EfficientFrontier(mu, sigma, weight_bounds=weight_bounds)
    # The solver can fail to converge or be infeasible (e.g. a target outside the
    # frontier, or an over-constrained budget). PyPortfolioOpt signals that with
    # OptimizationError (which subclasses Exception, NOT ValueError). Re-raise as
    # ValueError so callers can treat it uniformly as "could not solve".
    try:
        if objective == "max_sharpe":
            ef.max_sharpe(risk_free_rate=risk_free_rate)
        elif objective == "min_volatility":
            ef.min_volatility()
        elif objective == "max_quadratic_utility":
            if risk_aversion <= 0:
                raise ValueError("risk_aversion must be > 0 for max_quadratic_utility")
            ef.max_quadratic_utility(risk_aversion=risk_aversion)
        elif objective == "efficient_return":
            if target_return is None:
                raise ValueError("target_return required for efficient_return")
            ef.efficient_return(target_return=target_return)
        else:  # efficient_risk
            if target_volatility is None:
                raise ValueError("target_volatility required for efficient_risk")
            ef.efficient_risk(target_volatility=target_volatility)
        weights = ef.clean_weights()
        ret, vol, sharpe = ef.portfolio_performance(risk_free_rate=risk_free_rate)
    except OptimizationError as exc:
        raise ValueError(f"the optimizer could not solve this allocation: {exc}") from exc
    metadata: dict[str, Any] = {"weightBounds": list(weight_bounds)}
    if objective == "max_quadratic_utility":
        metadata["riskAversion"] = risk_aversion
    return OptimizationResult(
        weights=dict(weights),
        method=objective,
        expected_return=float(ret),
        expected_volatility=float(vol),
        sharpe_ratio=float(sharpe),
        metadata=metadata,
    )


__all__ = [
    "MOMENT_OBJECTIVES",
    "REGIME_OPTIMIZER_MAP",
    "OptimizationResult",
    "optimize",
    "optimize_for_regime",
    "optimize_from_moments",
]
