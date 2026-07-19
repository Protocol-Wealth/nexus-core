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

#: Errors that mean a *configured* database is unreachable or failed mid-call
#: (connection refused / reset / timeout, protocol error, mid-query drop) — as
#: opposed to a missing table, which is a distinct, expected "no data yet" state.
#: A configured-but-unreachable Cloud SQL must degrade to 503, never surface as
#: an uncaught 500. Read paths catch this set; ``ping`` uses it too.
CONNECTION_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    asyncpg.PostgresError,
    asyncpg.InterfaceError,
)


class DatabaseUnavailableError(RuntimeError):
    """A configured database was unreachable on a read path.

    Read helpers raise this after catching :data:`CONNECTION_ERRORS`; HTTP
    routes map it to a 503, matching the ``is_configured()`` gate so a momentary
    Cloud SQL outage degrades cleanly instead of propagating an uncaught 500.
    """


def database_url() -> str | None:
    """The configured ``DATABASE_URL``, or ``None``."""
    return os.getenv(_URL_ENV) or None


def is_configured() -> bool:
    """Whether a database URL is configured."""
    return database_url() is not None


def _asyncpg_dsn(url: str) -> str:
    """Drop SQLAlchemy's ``+asyncpg`` dialect tag for raw ``asyncpg.connect``."""
    return url.replace("+asyncpg", "", 1)


async def connect(*, timeout: float = 10.0) -> asyncpg.Connection:
    """Open an asyncpg connection to the configured database.

    Raises ``RuntimeError`` if ``DATABASE_URL`` is unset — callers should gate on
    :func:`is_configured` first. The caller owns closing the connection.
    """
    url = database_url()
    if url is None:
        raise RuntimeError("DATABASE_URL is not configured")
    return await asyncpg.connect(_asyncpg_dsn(url), timeout=timeout)


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
    except CONNECTION_ERRORS:
        return False
    finally:
        if conn is not None:
            await conn.close()


__all__ = [
    "CONNECTION_ERRORS",
    "DatabaseUnavailableError",
    "connect",
    "database_url",
    "is_configured",
    "ping",
]
