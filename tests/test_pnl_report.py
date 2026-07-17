# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the P4 realized-PnL / disposition report (hand-checked fixtures)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, localcontext
from typing import Literal

from nexus_core.engine.accounting import (
    AssetRef,
    BasisOverrideInput,
    EventKind,
    LedgerEvent,
    LedgerLeg,
    OpeningLotInput,
    OpeningStateInput,
    ReportWindowInput,
    TransferTreatment,
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
        price_source=None if usd is None else "caller_price",
        price_as_of=None if usd is None else 1,
    )


def _ev(event_id: str, kind: EventKind, ts: int, legs: list[LedgerLeg]) -> LedgerEvent:
    return LedgerEvent(event_id=event_id, account_ref="acct-1", kind=kind, timestamp=ts, legs=legs)


def test_report_summary_and_short_long_split() -> None:
    events = [
        _ev("acq", EventKind.acquire, _ACQ, [_leg("a", "in", "3", "30")]),  # unit $10
        _ev("d1", EventKind.dispose, _DISP_SHORT, [_leg("a", "out", "1", "15")]),  # short, gain 5
        _ev("d2", EventKind.dispose, _DISP_LONG, [_leg("a", "out", "1", "25")]),  # long, gain 15
    ]
    report = onchain_pnl_report(
        events,
        report_window=ReportWindowInput(
            start_at=_ACQ,
            end_at=_DISP_LONG + 1,
            full_history=True,
        ),
    )

    assert report.method == "fifo"
    assert report.summary.realized_gain_usd == Decimal("20")
    assert report.summary.short_term_gain_usd == Decimal("5")
    assert report.summary.long_term_gain_usd == Decimal("15")
    assert report.summary.proceeds_usd == Decimal("40")
    assert report.summary.cost_basis_usd == Decimal("20")
    assert report.summary.disposal_count == 2
    assert report.summary.incomplete_count == 0
    assert report.summary.complete is True
    assert report.completeness.complete is True
    assert report.completeness.statement_ready is True
    assert len(report.dispositions) == 2
    assert "tax professional" in report.disclaimer


def test_report_per_year_rollup() -> None:
    events = [
        _ev("acq", EventKind.acquire, _ACQ, [_leg("a", "in", "3", "30")]),
        _ev("d1", EventKind.dispose, _DISP_SHORT, [_leg("a", "out", "1", "15")]),
        _ev("d2", EventKind.dispose, _DISP_LONG, [_leg("a", "out", "1", "25")]),
    ]
    report = onchain_pnl_report(
        events,
        report_window=ReportWindowInput(
            start_at=_ACQ,
            end_at=_DISP_LONG + 1,
            full_history=True,
        ),
    )
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
    report = onchain_pnl_report(
        events,
        report_window=ReportWindowInput(
            start_at=_ACQ,
            end_at=_DISP_SHORT + 1,
            full_history=True,
        ),
    )
    assert report.summary.realized_gain_usd == Decimal("0")  # nothing summable
    assert report.summary.disposal_count == 1
    assert report.summary.incomplete_count == 1
    assert report.summary.complete is False
    assert any("basis unknown" in w for w in report.warnings)


def test_report_keeps_known_numbers_when_only_completeness_metadata_is_missing() -> None:
    events = [
        LedgerEvent(
            event_id="transfer",
            account_ref="acct-1",
            kind=EventKind.transfer_in,
            timestamp=_ACQ,
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
            legs=[_leg("a", "in", "1", "100")],
        ),
        _ev("dispose", EventKind.dispose, _DISP_SHORT, [_leg("a", "out", "1", "100")]),
    ]

    report = onchain_pnl_report(
        events,
        overrides=[BasisOverrideInput(event_id="transfer", cost_basis_usd=Decimal("80"))],
        report_window=ReportWindowInput(
            start_at=_ACQ,
            end_at=_DISP_SHORT + 1,
            full_history=True,
        ),
    )

    assert report.dispositions[0].realized_gain_usd == Decimal("20")
    assert report.dispositions[0].complete is False
    assert report.summary.realized_gain_usd == Decimal("20")
    assert report.summary.proceeds_usd == Decimal("100")
    assert report.summary.cost_basis_usd == Decimal("80")
    assert report.summary.short_term_gain_usd == Decimal("0")
    assert report.summary.long_term_gain_usd == Decimal("0")
    assert report.summary.incomplete_count == 1
    assert report.summary.complete is False


def test_unmatched_transfer_market_value_cannot_make_statement_complete() -> None:
    events = [
        LedgerEvent(
            event_id="transfer",
            account_ref="acct-1",
            kind=EventKind.transfer_in,
            timestamp=_ACQ,
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
            legs=[_leg("a", "in", "1", "10")],
        ),
        _ev("dispose", EventKind.dispose, _DISP_SHORT, [_leg("a", "out", "1", "20")]),
    ]
    report = onchain_pnl_report(
        events,
        report_window=ReportWindowInput(
            start_at=_ACQ,
            end_at=_DISP_SHORT + 1,
            full_history=True,
        ),
    )
    assert report.summary.realized_gain_usd == Decimal("0")
    assert report.summary.complete is False
    assert report.completeness.complete is False
    assert "unmatched_transfer_in" in {gap.code for gap in report.completeness.gaps}


def test_high_precision_pnl_aggregation_is_exact() -> None:
    basis_total = Decimal("15.153846153846153846153846155")
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="pnl-precision",
        as_of=_ACQ - 1,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref="pnl-lot",
                account_ref="acct-1",
                asset=AssetRef(asset_id="asset", decimals=36),
                quantity=Decimal("2"),
                cost_basis_usd=basis_total,
                unit_cost_usd=basis_total / Decimal("2"),
                acquired_at=_ACQ - _DAY,
                basis_source="replayed_history",
                basis_price_source="historian",
                basis_price_as_of=_ACQ - _DAY,
            )
        ],
    )
    events = [
        _ev("dispose-1", EventKind.dispose, _ACQ, [_leg("asset", "out", "0.2", "10")]),
        _ev(
            "dispose-2",
            EventKind.dispose,
            _ACQ + 1,
            [_leg("asset", "out", "0.54", "20")],
        ),
        _ev(
            "dispose-3",
            EventKind.dispose,
            _ACQ + 2,
            [_leg("asset", "out", "1.26", "30")],
        ),
    ]
    report = onchain_pnl_report(
        events,
        report_window=ReportWindowInput(
            start_at=_ACQ,
            end_at=_ACQ + 3,
            opening_state=opening,
        ),
    )

    with localcontext() as context:
        context.prec = 100
        expected_gain = Decimal("60") - basis_total
        assert report.summary.cost_basis_usd == basis_total
        assert report.summary.proceeds_usd == Decimal("60")
        assert report.summary.realized_gain_usd == expected_gain
        assert report.summary.short_term_gain_usd == expected_gain
        assert report.by_year[0].realized_gain_usd == expected_gain
    assert report.summary.complete is True
