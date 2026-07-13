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


class _StubFetcher:
    """Stands in for SignalFetcher — reports which readings fell back to defaults."""

    def __init__(self, signals: RegimeSignals, defaulted: frozenset[str]) -> None:
        self._signals = signals
        self._defaulted = defaulted

    def fetch_checked(self) -> tuple[RegimeSignals, frozenset[str]]:
        return self._signals, self._defaulted


class _StubEngine:
    """Stands in for RegimeEngine — classify() returns a fixed result."""

    def __init__(self, result: RegimeResult, *, defaulted: frozenset[str] = frozenset()) -> None:
        self._result = result
        self.seen_prior: str | None = None
        self.seen_signals: RegimeSignals | None = None
        self.fetcher = _StubFetcher(result.signals, defaulted)

    def classify(
        self, signals: RegimeSignals | None = None, *, prior_regime: str | None = None
    ) -> RegimeResult:
        self.seen_signals = signals
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


@pytest.mark.parametrize(
    "defaulted",
    [
        frozenset({"gold_spx_ratio"}),  # the anchor — the signal that DECIDES the regime
        frozenset({"real_rates"}),  # the REPRESSION override
        frozenset({"vix"}),  # the DEFLATION override
        frozenset({"credit_spreads"}),  # the other half of the DEFLATION override
        frozenset({"dxy"}),  # confidence-only, but still part of the stored record
        frozenset({"real_rates", "vix", "credit_spreads"}),  # a dead FRED key
    ],
)
def test_defaulted_reading_refuses_to_write(
    monkeypatch: pytest.MonkeyPatch, defaulted: frozenset[str]
) -> None:
    """Never persist a regime computed from a reading that was not actually observed.

    This is the failure Codex flagged (P1, #246) and it is the one that matters: a
    FRED key that is PRESENT BUT INVALID, expired, or rate-limited produces a full set
    of fabricated readings with NO error, so checking `is_configured()` catches nothing.
    Same for an unreachable market provider — which defaults the gold/SPX anchor itself,
    the one signal that selects the base regime.

    A defaulted row would be written as an observation, fed back as tomorrow's prior
    through the anchor hysteresis, and become part of the permanent record every
    accuracy measure is derived from. Fail loudly; let the scheduler retry.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")

    wrote = False

    async def fake_write(snapshot_date: str, **kwargs: Any) -> None:
        nonlocal wrote
        wrote = True

    monkeypatch.setattr(daily_snapshot, "write_regime_snapshot", fake_write)

    engine = _StubEngine(_result(), defaulted=defaulted)
    with pytest.raises(RuntimeError, match="Refusing to persist"):
        asyncio.run(daily_snapshot.run_regime_snapshot(engine))  # type: ignore[arg-type]

    assert wrote is False, "a defaulted regime call must never reach the history table"


def test_observed_readings_are_the_ones_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    """The job classifies the signals it verified — not a second, unchecked fetch."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg:///x?host=/cloudsql/y")

    async def fake_write(snapshot_date: str, **kwargs: Any) -> None:
        return None

    async def fake_read(limit: int = 1) -> list[dict[str, Any]]:
        return []

    monkeypatch.setattr(daily_snapshot, "write_regime_snapshot", fake_write)
    monkeypatch.setattr(daily_snapshot, "read_regime_history", fake_read)

    engine = _StubEngine(_result())
    asyncio.run(daily_snapshot.run_regime_snapshot(engine))  # type: ignore[arg-type]

    # Checking one set of readings and then classifying a different (re-fetched) set
    # would reintroduce the whole bug.
    assert engine.seen_signals is engine.fetcher.fetch_checked()[0]
