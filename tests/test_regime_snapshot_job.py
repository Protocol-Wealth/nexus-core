# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the daily REGIME snapshot leg of the Cloud Run Job (DB write mocked).

The regime classification used to be computed and discarded; these pin that the
job now writes the call down — the record every accuracy measure is derived from.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from nexus_core.engine.regime.signals import RegimeResult, RegimeSignals, SignalStatus
from nexus_core.jobs import daily_snapshot


class _StubEngine:
    """Stands in for RegimeEngine — classify() returns a fixed result."""

    def __init__(self, result: RegimeResult) -> None:
        self._result = result

    def classify(self) -> RegimeResult:
        return self._result


def _result() -> RegimeResult:
    signals = RegimeSignals(
        gold_spx_ratio=0.42,
        gold_spx_200wma=0.40,
        gold_spx_vs_wma="above",
        real_rates=1.8,
        dxy=104.0,
        vix=14.0,
        credit_spreads=95.0,
    )
    statuses = [
        SignalStatus(
            name="Gold/SPX Ratio",
            current_value=0.42,
            threshold_info="< 0.50 → GROWTH",
            status="bullish",
            supports_regime="GROWTH",
        )
    ]
    return RegimeResult(
        regime="GROWTH",
        confidence_score=73,
        days_in_regime=0,
        signals=signals,
        signal_statuses=statuses,
        rationale="Gold/SPX below growth threshold.",
    )


def test_run_regime_snapshot_writes_the_call_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")
    captured: dict[str, Any] = {}

    async def fake_write(snapshot_date: str, **kwargs: Any) -> None:
        captured["date"] = snapshot_date
        captured.update(kwargs)

    monkeypatch.setattr(daily_snapshot, "write_regime_snapshot", fake_write)

    out = asyncio.run(daily_snapshot.run_regime_snapshot(_StubEngine(_result())))  # type: ignore[arg-type]

    assert out["regime"] == "GROWTH"
    assert out["confidence_score"] == 73
    # the persisted row carries the readings that produced the call, so the
    # classification can be re-derived and attributed later
    assert captured["regime"] == "GROWTH"
    assert captured["confidence_score"] == 73
    assert captured["signals"]["gold_spx_ratio"] == 0.42
    assert captured["signal_statuses"][0]["name"] == "Gold/SPX Ratio"
    assert captured["rationale"] == "Gold/SPX below growth threshold."


def test_run_regime_snapshot_no_db_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing DB must raise so the scheduler retries — never silently skip a day."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        asyncio.run(daily_snapshot.run_regime_snapshot(_StubEngine(_result())))  # type: ignore[arg-type]
