# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Persisted benchmark-history REST surface (read-only).

``GET /api/benchmarks/history`` returns base-100 series + total return per
benchmark, derived from the **persisted** daily prices (vs the on-demand
``/api/benchmarks/series`` which hits CoinGecko live). Writes are performed by
the ``nexus-core snapshot`` Cloud Run Job (triggered daily via Cloud Scheduler
OIDC) — there is no public write endpoint.

Requires ``DATABASE_URL``; 503 cleanly when unconfigured.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response

from ..data import db
from ..data.snapshots import read_benchmark_snapshots
from ..engine.benchmarks import (
    ASSET_COIN_IDS,
    BENCHMARK_COMPOSITIONS,
    build_benchmark_series,
)

_HISTORY_TTL = 1800
_DISCLAIMER = (
    "Public market data — educational only, not investment advice. Benchmarks are "
    "buy-and-hold (no rebalancing), base-100 normalized from persisted daily prices; "
    "USDC is held at $1."
)


def build_snapshots_router() -> APIRouter:
    """Build the persisted-history router (read-only)."""
    router = APIRouter(tags=["benchmarks"])

    @router.get("/api/benchmarks/history", summary="Persisted benchmark history")
    async def history(
        response: Response,
        days: Annotated[int, Query(ge=1, le=3650, description="Max stored days to return")] = 365,
    ) -> dict[str, Any]:
        """Base-100 benchmark series derived from persisted daily prices."""
        if not db.is_configured():
            raise HTTPException(
                status_code=503, detail="History unavailable: DATABASE_URL not configured"
            )
        snaps = await read_benchmark_snapshots(limit=days)
        response.headers["Cache-Control"] = f"public, max-age={_HISTORY_TTL}"
        if not snaps:
            return {"snapshots": 0, "benchmarks": [], "disclaimer": _DISCLAIMER}

        timestamps = [s["date"] for s in snaps]
        closes: dict[str, list[float]] = {}
        for asset in ASSET_COIN_IDS:
            # Forward-fill transient gaps (a day missing this asset carries the
            # last known price) so a one-day CoinGecko miss isn't a false −100%.
            filled: list[float] = []
            last = 0.0
            for snap in snaps:
                raw = float(snap["prices"].get(asset, 0.0) or 0.0)
                if raw > 0:
                    last = raw
                filled.append(last)
            if any(v > 0 for v in filled):
                closes[asset] = filled

        built = []
        for name, weights in BENCHMARK_COMPOSITIONS.items():
            if any(a not in closes for a in weights):
                continue
            bench = build_benchmark_series(name, weights, closes, timestamps)
            if bench is not None:
                built.append(asdict(bench))
        return {"snapshots": len(snaps), "benchmarks": built, "disclaimer": _DISCLAIMER}

    return router


__all__ = ["build_snapshots_router"]
