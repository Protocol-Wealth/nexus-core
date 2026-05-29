# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Async access to the dedicated market-data Postgres (asyncpg).

nexus-core's public surface is read-only over external APIs; this is the narrow
seam to the private ``nexus-marketdata`` Cloud SQL instance — reachable only
from inside ``pwllc-prod-vpc`` via the Cloud SQL connector socket
(``/cloudsql/<connection-name>``), never from the public internet. It backs
persistence jobs (daily snapshots) and connectivity checks.

Configured by ``DATABASE_URL`` (a ``postgresql+asyncpg://…?host=/cloudsql/…``
socket URL). Absent ⇒ :func:`is_configured` is ``False`` and callers no-op, so
the service runs unchanged without a database.
"""

from __future__ import annotations

import os

import asyncpg

_URL_ENV = "DATABASE_URL"


def database_url() -> str | None:
    """The configured ``DATABASE_URL``, or ``None``."""
    return os.getenv(_URL_ENV) or None


def is_configured() -> bool:
    """Whether a database URL is configured."""
    return database_url() is not None


def _asyncpg_dsn(url: str) -> str:
    """Drop SQLAlchemy's ``+asyncpg`` dialect tag for raw ``asyncpg.connect``."""
    return url.replace("+asyncpg", "", 1)


async def ping(*, timeout: float = 5.0) -> bool:
    """Open a connection and run ``SELECT 1`` — ``True`` on success.

    Best-effort: any connection/protocol failure returns ``False`` rather than
    raising, so a health check never 500s.
    """
    url = database_url()
    if not url:
        return False
    conn = None
    try:
        conn = await asyncpg.connect(_asyncpg_dsn(url), timeout=timeout)
        return bool(await conn.fetchval("SELECT 1") == 1)
    except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError):
        return False
    finally:
        if conn is not None:
            await conn.close()


__all__ = ["database_url", "is_configured", "ping"]
