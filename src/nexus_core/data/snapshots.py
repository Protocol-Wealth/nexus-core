# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Daily benchmark-price snapshot persistence (asyncpg → nexus-marketdata).

Stores one row per day of raw asset USD prices (BTC/ETH/SOL/USDC). Base-100
return series and compositions are derived on read by ``engine.benchmarks`` from
the stored price history, so the persisted shape stays minimal and the
normalization baseline is simply the earliest stored day.

Idempotent: the table is created on demand (``CREATE TABLE IF NOT EXISTS``) and
writes upsert on ``snapshot_date`` so re-running a day overwrites cleanly. All
functions require ``DATABASE_URL`` (reachable only inside ``pwllc-prod-vpc``).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import asyncpg

from .db import CONNECTION_ERRORS, DatabaseUnavailableError, connect

_SCHEMA = """
CREATE TABLE IF NOT EXISTS benchmark_snapshots (
    snapshot_date DATE PRIMARY KEY,
    prices        JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_UPSERT = """
INSERT INTO benchmark_snapshots (snapshot_date, prices)
VALUES ($1::date, $2::jsonb)
ON CONFLICT (snapshot_date) DO UPDATE SET prices = EXCLUDED.prices
"""

# Most-recent N rows, re-sorted oldest-first (the base-100 derivation needs the
# earliest day at index 0). A plain ``ORDER BY ASC LIMIT`` would freeze on the
# oldest N once the table exceeds the limit.
_SELECT = """
SELECT snapshot_date, prices FROM (
    SELECT snapshot_date, prices FROM benchmark_snapshots
    ORDER BY snapshot_date DESC LIMIT $1
) recent
ORDER BY snapshot_date ASC
"""


async def write_benchmark_snapshot(snapshot_date: str, prices: dict[str, float]) -> None:
    """Upsert one day's asset prices (``snapshot_date`` = ``YYYY-MM-DD``)."""
    # asyncpg's date codec requires a datetime.date, not an ISO string — binding
    # a str raises DataError even with a ::date cast (encode precedes the cast).
    day = date.fromisoformat(snapshot_date)
    conn = await connect()
    try:
        await conn.execute(_SCHEMA)
        await conn.execute(_UPSERT, day, json.dumps(prices))
    finally:
        await conn.close()


async def read_benchmark_snapshots(limit: int = 365) -> list[dict[str, Any]]:
    """Stored daily price rows, oldest first (the most recent ``limit`` days).

    No DDL on this (public, frequent) read path; an absent table — i.e. nothing
    has been written yet — degrades to an empty list. A *configured but
    unreachable* database (the connection itself failing, or dropping mid-query)
    raises :class:`DatabaseUnavailableError` so the route can degrade to 503
    rather than surface an uncaught 500. ``connect()`` is inside the ``try`` for
    exactly this reason.
    """
    conn: asyncpg.Connection | None = None
    try:
        conn = await connect()
        rows = await conn.fetch(_SELECT, max(1, limit))
    except asyncpg.UndefinedTableError:
        return []
    except CONNECTION_ERRORS as exc:
        raise DatabaseUnavailableError("benchmark history is temporarily unavailable") from exc
    finally:
        if conn is not None:
            await conn.close()
    out: list[dict[str, Any]] = []
    for row in rows:
        prices = row["prices"]
        if isinstance(prices, str):  # asyncpg returns JSONB as text by default
            prices = json.loads(prices)
        out.append({"date": row["snapshot_date"].isoformat(), "prices": prices})
    return out


__all__ = ["read_benchmark_snapshots", "write_benchmark_snapshot"]
