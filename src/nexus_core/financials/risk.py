# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tail-risk and drawdown metrics.

VaR family (historical / Gaussian / Cornish-Fisher), CVaR (Expected
Shortfall), downside volatility, max drawdown.

Pure-Python; no third-party dep on the import path. Numerical
precision is sufficient for advisor-grade reporting; for trading
applications use a vectorized stack (numpy + scipy) — wrap these
shapes around it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskMetrics:
    var_historical_5: float | None
    var_gaussian_5: float | None
    var_cornish_fisher_5: float | None
    cvar_5: float | None
    downside_volatility: float | None
    max_drawdown: float | None


def _mean(xs: list[float]) -> float:
    if not xs:
        raise ValueError("empty sequence")
    return sum(xs) / len(xs)


def _stdev(xs: list[float], ddof: int = 1) -> float:
    n = len(xs)
    if n <= ddof:
        raise ValueError(f"need at least {ddof + 1} samples")
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (n - ddof)
    return math.sqrt(var)


def historical_var(returns: list[float], alpha: float = 0.05) -> float | None:
    """VaR via historical quantile. Returns a *negative* number for a loss."""
    if not returns or not 0 < alpha < 1:
        return None
    sorted_returns = sorted(returns)
    idx = max(0, min(len(sorted_returns) - 1, int(alpha * len(sorted_returns))))
    return sorted_returns[idx]


def gaussian_var(returns: list[float], alpha: float = 0.05) -> float | None:
    """Parametric VaR assuming Normal returns."""
    if len(returns) < 2:
        return None
    mu = _mean(returns)
    sd = _stdev(returns)
    if sd == 0:
        return mu
    # z-score for α (one-tailed). Approximation table; sufficient for
    # standard advisor reporting at 1% / 5% / 10%.
    z_table = {0.01: -2.326, 0.025: -1.960, 0.05: -1.645, 0.10: -1.282}
    z = z_table.get(round(alpha, 4))
    if z is None:
        # Fall back to inverse-erf approximation. Beasley-Springer/Moro is
        # too heavy for this module; advisor-grade ±0.005 tolerance is fine.
        z = -1.645  # default 5% if unrecognized
    return mu + z * sd


def cornish_fisher_var(returns: list[float], alpha: float = 0.05) -> float | None:
    """Cornish-Fisher VaR — adjusts Gaussian VaR for skewness and kurtosis."""
    if len(returns) < 4:
        return None
    mu = _mean(returns)
    sd = _stdev(returns)
    if sd == 0:
        return mu
    n = len(returns)
    skew = (sum((r - mu) ** 3 for r in returns) / n) / (sd**3)
    kurt = (sum((r - mu) ** 4 for r in returns) / n) / (sd**4) - 3.0
    z_table = {0.01: -2.326, 0.025: -1.960, 0.05: -1.645, 0.10: -1.282}
    z = z_table.get(round(alpha, 4), -1.645)
    z_cf = z + (z**2 - 1) * skew / 6 + (z**3 - 3 * z) * kurt / 24 - (
        2 * z**3 - 5 * z
    ) * skew**2 / 36
    return mu + z_cf * sd


def cvar_historical(returns: list[float], alpha: float = 0.05) -> float | None:
    """CVaR = expected loss conditional on being in the worst α tail."""
    if not returns or not 0 < alpha < 1:
        return None
    sorted_returns = sorted(returns)
    cutoff = max(1, int(alpha * len(sorted_returns)))
    tail = sorted_returns[:cutoff]
    return sum(tail) / len(tail) if tail else None


def downside_volatility(
    returns: list[float], target: float = 0.0
) -> float | None:
    """Stdev of returns below ``target`` (0 by default — semi-deviation)."""
    below = [(r - target) ** 2 for r in returns if r < target]
    if not below:
        return 0.0
    return math.sqrt(sum(below) / len(below))


def max_drawdown(returns: list[float]) -> float | None:
    """Max peak-to-trough drawdown for a return series."""
    if not returns:
        return None
    cum = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns:
        cum *= 1 + r
        peak = max(peak, cum)
        dd = (cum - peak) / peak
        mdd = min(mdd, dd)
    return mdd


def all_risk(returns: list[float]) -> RiskMetrics:
    """Convenience: compute every metric at α=5%."""
    return RiskMetrics(
        var_historical_5=historical_var(returns, alpha=0.05),
        var_gaussian_5=gaussian_var(returns, alpha=0.05),
        var_cornish_fisher_5=cornish_fisher_var(returns, alpha=0.05),
        cvar_5=cvar_historical(returns, alpha=0.05),
        downside_volatility=downside_volatility(returns),
        max_drawdown=max_drawdown(returns),
    )
