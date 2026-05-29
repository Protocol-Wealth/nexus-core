# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Benchmark snapshot trigger + persisted-history REST surface.

- ``POST /api/internal/snapshot/run`` — token-gated daily job (called by Cloud
  Scheduler from inside the VPC where the DB is reachable): fetch today's asset
  prices and upsert a row.
- ``GET /api/benchmarks/history`` — public read: base-100 series + total return
  per benchmark, derived from the **persisted** price history (vs the on-demand
  ``/api/benchmarks/series`` which hits CoinGecko live).

Persistence requires ``DATABASE_URL``; the trigger additionally requires
``SNAPSHOT_TOKEN``. Both 503 cleanly when unconfigured.
"""

from __future__ import annotations

import hmac
import os
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Query, Response

from ..data import db
from ..data.market import CoinGeckoMarketData
from ..data.snapshots import read_benchmark_snapshots, write_benchmark_snapshot
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


def build_snapshots_router(*, coingecko: CoinGeckoMarketData) -> APIRouter:
    """Build the snapshot trigger + persisted-history router."""
    router = APIRouter(tags=["benchmarks"])

    @router.post("/api/internal/snapshot/run", include_in_schema=False)
    async def run_snapshot(
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        """Fetch today's asset prices and upsert a daily snapshot (token-gated)."""
        token = os.getenv("SNAPSHOT_TOKEN")
        if not token:
            raise HTTPException(status_code=503, detail="Snapshot disabled: SNAPSHOT_TOKEN unset")
        expected = f"Bearer {token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=403, detail="Forbidden")
        if not db.is_configured():
            raise HTTPException(status_code=503, detail="DATABASE_URL not configured")

        prices: dict[str, float] = {}
        for asset in ("BTC", "ETH", "SOL"):
            quote = coingecko.get_quote(ASSET_COIN_IDS[asset])
            if quote is not None:
                prices[asset] = quote.price
        # Completeness gate: never persist a partial day — let the scheduler's
        # same-day retry re-attempt rather than store a row that would read as a
        # false drawdown for the missing asset.
        missing = [a for a in ("BTC", "ETH", "SOL") if a not in prices]
        if missing:
            raise HTTPException(
                status_code=502, detail=f"Incomplete price set from CoinGecko (missing {missing})"
            )
        prices["USDC"] = 1.0

        snapshot_date = datetime.now(UTC).date().isoformat()
        await write_benchmark_snapshot(snapshot_date, prices)
        return {"date": snapshot_date, "prices": prices, "stored": True}

    @router.get("/api/benchmarks/history", summary="Persisted benchmark history")
    async def history(
        response: Response,
        days: Annotated[int, Query(ge=1, le=3650, description="Max stored days to return")] = 365,
    ) -> dict[str, Any]:
        """Base-100 benchmark series derived from persisted daily prices."""
        if not db.is_configured():
            raise HTTPException(status_code=503, detail="History unavailable: DATABASE_URL not configured")
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
