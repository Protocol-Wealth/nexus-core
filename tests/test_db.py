# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the async DB seam (config + DSN handling; no live connection)."""

from __future__ import annotations

import asyncio

import pytest

from nexus_core.data import db


def test_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db.is_configured() is False
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///marketdata?host=/cloudsql/x")
    assert db.is_configured() is True


def test_asyncpg_dsn_strips_dialect() -> None:
    assert (
        db._asyncpg_dsn("postgresql+asyncpg://u:p@/d?host=/cloudsql/x")
        == "postgresql://u:p@/d?host=/cloudsql/x"
    )
    # Plain URLs are unchanged.
    assert db._asyncpg_dsn("postgresql://u:p@/d") == "postgresql://u:p@/d"


def test_ping_unconfigured_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert asyncio.run(db.ping()) is False
