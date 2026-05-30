# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hold-strategy benchmark REST surface (CoinGecko-backed).

``GET /api/benchmarks/series?days=90`` returns base-100 normalized return series
for BTC / ETH / SOL and buy-and-hold compositions (50/50 ETH-USDC, 60/40, …),
the "did holding beat LPing?" baselines. Public market data; on-demand from
CoinGecko historical (no stored state). Daily-persisted history is a later
addition once the market-data Cloud SQL is wired (Phase 3c).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response

from ..data.market import CoinGeckoMarketData
from ..disclaimers import TERSE
from ..engine.benchmarks import (
    ASSET_COIN_IDS,
    BENCHMARK_COMPOSITIONS,
    BenchmarkSeries,
    build_benchmark_series,
)

_BENCH_TTL = 3600
_CRYPTO_ASSETS = ("BTC", "ETH", "SOL")  # USDC is treated as a constant $1
_METHODOLOGY = (
    "Benchmarks are buy-and-hold (no rebalancing), base-100 normalized; USDC is held at $1."
)
_DISCLAIMER = f"{TERSE} {_METHODOLOGY}"


def fetch_benchmark_series(coingecko: CoinGeckoMarketData, days: int) -> list[BenchmarkSeries]:
    """Base-100 buy-and-hold benchmark series over ``days`` (empty on no data).

    Shared by the ``/api/benchmarks/series`` route and the LP vs-benchmark view.
    Fetches the volatile assets from CoinGecko, aligns them index-wise (OHLC for
    one ``days`` value returns same-length, same-timestamp series), holds USDC at
    $1, and builds each composition.
    """
    closes: dict[str, list[float]] = {}
    timestamps: list[str] = []
    for asset in _CRYPTO_ASSETS:
        bars = coingecko.get_price_history(ASSET_COIN_IDS[asset], days=days)
        if bars:
            closes[asset] = [b.close for b in bars]
            if not timestamps or len(bars) > len(timestamps):
                timestamps = [b.timestamp for b in bars]
    if not closes:
        return []

    length = min(len(s) for s in closes.values())
    closes = {a: s[:length] for a, s in closes.items()}
    closes["USDC"] = [1.0] * length
    timestamps = timestamps[:length]

    out: list[BenchmarkSeries] = []
    for name, weights in BENCHMARK_COMPOSITIONS.items():
        if any(a not in closes for a in weights):  # skip if an asset failed to load
            continue
        bench = build_benchmark_series(name, weights, closes, timestamps)
        if bench is not None:
            out.append(bench)
    return out


def build_benchmarks_router(*, coingecko: CoinGeckoMarketData) -> APIRouter:
    """Build the hold-strategy benchmark router around a CoinGecko provider."""
    router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])

    @router.get("", summary="Available hold-strategy benchmarks")
    def list_benchmarks() -> dict[str, Any]:
        """List benchmark names + their compositions."""
        return {
            "benchmarks": [
                {"name": name, "composition": comp}
                for name, comp in BENCHMARK_COMPOSITIONS.items()
            ],
            "assets": list(ASSET_COIN_IDS),
            "disclaimer": _DISCLAIMER,
        }

    @router.get("/series", summary="Base-100 benchmark return series")
    def series(
        response: Response,
        days: Annotated[int, Query(ge=1, le=365, description="Lookback window in days")] = 90,
    ) -> dict[str, Any]:
        """Base-100 return series + total return for every benchmark over ``days``."""
        built = fetch_benchmark_series(coingecko, days)
        if not built:
            raise HTTPException(
                status_code=503,
                detail="Benchmark data unavailable: no price history from CoinGecko",
            )
        response.headers["Cache-Control"] = f"public, max-age={_BENCH_TTL}"
        return {
            "days": days,
            "points": len(built[0].points),
            "benchmarks": [asdict(b) for b in built],
            "disclaimer": _DISCLAIMER,
        }

    return router


__all__ = ["build_benchmarks_router"]
