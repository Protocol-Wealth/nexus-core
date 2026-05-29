# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the snapshot DB layer's query binding (fake connection, no live DB).

Regression guard: asyncpg's date codec requires a ``datetime.date``, not an ISO
string — binding a str raises ``DataError`` at runtime even with a ``::date``
cast. These tests assert the bound argument type without needing a database.
"""

from __future__ import annotations

import asyncio
import datetime
import json
from typing import Any

import pytest

from nexus_core.data import snapshots


class _FakeConn:
    def __init__(self, fetch_rows: list[Any] | None = None) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._fetch_rows = fetch_rows or []

    async def execute(self, query: str, *args: Any) -> None:
        self.calls.append((query, args))

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.calls.append((query, args))
        return self._fetch_rows

    async def close(self) -> None:
        pass


def test_write_binds_a_date_object_not_str(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConn()

    async def fake_connect(**_kw: Any) -> _FakeConn:
        return fake

    monkeypatch.setattr(snapshots, "connect", fake_connect)
    asyncio.run(snapshots.write_benchmark_snapshot("2026-05-29", {"BTC": 1.0, "USDC": 1.0}))

    upsert = next(c for c in fake.calls if len(c[1]) == 2)  # the INSERT (2 bound args)
    day, payload = upsert[1]
    assert isinstance(day, datetime.date)  # the bug: was a str → asyncpg DataError
    assert day == datetime.date(2026, 5, 29)
    assert json.loads(payload) == {"BTC": 1.0, "USDC": 1.0}


def test_read_parses_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"snapshot_date": datetime.date(2026, 1, 1), "prices": '{"BTC": 40000, "USDC": 1.0}'},
        {"snapshot_date": datetime.date(2026, 1, 2), "prices": {"BTC": 44000, "USDC": 1.0}},
    ]
    fake = _FakeConn(fetch_rows=rows)

    async def fake_connect(**_kw: Any) -> _FakeConn:
        return fake

    monkeypatch.setattr(snapshots, "connect", fake_connect)
    out = asyncio.run(snapshots.read_benchmark_snapshots(limit=30))
    assert out[0] == {"date": "2026-01-01", "prices": {"BTC": 40000, "USDC": 1.0}}
    assert out[1]["prices"]["BTC"] == 44000  # already-dict JSONB handled too
