# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Black-Litterman view construction + posterior expected returns.

Wraps PyPortfolioOpt's ``BlackLittermanModel``. Builds the BL
"posterior" expected-returns vector that MVO / max-Sharpe etc. can
then consume.

The interesting bit isn't the math (PyPortfolioOpt has it); it's
expressing views in a clean Pythonic shape: ``View`` value objects
that callers can build incrementally, then handed off as a list.

Attribution:
    PyPortfolioOpt — Copyright 2018-2024 Robert Andrew Martin (MIT).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ViewKind = Literal["absolute", "relative"]


@dataclass(frozen=True)
class View:
    """One advisor view on expected returns.

    Absolute view:  asset X will return Y%.
    Relative view:  asset X will outperform asset Z by Y%.

    Attributes:
        kind: ``absolute`` or ``relative``.
        target_assets: Tickers the view is "long" on.
        comparison_assets: For relative views, tickers the view is
            "short" on (must be empty for absolute views).
        expected_return: The target return (for absolute) or
            outperformance (for relative).
        confidence: Caller's confidence in the view, 0–1.
            Used by Idzorek's confidence method when wired.
    """

    kind: ViewKind
    target_assets: list[str]
    comparison_assets: list[str]
    expected_return: float
    confidence: float = 0.5


def absolute_view(asset: str, expected_return: float, confidence: float = 0.5) -> View:
    return View(
        kind="absolute",
        target_assets=[asset],
        comparison_assets=[],
        expected_return=expected_return,
        confidence=confidence,
    )


def relative_view(
    long_asset: str,
    short_asset: str,
    outperformance: float,
    confidence: float = 0.5,
) -> View:
    return View(
        kind="relative",
        target_assets=[long_asset],
        comparison_assets=[short_asset],
        expected_return=outperformance,
        confidence=confidence,
    )


def black_litterman_posterior(
    prior_returns: Any,  # pd.Series of equilibrium / market-implied returns
    cov_matrix: Any,  # pd.DataFrame
    views: list[View],
    *,
    tau: float = 0.05,
    risk_aversion: float = 2.5,
) -> Any:
    """Compute BL posterior expected-returns vector.

    Pass the result into any optimizer that takes a ``mu`` series
    (PyPortfolioOpt's ``EfficientFrontier``, etc.).

    Args:
        prior_returns: Equilibrium / implied returns (e.g. via
            ``pypfopt.black_litterman.market_implied_prior_returns``).
        cov_matrix: Asset covariance matrix.
        views: List of ``View`` objects.
        tau: Uncertainty in the prior. Standard 0.025–0.05.
        risk_aversion: Investor risk-aversion coefficient.

    Returns:
        ``pd.Series`` of posterior expected returns (one per asset).
    """
    try:
        from pypfopt import BlackLittermanModel
    except ImportError as exc:
        raise RuntimeError(
            "PyPortfolioOpt not installed. Install with: pip install nexus-core[optimization]"
        ) from exc

    if not views:
        return prior_returns

    # Build the P matrix (k views × n assets) and Q vector (k views).
    assets = list(prior_returns.index) if hasattr(prior_returns, "index") else []
    k = len(views)
    n = len(assets)

    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("numpy required") from exc

    p_matrix = np.zeros((k, n))
    q_vector = np.zeros(k)

    for i, view in enumerate(views):
        for ticker in view.target_assets:
            if ticker in assets:
                p_matrix[i, assets.index(ticker)] = 1.0
        for ticker in view.comparison_assets:
            if ticker in assets:
                p_matrix[i, assets.index(ticker)] = -1.0
        q_vector[i] = view.expected_return

    bl = BlackLittermanModel(
        cov_matrix,
        pi=prior_returns,
        Q=q_vector,
        P=p_matrix,
        tau=tau,
        risk_aversion=risk_aversion,
    )
    return bl.bl_returns()
