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
from ..data.macro import FredMacroData
from ..data.market import CoinGeckoMarketData
from ..data.regime_history import read_regime_history, write_regime_snapshot
from ..data.snapshots import write_benchmark_snapshot
from ..engine.benchmarks import ASSET_COIN_IDS
from ..engine.regime import RegimeEngine

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


async def run_regime_snapshot(engine: RegimeEngine) -> dict[str, object]:
    """Classify today's regime and upsert one row of history.

    Without this the classification is computed, served, and discarded — so no
    accuracy or precision measure is computable, not even retrospectively. This
    is the record every downstream measurement (regime-conditional realized
    returns, transition hit-rate, agreement-score calibration) is measured
    against, so a day lost here is not recoverable later.

    Raises ``RuntimeError`` if the DB or the macro provider is unconfigured, so
    the day is retried rather than recorded wrong (see below).
    """
    if not db.is_configured():
        raise RuntimeError("DATABASE_URL is not configured")

    # REFUSE TO PERSIST A FABRICATED CALL.
    #
    # SignalFetcher resolves each reading as `fetched or default` — a provider outage,
    # an unreachable upstream, or a key that is present but INVALID / EXPIRED /
    # RATE-LIMITED all silently yield neutral priors (real_rates=1.5, dxy=100.0,
    # vix=20.0, credit_spreads=150.0, and defaults for the gold/SPX anchor itself)
    # rather than an error. On the SERVING path that is deliberate: a caller gets a
    # lower-precision answer now and can ask again later.
    #
    # On THIS path it is not. A defaulted row would be written as though it were an
    # observation, fed back as tomorrow's `prior_regime` through the anchor hysteresis,
    # and become part of the permanent record every future accuracy, transition-hit-rate
    # and calibration measure is derived from. A silently fabricated history is strictly
    # worse than no history: after the fact it cannot be told apart from a real one, and
    # measurability is the whole reason this table exists.
    #
    # Checking that a key is CONFIGURED is not sufficient — an expired key produces a
    # complete set of invented readings with no error. So we check the READINGS.
    signals, defaulted = engine.fetcher.fetch_checked()
    if defaulted:
        raise RuntimeError(
            "Refusing to persist a regime call: these decision-critical signals fell "
            f"back to defaults rather than being observed: {sorted(defaulted)}. "
            "Check FRED_API_KEY (valid, not rate-limited) and market-data reachability. "
            "The serving path may degrade; the historical record must not."
        )

    # Feed yesterday's stored call back in as the prior. The anchor hysteresis is
    # only meaningful against a real prior regime, and the engine's in-process
    # value resets on every Cloud Run cold start — the stored history is the only
    # durable source of "what we said last time".
    previous = await read_regime_history(limit=1)
    prior_regime = previous[-1]["regime"] if previous else None

    result = engine.classify(signals, prior_regime=prior_regime).to_dict()
    snapshot_date = datetime.now(UTC).date().isoformat()
    await write_regime_snapshot(
        snapshot_date,
        regime=str(result["regime"]),
        confidence_score=int(result["confidence_score"]),
        signals=dict(result["signals"]),
        signal_statuses=list(result["signal_statuses"]),
        rationale=result.get("rationale"),
        as_of=result.get("as_of"),
    )
    return {
        "date": snapshot_date,
        "regime": result["regime"],
        "confidence_score": result["confidence_score"],
    }


def run() -> int:
    """Sync entrypoint for the CLI / Cloud Run Job; returns a process exit code.

    Runs both snapshots INDEPENDENTLY: a failure in one must not cost us the
    other day's record. Either failing exits non-zero so the scheduler retries;
    both writes upsert on the day, so a retry is safe.
    """
    logging.basicConfig(level=logging.INFO)

    # httpx logs the FULL request URL at INFO ("HTTP Request: GET <url> ..."), and
    # some upstreams take their credential in the QUERY STRING rather than a header.
    # basicConfig(INFO) above raises the ROOT level, which switches that logging on —
    # so the job must pin httpx back down or it writes provider keys into the log
    # sink. (The web service is unaffected: uvicorn's log config leaves httpx at
    # WARNING. This is specific to a CLI/job entrypoint raising the root level.)
    # Nothing of ours is lost: our own INFO lines still emit, and a failed request
    # still surfaces at WARNING/ERROR.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    exit_code = 0

    try:
        result = asyncio.run(run_snapshot(CoinGeckoMarketData()))
        logger.info("benchmark snapshot stored: %s", result)
    except Exception:
        logger.exception("benchmark snapshot job failed")
        exit_code = 1

    try:
        # Same provider wiring create_app uses, so the persisted call is the one
        # the live /api/regime endpoint would have returned. Imported here (not
        # at module scope) to keep the job's import graph off FastAPI unless the
        # regime leg actually runs.
        from ..app.main import build_market_provider

        engine = RegimeEngine(market_data=build_market_provider(), macro_data=FredMacroData())
        regime_result = asyncio.run(run_regime_snapshot(engine))
        logger.info("regime snapshot stored: %s", regime_result)
    except Exception:
        logger.exception("regime snapshot job failed")
        exit_code = 1

    return exit_code


__all__ = ["run", "run_regime_snapshot", "run_snapshot"]
