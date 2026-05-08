# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Risk-adjusted performance metrics — Sharpe, Treynor, Information Ratio,
Jensen Alpha + Beta.

Pure functions; expects pre-computed return series as ``list[float]``
or numeric iterables. No pandas required (works with any iterable).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Number = int | float


@dataclass(frozen=True)
class PerformanceMetrics:
    sharpe: float | None
    treynor: float | None
    information_ratio: float | None
    alpha: float | None
    beta: float | None


def _mean(xs: list[float]) -> float:
    if not xs:
        raise ValueError("empty sequence")
    return sum(xs) / len(xs)


def _variance(xs: list[float], ddof: int = 1) -> float:
    n = len(xs)
    if n <= ddof:
        raise ValueError(f"need at least {ddof + 1} samples")
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - ddof)


def _stdev(xs: list[float], ddof: int = 1) -> float:
    return math.sqrt(_variance(xs, ddof))


def _covariance(xs: list[float], ys: list[float], ddof: int = 1) -> float:
    if len(xs) != len(ys):
        raise ValueError("xs and ys must have equal length")
    n = len(xs)
    if n <= ddof:
        raise ValueError(f"need at least {ddof + 1} samples")
    mx, my = _mean(xs), _mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / (n - ddof)


def sharpe_ratio(
    returns: list[float],
    risk_free_rate_per_period: float = 0.0,
    annualization_factor: float = 252.0,
) -> float | None:
    """Annualized Sharpe = sqrt(N) × (mean(excess) / stdev(excess))."""
    if len(returns) < 2:
        return None
    excess = [r - risk_free_rate_per_period for r in returns]
    sd = _stdev(excess)
    if sd == 0:
        return None
    return math.sqrt(annualization_factor) * (_mean(excess) / sd)


def treynor_ratio(
    portfolio_returns: list[float],
    benchmark_returns: list[float],
    risk_free_rate_per_period: float = 0.0,
    annualization_factor: float = 252.0,
) -> float | None:
    """Annualized Treynor = (mean(excess) × N) / β."""
    if len(portfolio_returns) < 3 or len(portfolio_returns) != len(benchmark_returns):
        return None
    var_b = _variance(benchmark_returns)
    if var_b == 0:
        return None
    cov = _covariance(portfolio_returns, benchmark_returns)
    beta = cov / var_b
    if beta == 0:
        return None
    excess = [r - risk_free_rate_per_period for r in portfolio_returns]
    return (_mean(excess) * annualization_factor) / beta


def information_ratio(
    portfolio_returns: list[float],
    benchmark_returns: list[float],
    annualization_factor: float = 252.0,
) -> float | None:
    """Annualized IR = sqrt(N) × (mean(active) / tracking_error)."""
    if len(portfolio_returns) < 2 or len(portfolio_returns) != len(benchmark_returns):
        return None
    active = [p - b for p, b in zip(portfolio_returns, benchmark_returns, strict=True)]
    te = _stdev(active)
    if te == 0:
        return None
    return math.sqrt(annualization_factor) * (_mean(active) / te)


def alpha_beta(
    portfolio_returns: list[float],
    benchmark_returns: list[float],
    risk_free_rate_per_period: float = 0.0,
) -> tuple[float | None, float | None]:
    """Jensen-style α and β via OLS on excess returns.

    Returns ``(alpha_per_period, beta)``. Multiply alpha by your
    annualization factor for an annualized number.
    """
    if len(portfolio_returns) < 3 or len(portfolio_returns) != len(benchmark_returns):
        return None, None
    p_excess = [p - risk_free_rate_per_period for p in portfolio_returns]
    b_excess = [b - risk_free_rate_per_period for b in benchmark_returns]
    var_b = _variance(b_excess)
    if var_b == 0:
        return None, None
    beta = _covariance(p_excess, b_excess) / var_b
    alpha = _mean(p_excess) - beta * _mean(b_excess)
    return alpha, beta


def all_performance(
    portfolio_returns: list[float],
    benchmark_returns: list[float] | None = None,
    risk_free_rate_per_period: float = 0.0,
    annualization_factor: float = 252.0,
) -> PerformanceMetrics:
    """Convenience: compute every metric for which inputs are sufficient."""
    sharpe = sharpe_ratio(
        portfolio_returns, risk_free_rate_per_period, annualization_factor
    )
    if benchmark_returns is None:
        return PerformanceMetrics(
            sharpe=sharpe, treynor=None, information_ratio=None, alpha=None, beta=None
        )
    treynor = treynor_ratio(
        portfolio_returns, benchmark_returns, risk_free_rate_per_period, annualization_factor
    )
    ir = information_ratio(portfolio_returns, benchmark_returns, annualization_factor)
    alpha, beta = alpha_beta(portfolio_returns, benchmark_returns, risk_free_rate_per_period)
    return PerformanceMetrics(
        sharpe=sharpe, treynor=treynor, information_ratio=ir, alpha=alpha, beta=beta
    )
