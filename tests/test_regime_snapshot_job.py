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


class _StubMacro:
    def __init__(self, configured: bool = True) -> None:
        self._configured = configured

    def is_configured(self) -> bool:
        return self._configured


class _StubFetcher:
    def __init__(self, macro: _StubMacro | None) -> None:
        self.macro = macro


class _StubEngine:
    """Stands in for RegimeEngine — classify() returns a fixed result."""

    def __init__(self, result: RegimeResult, *, macro: _StubMacro | None = None) -> None:
        self._result = result
        self.seen_prior: str | None = None
        self.fetcher = _StubFetcher(macro if macro is not None else _StubMacro(True))

    def classify(self, *, prior_regime: str | None = None) -> RegimeResult:
        self.seen_prior = prior_regime
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

    async def fake_read(limit: int = 1) -> list[dict[str, Any]]:
        return [{"regime": "TRANSITION"}]  # yesterday's stored call

    monkeypatch.setattr(daily_snapshot, "write_regime_snapshot", fake_write)
    monkeypatch.setattr(daily_snapshot, "read_regime_history", fake_read)

    engine = _StubEngine(_result())
    out = asyncio.run(daily_snapshot.run_regime_snapshot(engine))  # type: ignore[arg-type]

    # yesterday's stored regime is fed back as the prior — this is what makes the
    # anchor hysteresis work across Cloud Run cold starts
    assert engine.seen_prior == "TRANSITION"
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


def test_unconfigured_macro_refuses_to_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never persist a regime computed from default priors.

    SignalFetcher resolves macro signals as ``_fetch_x() or default_x``, so a missing
    FRED key does NOT raise — it silently substitutes neutral priors. On the serving
    path that is an acceptable degradation. Here it would write an invented row as an
    observation, feed it back as tomorrow's prior through the anchor hysteresis, and
    poison the record that every accuracy measure is derived from. Fail loudly instead.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")

    wrote = False

    async def fake_write(snapshot_date: str, **kwargs: Any) -> None:
        nonlocal wrote
        wrote = True

    monkeypatch.setattr(daily_snapshot, "write_regime_snapshot", fake_write)

    engine = _StubEngine(_result(), macro=_StubMacro(configured=False))
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        asyncio.run(daily_snapshot.run_regime_snapshot(engine))  # type: ignore[arg-type]

    assert wrote is False, "a defaulted regime call must never reach the history table"
