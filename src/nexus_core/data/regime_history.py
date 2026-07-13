# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Daily regime-classification persistence (asyncpg → nexus-marketdata).

The regime engine classifies on demand and, until now, the answer was served and
discarded. Nothing was written down, so no accuracy or precision measure was
computable — not even retrospectively, because there was no record of what the
engine said on any given day.

This module writes the daily call down. One row per day: the regime code, the
agreement score, the raw signal readings that produced it, the per-signal
statuses, and the rationale. That record is the precondition for every downstream
measurement — regime-conditional realized returns, transition hit-rate, and a
calibration curve for the agreement score — none of which can be built without a
history to measure against.

Public macro data only: signal readings are market/FRED aggregates. No client
data touches this table.

Idempotent: the table is created on demand (``CREATE TABLE IF NOT EXISTS``) and
writes upsert on ``snapshot_date``, so re-running a day overwrites cleanly. All
functions require ``DATABASE_URL`` (reachable only inside ``pwllc-prod-vpc``).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import asyncpg

from .db import connect

_SCHEMA = """
CREATE TABLE IF NOT EXISTS regime_history (
    snapshot_date    DATE PRIMARY KEY,
    regime           TEXT NOT NULL,
    confidence_score INTEGER NOT NULL,
    signals          JSONB NOT NULL,
    signal_statuses  JSONB NOT NULL,
    rationale        TEXT,
    as_of            DATE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_UPSERT = """
INSERT INTO regime_history (
    snapshot_date, regime, confidence_score, signals, signal_statuses, rationale, as_of
)
VALUES ($1::date, $2, $3, $4::jsonb, $5::jsonb, $6, $7::date)
ON CONFLICT (snapshot_date) DO UPDATE SET
    regime           = EXCLUDED.regime,
    confidence_score = EXCLUDED.confidence_score,
    signals          = EXCLUDED.signals,
    signal_statuses  = EXCLUDED.signal_statuses,
    rationale        = EXCLUDED.rationale,
    as_of            = EXCLUDED.as_of
"""

# Most-recent N rows, re-sorted oldest-first so a caller can read the series
# forward in time (same shape rationale as benchmark_snapshots).
_SELECT = """
SELECT snapshot_date, regime, confidence_score, signals, signal_statuses, rationale, as_of
FROM (
    SELECT snapshot_date, regime, confidence_score, signals, signal_statuses, rationale, as_of
    FROM regime_history
    ORDER BY snapshot_date DESC LIMIT $1
) recent
ORDER BY snapshot_date ASC
"""


async def write_regime_snapshot(
    snapshot_date: str,
    *,
    regime: str,
    confidence_score: int,
    signals: dict[str, Any],
    signal_statuses: list[dict[str, Any]],
    rationale: str | None = None,
    as_of: str | None = None,
) -> None:
    """Upsert one day's regime classification (``snapshot_date`` = ``YYYY-MM-DD``)."""
    # asyncpg's date codec requires datetime.date, not an ISO string (encode
    # precedes the ::date cast) — the benchmark_snapshots precedent.
    day = date.fromisoformat(snapshot_date)
    as_of_day = date.fromisoformat(as_of) if as_of else None
    conn = await connect()
    try:
        await conn.execute(_SCHEMA)
        await conn.execute(
            _UPSERT,
            day,
            regime,
            int(confidence_score),
            json.dumps(signals),
            json.dumps(signal_statuses),
            rationale,
            as_of_day,
        )
    finally:
        await conn.close()


def _as_json(value: Any) -> Any:
    """asyncpg returns JSONB as text by default."""
    return json.loads(value) if isinstance(value, str) else value


async def read_regime_history(limit: int = 365) -> list[dict[str, Any]]:
    """Stored daily regime rows, oldest first (the most recent ``limit`` days).

    No DDL on this (public, frequent) read path; an absent table — i.e. nothing
    has been written yet — degrades to an empty list.
    """
    conn = await connect()
    try:
        rows = await conn.fetch(_SELECT, max(1, limit))
    except asyncpg.UndefinedTableError:
        return []
    finally:
        await conn.close()
    return [
        {
            "date": row["snapshot_date"].isoformat(),
            "regime": row["regime"],
            "confidence_score": row["confidence_score"],
            "signals": _as_json(row["signals"]),
            "signal_statuses": _as_json(row["signal_statuses"]),
            "rationale": row["rationale"],
            "as_of": row["as_of"].isoformat() if row["as_of"] else None,
        }
        for row in rows
    ]


__all__ = ["read_regime_history", "write_regime_snapshot"]
