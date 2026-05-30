# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Daily benchmark-price snapshot job (Cloud Run Job entrypoint).

``nexus-core snapshot`` runs this. In production a Cloud Scheduler job triggers
the Cloud Run Job daily via a service-account OIDC identity — **no public HTTP
endpoint and no shared secret**. The job runs inside ``pwllc-prod-vpc`` where the
private ``nexus-marketdata`` DB is reachable: it fetches today's BTC/ETH/SOL
prices from CoinGecko and upserts one row (USDC held at $1).

Fails loudly (non-zero exit) on incomplete prices or a DB error so the
scheduler's retry re-attempts rather than persisting a partial day.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from ..data import db
from ..data.market import CoinGeckoMarketData
from ..data.snapshots import write_benchmark_snapshot
from ..engine.benchmarks import ASSET_COIN_IDS

logger = logging.getLogger(__name__)

_CRYPTO_ASSETS = ("BTC", "ETH", "SOL")


async def run_snapshot(coingecko: CoinGeckoMarketData) -> dict[str, object]:
    """Fetch today's prices and upsert a snapshot row.

    Raises ``RuntimeError`` if the DB is unconfigured or the price set is
    incomplete (so the day is retried, never stored partial).
    """
    if not db.is_configured():
        raise RuntimeError("DATABASE_URL is not configured")
    prices: dict[str, float] = {}
    for asset in _CRYPTO_ASSETS:
        quote = coingecko.get_quote(ASSET_COIN_IDS[asset])
        if quote is not None:
            prices[asset] = quote.price
    missing = [a for a in _CRYPTO_ASSETS if a not in prices]
    if missing:
        raise RuntimeError(f"Incomplete price set from CoinGecko (missing {missing})")
    prices["USDC"] = 1.0
    snapshot_date = datetime.now(UTC).date().isoformat()
    await write_benchmark_snapshot(snapshot_date, prices)
    return {"date": snapshot_date, "prices": prices}


def run() -> int:
    """Sync entrypoint for the CLI / Cloud Run Job; returns a process exit code."""
    logging.basicConfig(level=logging.INFO)
    try:
        result = asyncio.run(run_snapshot(CoinGeckoMarketData()))
    except Exception:
        logger.exception("benchmark snapshot job failed")
        return 1
    logger.info("benchmark snapshot stored: %s", result)
    return 0


__all__ = ["run", "run_snapshot"]
