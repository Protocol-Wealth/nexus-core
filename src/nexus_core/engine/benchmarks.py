# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hold-strategy benchmark math (base-100 normalized returns).

Pure computation — no I/O. The data layer supplies aligned daily close-price
series (from CoinGecko); these helpers turn them into base-100 normalized
return series for single assets and buy-and-hold compositions (e.g. 50/50
ETH-USDC). The point is to answer *"did an LP/active strategy beat simply
holding?"* — pair a position's PnL with these baselines.

A composition is **buy-and-hold, no rebalancing**: at t0 you allocate the
weights and never touch them, so

    value_t / value_0 = Σ_i weight_i · (price_i_t / price_i_0)

scaled to base 100. (Daily rebalancing would be a different, higher-turnover
baseline; buy-and-hold is the honest "do nothing" comparison.)
"""

from __future__ import annotations

from dataclasses import dataclass

# CoinGecko coin ids for the benchmark assets (USDC is treated as a constant $1).
ASSET_COIN_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "USDC": "usd-coin",
}

#: Benchmark name → asset weights (must sum to 1.0).
BENCHMARK_COMPOSITIONS: dict[str, dict[str, float]] = {
    "BTC": {"BTC": 1.0},
    "ETH": {"ETH": 1.0},
    "SOL": {"SOL": 1.0},
    "ETH-USDC 50/50": {"ETH": 0.5, "USDC": 0.5},
    "ETH-BTC 50/50": {"ETH": 0.5, "BTC": 0.5},
    "ETH-USDC 60/40": {"ETH": 0.6, "USDC": 0.4},
    "ETH-USDC 70/30": {"ETH": 0.7, "USDC": 0.3},
}


@dataclass(frozen=True)
class BenchmarkPoint:
    """One point on a base-100 benchmark series."""

    timestamp: str
    value: float  # base-100 (100.0 at the series start)


@dataclass(frozen=True)
class BenchmarkSeries:
    """A named benchmark's base-100 series + headline return."""

    name: str
    composition: dict[str, float]
    points: list[BenchmarkPoint]
    total_return_pct: float  # (end / 100 - 1) * 100, i.e. end_value - 100


def normalize_base_100(closes: list[float]) -> list[float]:
    """Normalize a close-price series to base 100 at its first point."""
    if not closes or closes[0] <= 0:
        return []
    base = closes[0]
    return [100.0 * c / base for c in closes]


def composition_series(
    asset_closes: dict[str, list[float]], weights: dict[str, float]
) -> list[float]:
    """Base-100 buy-and-hold value series for a weighted composition.

    All asset series must be index-aligned (same length, same timestamps).
    Assets with a non-positive base price are skipped (their weight drops out).
    """
    assets = [a for a in weights if a in asset_closes and asset_closes[a]]
    if not assets:
        return []
    length = min(len(asset_closes[a]) for a in assets)
    bases = {a: asset_closes[a][0] for a in assets}
    series: list[float] = []
    for t in range(length):
        value = sum(
            weights[a] * (asset_closes[a][t] / bases[a]) for a in assets if bases[a] > 0
        )
        series.append(100.0 * value)
    return series


def build_benchmark_series(
    name: str,
    weights: dict[str, float],
    asset_closes: dict[str, list[float]],
    timestamps: list[str],
) -> BenchmarkSeries | None:
    """Assemble a :class:`BenchmarkSeries` from aligned closes + timestamps."""
    values = composition_series(asset_closes, weights)
    if not values:
        return None
    n = min(len(values), len(timestamps))
    points = [BenchmarkPoint(timestamp=timestamps[i], value=values[i]) for i in range(n)]
    total_return = points[-1].value - 100.0 if points else 0.0
    return BenchmarkSeries(
        name=name, composition=weights, points=points, total_return_pct=total_return
    )


__all__ = [
    "ASSET_COIN_IDS",
    "BENCHMARK_COMPOSITIONS",
    "BenchmarkPoint",
    "BenchmarkSeries",
    "build_benchmark_series",
    "composition_series",
    "normalize_base_100",
]
