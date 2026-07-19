# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the regime-history read path's degrade behavior (fake conn, no DB).

Regression: ``read_regime_history`` opened the connection OUTSIDE the ``try`` and
caught only ``UndefinedTableError``, so a configured-but-unreachable database
propagated an uncaught error (HTTP 500). It now catches the connection-error set
and raises ``DatabaseUnavailableError`` so the route degrades to 503, while a
genuinely absent table still degrades to an empty list.
"""

from __future__ import annotations

import asyncio
import datetime
from typing import Any

import asyncpg
import pytest

from nexus_core.data import regime_history
from nexus_core.data.db import DatabaseUnavailableError


class _FakeConn:
    def __init__(self, fetch_rows: list[Any] | None = None) -> None:
        self._fetch_rows = fetch_rows or []

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        return self._fetch_rows

    async def close(self) -> None:
        pass


def test_read_parses_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "snapshot_date": datetime.date(2026, 1, 1),
            "regime": "GROWTH",
            "confidence_score": 80,
            "signals": '{"dxy": 100.0}',
            "signal_statuses": '[{"name": "dxy", "status": "ok"}]',
            "rationale": "strong growth",
            "as_of": datetime.date(2026, 1, 1),
        }
    ]
    fake = _FakeConn(fetch_rows=rows)

    async def fake_connect(**_kw: Any) -> _FakeConn:
        return fake

    monkeypatch.setattr(regime_history, "connect", fake_connect)
    out = asyncio.run(regime_history.read_regime_history(limit=30))
    assert out[0]["regime"] == "GROWTH"
    assert out[0]["signals"] == {"dxy": 100.0}  # JSONB-as-text parsed


def test_read_absent_table_degrades_to_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    class _MissingTableConn(_FakeConn):
        async def fetch(self, query: str, *args: Any) -> list[Any]:
            raise asyncpg.UndefinedTableError("relation does not exist")

    async def fake_connect(**_kw: Any) -> _MissingTableConn:
        return _MissingTableConn()

    monkeypatch.setattr(regime_history, "connect", fake_connect)
    assert asyncio.run(regime_history.read_regime_history(limit=30)) == []


def test_read_unreachable_db_raises_unavailable_not_500(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_connect(**_kw: Any) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr(regime_history, "connect", fake_connect)
    with pytest.raises(DatabaseUnavailableError):
        asyncio.run(regime_history.read_regime_history(limit=30))


def test_read_mid_query_drop_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class _DroppingConn(_FakeConn):
        async def fetch(self, query: str, *args: Any) -> list[Any]:
            raise asyncpg.InterfaceError("connection was closed")

    async def fake_connect(**_kw: Any) -> _DroppingConn:
        return _DroppingConn()

    monkeypatch.setattr(regime_history, "connect", fake_connect)
    with pytest.raises(DatabaseUnavailableError):
        asyncio.run(regime_history.read_regime_history(limit=30))
