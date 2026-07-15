# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the P4 realized-PnL / disposition report (hand-checked fixtures)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from nexus_core.engine.accounting import (
    AssetRef,
    EventKind,
    LedgerEvent,
    LedgerLeg,
    onchain_pnl_report,
)

# 2020-09-13; +100 days -> 2020; +400 days -> 2021
_ACQ = 1_600_000_000
_DAY = 86_400
_DISP_SHORT = _ACQ + 100 * _DAY  # 2020, short-term
_DISP_LONG = _ACQ + 400 * _DAY  # 2021, long-term


def _leg(
    asset_id: str, direction: Literal["in", "out"], amount: str, usd: str | None = None
) -> LedgerLeg:
    return LedgerLeg(
        asset=AssetRef(asset_id=asset_id),
        direction=direction,
        amount=Decimal(amount),
        usd_value=None if usd is None else Decimal(usd),
    )


def _ev(event_id: str, kind: EventKind, ts: int, legs: list[LedgerLeg]) -> LedgerEvent:
    return LedgerEvent(event_id=event_id, account_ref="acct-1", kind=kind, timestamp=ts, legs=legs)


def test_report_summary_and_short_long_split() -> None:
    events = [
        _ev("acq", EventKind.acquire, _ACQ, [_leg("a", "in", "3", "30")]),  # unit $10
        _ev("d1", EventKind.dispose, _DISP_SHORT, [_leg("a", "out", "1", "15")]),  # short, gain 5
        _ev("d2", EventKind.dispose, _DISP_LONG, [_leg("a", "out", "1", "25")]),  # long, gain 15
    ]
    report = onchain_pnl_report(events)

    assert report.method == "fifo"
    assert report.summary.realized_gain_usd == Decimal("20")
    assert report.summary.short_term_gain_usd == Decimal("5")
    assert report.summary.long_term_gain_usd == Decimal("15")
    assert report.summary.proceeds_usd == Decimal("40")
    assert report.summary.cost_basis_usd == Decimal("20")
    assert report.summary.disposal_count == 2
    assert report.summary.incomplete_count == 0
    assert report.summary.complete is True
    assert "tax professional" in report.disclaimer


def test_report_per_year_rollup() -> None:
    events = [
        _ev("acq", EventKind.acquire, _ACQ, [_leg("a", "in", "3", "30")]),
        _ev("d1", EventKind.dispose, _DISP_SHORT, [_leg("a", "out", "1", "15")]),
        _ev("d2", EventKind.dispose, _DISP_LONG, [_leg("a", "out", "1", "25")]),
    ]
    report = onchain_pnl_report(events)
    years = {y.year: y for y in report.by_year}
    assert set(years) == {2020, 2021}
    assert years[2020].realized_gain_usd == Decimal("5")
    assert years[2020].short_term_gain_usd == Decimal("5")
    assert years[2020].long_term_gain_usd == Decimal("0")
    assert years[2021].realized_gain_usd == Decimal("15")
    assert years[2021].long_term_gain_usd == Decimal("15")


def test_report_excludes_incomplete_disposals_and_counts_them() -> None:
    # unpriced acquisition -> the disposal has unknown basis -> excluded from sums
    events = [
        _ev("acq", EventKind.acquire, _ACQ, [_leg("a", "in", "1")]),  # no usd -> basis unknown
        _ev("d1", EventKind.dispose, _DISP_SHORT, [_leg("a", "out", "1", "10")]),
    ]
    report = onchain_pnl_report(events)
    assert report.summary.realized_gain_usd == Decimal("0")  # nothing summable
    assert report.summary.disposal_count == 1
    assert report.summary.incomplete_count == 1
    assert report.summary.complete is False
    assert any("basis unknown" in w for w in report.warnings)
