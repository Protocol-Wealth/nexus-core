# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Return-series risk metrics (educational).

Standard ex-post risk statistics for a realized (or simulated) periodic return
series: annualized return / volatility, Sharpe and Sortino ratios, maximum
drawdown, and historical Value-at-Risk / Conditional VaR. Pure Python — no
numpy / empyrical dependency — so the same core runs in the tool gateway, the
REST surface, and tests.

Conventions: returns are simple per-period returns (``0.05`` = +5%); annualization
uses ``periods_per_year`` (1 = annual, 12 = monthly, 252 = daily). Sortino's
downside deviation and VaR/CVaR use a 0% minimum-acceptable-return threshold.
This is descriptive analysis of a supplied series, not advice or a forecast.
"""

from __future__ import annotations

import math
from typing import Any

#: Tail probability for Value-at-Risk / Conditional VaR (5% ⇒ 95% confidence).
_VAR_TAIL = 0.05


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation quantile of an already-sorted, non-empty list."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def risk_metrics(
    *,
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 1,
) -> dict[str, Any]:
    """Annualized risk statistics for a periodic return series.

    Args:
        returns: Simple per-period returns (need >= 2; each > -1).
        risk_free_rate: Annual risk-free rate for the Sharpe / Sortino numerator.
        periods_per_year: Periods per year for annualization (>= 1).

    Returns:
        ``periods``, ``annualizedReturn`` (geometric), ``annualizedVolatility``
        (sample stdev annualized), ``sharpe``, ``sortino``, ``maxDrawdown`` (a
        negative fraction, peak-to-trough of the cumulative series),
        ``valueAtRisk95`` and ``conditionalVaR95`` (positive loss fractions at
        95% confidence; CVaR is the mean loss in the worst 5% tail).
    """
    n = len(returns)
    if n < 2:
        raise ValueError("returns must have at least 2 observations")
    if any(r <= -1 for r in returns):
        raise ValueError("each return must be > -1 (a -100% period wipes out the series)")
    if periods_per_year < 1:
        raise ValueError("periods_per_year must be >= 1")

    mean = sum(returns) / n
    cumulative_growth = math.prod(1.0 + r for r in returns)
    annualized_return = cumulative_growth ** (periods_per_year / n) - 1.0

    # Sample (n-1) standard deviation, annualized by sqrt of periods.
    variance = sum((r - mean) ** 2 for r in returns) / (n - 1)
    period_vol = math.sqrt(variance)
    annualized_vol = period_vol * math.sqrt(periods_per_year)
    sharpe = (annualized_return - risk_free_rate) / annualized_vol if annualized_vol > 0 else 0.0

    # Downside deviation about a 0% per-period threshold, annualized.
    downside = math.sqrt(sum(min(0.0, r) ** 2 for r in returns) / n)
    annualized_downside = downside * math.sqrt(periods_per_year)
    sortino = (
        (annualized_return - risk_free_rate) / annualized_downside
        if annualized_downside > 0
        else 0.0
    )

    # Maximum drawdown on the cumulative wealth curve (starts at 1.0).
    wealth = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for r in returns:
        wealth *= 1.0 + r
        peak = max(peak, wealth)
        max_drawdown = min(max_drawdown, wealth / peak - 1.0)

    # Historical VaR / CVaR at the 5% tail, reported as positive loss fractions.
    ordered = sorted(returns)
    var_return = _quantile(ordered, _VAR_TAIL)
    tail = [r for r in ordered if r <= var_return]
    cvar_return = sum(tail) / len(tail) if tail else var_return

    return {
        "periods": n,
        "annualizedReturn": round(annualized_return, 4),
        "annualizedVolatility": round(annualized_vol, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "maxDrawdown": round(max_drawdown, 4),
        "valueAtRisk95": round(-var_return, 4),
        "conditionalVaR95": round(-cvar_return, 4),
    }


__all__ = ["risk_metrics"]
