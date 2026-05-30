# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Discrete (whole-share) allocation — converts continuous weights into
integer share counts that fit a target portfolio value.

Wraps PyPortfolioOpt's ``DiscreteAllocation``. Returns the share
allocation plus the leftover cash (always >= 0).

Attribution:
    PyPortfolioOpt — Copyright 2018-2024 Robert Andrew Martin (MIT).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DiscreteAllocationResult:
    shares: dict[str, int]
    leftover_cash: float
    method: str  # "lp" or "greedy"
    total_value: float


def discrete_allocate(
    weights: dict[str, float],
    latest_prices: Any,  # pd.Series[ticker -> price]
    total_portfolio_value: float,
    *,
    method: str = "lp",
    short_ratio: float | None = None,
) -> DiscreteAllocationResult:
    """Compute integer share allocation from continuous weights.

    Args:
        weights: Continuous weights (e.g. from ``optimize()``).
        latest_prices: Prices at allocation time, one per ticker.
        total_portfolio_value: Total dollar value to allocate.
        method: ``lp`` (linear-programming, optimal) or ``greedy``
            (faster, near-optimal).
        short_ratio: If allowing short positions, fraction of total
            value that may be shorted. ``None`` disables shorts.
    """
    try:
        from pypfopt import DiscreteAllocation
    except ImportError as exc:
        raise RuntimeError(
            "PyPortfolioOpt not installed. Install with: pip install nexus-core[optimization]"
        ) from exc

    da_kwargs: dict[str, Any] = {
        "weights": weights,
        "latest_prices": latest_prices,
        "total_portfolio_value": total_portfolio_value,
    }
    if short_ratio is not None:
        da_kwargs["short_ratio"] = short_ratio

    da = DiscreteAllocation(**da_kwargs)
    if method == "lp":
        shares, leftover = da.lp_portfolio()
    elif method == "greedy":
        shares, leftover = da.greedy_portfolio()
    else:
        raise ValueError(f"Unknown method: {method}")

    return DiscreteAllocationResult(
        shares={ticker: int(qty) for ticker, qty in shares.items()},
        leftover_cash=float(leftover),
        method=method,
        total_value=total_portfolio_value,
    )
