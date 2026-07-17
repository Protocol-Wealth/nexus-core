# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hand-checked fixtures for the account-scoped accounting contract v2."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from typing import Literal

import pytest

from nexus_core.engine.accounting import (
    AsOfPriceInput,
    AssetRef,
    BasisOverrideInput,
    EventKind,
    FeeAllocation,
    FeePayment,
    LedgerEvent,
    LedgerLeg,
    OpeningLotInput,
    OpeningStateInput,
    ReportWindowInput,
    TaxTreatment,
    TransferTreatment,
    compute_cost_basis,
)
from nexus_core.engine.accounting.lots import Lot, LotBook, exact_decimal_sum


def _ts(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, 12, tzinfo=UTC).timestamp())


def _leg(
    asset_id: str,
    direction: Literal["in", "out"],
    amount: str,
    usd: str | None = None,
    *,
    role: Literal["principal", "fee"] = "principal",
) -> LedgerLeg:
    return LedgerLeg(
        asset=AssetRef(asset_id=asset_id),
        direction=direction,
        amount=Decimal(amount),
        usd_value=None if usd is None else Decimal(usd),
        role=role,
        price_source=None if usd is None else "caller_price",
        price_as_of=None if usd is None else 1,
    )


def _ev(
    event_id: str,
    kind: EventKind,
    ts: int,
    legs: list[LedgerLeg],
    *,
    account_ref: str = "acct-a",
    sequence: int | None = None,
    tx_ref: str | None = None,
    transfer_ref: str | None = None,
    transfer_treatment: TransferTreatment | None = None,
    tax_treatment: TaxTreatment | None = None,
    fee_usd: str | None = None,
    fee_allocation: FeeAllocation | None = None,
    fee_payment: FeePayment | None = None,
) -> LedgerEvent:
    return LedgerEvent(
        event_id=event_id,
        account_ref=account_ref,
        kind=kind,
        timestamp=ts,
        sequence=sequence,
        tx_ref=tx_ref,
        legs=legs,
        transfer_ref=transfer_ref,
        transfer_treatment=transfer_treatment,
        tax_treatment=tax_treatment,
        fee_usd=None if fee_usd is None else Decimal(fee_usd),
        fee_allocation=fee_allocation,
        fee_payment=fee_payment,
    )


def _window(start_at: int, end_at: int) -> ReportWindowInput:
    return ReportWindowInput(start_at=start_at, end_at=end_at, full_history=True)


def _lot(account_ref: str, asset_id: str, qty: str, unit: str, at: int) -> Lot:
    return Lot(
        lot_ref=f"lot-{account_ref}-{at}",
        account_ref=account_ref,
        asset_id=asset_id,
        quantity=Decimal(qty),
        unit_cost_usd=Decimal(unit),
        acquired_at=at,
        basis_source="test",
    )


def test_lotbook_fifo_is_scoped_by_account() -> None:
    book = LotBook()
    book.add(_lot("acct-a", "asset", "1", "10", 1))
    book.add(_lot("acct-b", "asset", "1", "20", 2))

    matched, shortfall = book.consume("acct-b", "asset", Decimal("1"))

    assert shortfall == 0
    assert matched[0].lot.account_ref == "acct-b"
    assert matched[0].lot.unit_cost_usd == Decimal("20")
    assert [(lot.account_ref, lot.quantity) for lot in book.open_lots()] == [
        ("acct-a", Decimal("1"))
    ]


def test_lotbook_reorders_late_arriving_lot_by_original_acquisition() -> None:
    book = LotBook()
    book.add(_lot("acct-a", "asset", "1", "50", 5))
    book.add(_lot("acct-a", "asset", "1", "10", 1))

    matched, shortfall = book.consume("acct-a", "asset", Decimal("1"))

    assert shortfall == 0
    assert matched[0].lot.unit_cost_usd == Decimal("10")


def test_repeated_same_asset_legs_use_intra_event_fifo_order() -> None:
    result = compute_cost_basis(
        [
            _ev(
                "multi-leg-acq",
                EventKind.acquire,
                1,
                [_leg("asset", "in", "1", "10"), _leg("asset", "in", "1", "20")],
            ),
            _ev("disp", EventKind.dispose, 2, [_leg("asset", "out", "1", "30")]),
        ],
        report_window=_window(1, 3),
    )

    assert result.disposals[0].lot_ref == "multi-leg-acq:in:0"
    assert result.disposals[0].cost_basis_usd == Decimal("10")
    assert result.open_lots[0].lot_ref == "multi-leg-acq:in:1"
    assert result.completeness.complete is True


def test_lotbook_rejects_duplicate_lot_refs_across_accounts() -> None:
    book = LotBook()
    lot = _lot("acct-a", "asset", "1", "10", 1)
    book.add(lot)
    with pytest.raises(ValueError, match="duplicate lot_ref"):
        book.add(
            Lot(
                lot_ref=lot.lot_ref,
                account_ref="acct-b",
                asset_id="asset",
                quantity=Decimal("1"),
                unit_cost_usd=Decimal("10"),
                acquired_at=1,
                basis_source="test",
            )
        )


def test_disposal_cannot_consume_another_accounts_lot() -> None:
    result = compute_cost_basis(
        [
            _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
            _ev(
                "disp",
                EventKind.dispose,
                2,
                [_leg("asset", "out", "1", "30")],
                account_ref="acct-b",
            ),
        ],
        report_window=_window(1, 3),
    )

    assert result.disposals[0].account_ref == "acct-b"
    assert result.disposals[0].cost_basis_usd is None
    assert result.open_lots[0].account_ref == "acct-a"
    assert result.open_lots[0].quantity == Decimal("1")
    assert result.completeness.complete is False


def test_same_owner_transfer_preserves_lot_basis_date_and_lineage() -> None:
    acquired = _ts(2023, 1, 1)
    moved = _ts(2023, 6, 1)
    disposed = _ts(2024, 6, 2)
    events = [
        _ev(
            "acq",
            EventKind.acquire,
            acquired,
            [_leg("asset", "in", "2", "20")],
            tx_ref="tx-acq",
        ),
        _ev(
            "move-out",
            EventKind.transfer_out,
            moved,
            [_leg("asset", "out", "1")],
            sequence=0,
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
        ),
        _ev(
            "move-in",
            EventKind.transfer_in,
            moved,
            [_leg("asset", "in", "1")],
            account_ref="acct-b",
            sequence=1,
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
        ),
        _ev(
            "disp",
            EventKind.dispose,
            disposed,
            [_leg("asset", "out", "1", "20")],
            account_ref="acct-b",
            tx_ref="tx-disp",
        ),
    ]

    result = compute_cost_basis(events, report_window=_window(acquired, disposed + 1))

    assert len(result.disposals) == 1
    disposal = result.disposals[0]
    assert disposal.cost_basis_usd == Decimal("10")
    assert disposal.realized_gain_usd == Decimal("10")
    assert disposal.acquired_at == acquired
    assert disposal.term == "long"
    assert disposal.acquisition_event_id == "acq"
    assert disposal.acquisition_tx_ref == "tx-acq"
    assert disposal.disposal_event_id == "disp"
    assert disposal.disposal_tx_ref == "tx-disp"
    assert disposal.lot_ref is not None
    assert disposal.origin_lot_ref == "acq:in:0"
    assert result.completeness.complete is True
    assert result.completeness.statement_ready is True


def test_unmatched_same_owner_transfer_makes_closing_inventory_totals_unknown() -> None:
    result = compute_cost_basis(
        [
            _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
            _ev(
                "move-out",
                EventKind.transfer_out,
                2,
                [_leg("asset", "out", "1")],
                transfer_ref="transfer-1",
                transfer_treatment=TransferTreatment.same_owner,
            ),
        ],
        as_of_prices=[
            AsOfPriceInput(
                asset_id="asset",
                unit_price_usd=Decimal("20"),
                source="closing_price",
                as_of=3,
            )
        ],
        report_window=_window(1, 4),
    )

    assert result.open_lots == []
    assert result.totals.open_cost_basis_usd is None
    assert result.totals.open_market_value_usd is None
    assert result.totals.open_unrealized_pnl_usd is None
    assert result.totals.realized_gain_usd == Decimal("0")
    assert result.coverage.unresolved_transfer_count == 1
    assert "unmatched_transfer_out" in {gap.code for gap in result.completeness.gaps}


def test_chained_same_owner_transfer_preserves_root_lot_lineage() -> None:
    events = [
        _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
        _ev(
            "move-1-out",
            EventKind.transfer_out,
            2,
            [_leg("asset", "out", "1")],
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
        ),
        _ev(
            "move-1-in",
            EventKind.transfer_in,
            3,
            [_leg("asset", "in", "1")],
            account_ref="acct-b",
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
        ),
        _ev(
            "move-2-out",
            EventKind.transfer_out,
            4,
            [_leg("asset", "out", "1")],
            account_ref="acct-b",
            transfer_ref="transfer-2",
            transfer_treatment=TransferTreatment.same_owner,
        ),
        _ev(
            "move-2-in",
            EventKind.transfer_in,
            5,
            [_leg("asset", "in", "1")],
            account_ref="acct-c",
            transfer_ref="transfer-2",
            transfer_treatment=TransferTreatment.same_owner,
        ),
    ]

    result = compute_cost_basis(events, report_window=_window(1, 6))

    assert result.open_lots[0].account_ref == "acct-c"
    assert result.open_lots[0].origin_lot_ref == "acq:in:0"
    assert result.open_lots[0].acquisition_event_id == "acq"


def test_same_owner_transfer_reorders_destination_fifo_by_original_date() -> None:
    events = [
        _ev("old-acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
        _ev(
            "new-acq",
            EventKind.acquire,
            5,
            [_leg("asset", "in", "1", "50")],
            account_ref="acct-b",
        ),
        _ev(
            "move-out",
            EventKind.transfer_out,
            10,
            [_leg("asset", "out", "1")],
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
        ),
        _ev(
            "move-in",
            EventKind.transfer_in,
            11,
            [_leg("asset", "in", "1")],
            account_ref="acct-b",
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
        ),
        _ev(
            "dispose",
            EventKind.dispose,
            20,
            [_leg("asset", "out", "1", "100")],
            account_ref="acct-b",
        ),
    ]

    result = compute_cost_basis(events, report_window=_window(1, 21))

    assert result.disposals[0].acquisition_event_id == "old-acq"
    assert result.disposals[0].cost_basis_usd == Decimal("10")
    assert result.disposals[0].realized_gain_usd == Decimal("90")
    assert result.completeness.complete is True


def test_same_owner_transfer_rejects_identical_source_and_destination_account() -> None:
    events = [
        _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
        _ev(
            "move-out",
            EventKind.transfer_out,
            2,
            [_leg("asset", "out", "1")],
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
        ),
        _ev(
            "move-in",
            EventKind.transfer_in,
            3,
            [_leg("asset", "in", "1")],
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
        ),
    ]
    with pytest.raises(ValueError, match="source and destination account_ref must differ"):
        compute_cost_basis(events)


def test_unmatched_transfer_in_never_uses_market_as_original_basis() -> None:
    events = [
        _ev(
            "move-in",
            EventKind.transfer_in,
            1,
            [_leg("asset", "in", "1", "100")],
            transfer_ref="transfer-1",
            transfer_treatment=TransferTreatment.same_owner,
        ),
        _ev("disp", EventKind.dispose, 2, [_leg("asset", "out", "1", "150")]),
    ]

    result = compute_cost_basis(events, report_window=_window(1, 3))

    assert result.disposals[0].cost_basis_usd is None
    assert result.disposals[0].realized_gain_usd is None
    assert result.completeness.complete is False
    assert "unmatched_transfer_in" in {gap.code for gap in result.completeness.gaps}
    assert result.coverage.unresolved_transfer_count == 1


def test_paired_transfer_source_shortfall_is_counted_as_unresolved() -> None:
    result = compute_cost_basis(
        [
            _ev(
                "move-out",
                EventKind.transfer_out,
                1,
                [_leg("asset", "out", "1")],
                transfer_ref="transfer-1",
                transfer_treatment=TransferTreatment.same_owner,
            ),
            _ev(
                "move-in",
                EventKind.transfer_in,
                2,
                [_leg("asset", "in", "1")],
                account_ref="acct-b",
                transfer_ref="transfer-1",
                transfer_treatment=TransferTreatment.same_owner,
            ),
        ],
        report_window=_window(1, 3),
    )

    assert result.coverage.unresolved_transfer_count == 1
    assert "transfer_source_shortfall" in {gap.code for gap in result.completeness.gaps}


def test_missing_transfer_ref_has_specific_gap_and_coverage() -> None:
    result = compute_cost_basis(
        [
            _ev(
                "move-in",
                EventKind.transfer_in,
                1,
                [_leg("asset", "in", "1")],
                transfer_treatment=TransferTreatment.same_owner,
            )
        ],
        report_window=_window(1, 2),
    )

    codes = {gap.code for gap in result.completeness.gaps}
    assert "missing_transfer_ref" in codes
    assert "unresolved_transfer_treatment" not in codes
    assert result.coverage.unresolved_transfer_count == 1


def test_same_owner_transfer_override_requires_original_date_and_provenance() -> None:
    transfer = _ev(
        "move-in",
        EventKind.transfer_in,
        10,
        [_leg("asset", "in", "1", "100")],
        transfer_ref="transfer-1",
        transfer_treatment=TransferTreatment.same_owner,
    )
    disposal = _ev(
        "disp",
        EventKind.dispose,
        11,
        [_leg("asset", "out", "1", "100")],
    )
    result = compute_cost_basis(
        [transfer, disposal],
        overrides=[BasisOverrideInput(event_id="move-in", cost_basis_usd=Decimal("80"))],
        report_window=_window(10, 12),
    )
    codes = {gap.code for gap in result.completeness.gaps}
    assert "missing_transfer_acquisition_date" in codes
    assert "missing_override_provenance" in codes
    assert "unconfirmed_single_lot_override" in codes
    assert result.disposals[0].acquired_at is None
    assert result.disposals[0].complete is False
    assert result.totals.realized_gain_usd == Decimal("20")

    with pytest.raises(ValueError, match="cannot follow"):
        compute_cost_basis(
            [transfer],
            overrides=[
                BasisOverrideInput(
                    event_id="move-in",
                    cost_basis_usd=Decimal("80"),
                    acquired_at=11,
                )
            ],
        )


def test_single_lot_transfer_override_uses_evidence_not_fake_price_provenance() -> None:
    transfer = _ev(
        "move-in",
        EventKind.transfer_in,
        10,
        [_leg("asset", "in", "1")],
        transfer_ref="transfer-1",
        transfer_treatment=TransferTreatment.same_owner,
    )
    result = compute_cost_basis(
        [transfer],
        overrides=[
            BasisOverrideInput(
                event_id="move-in",
                override_ref="evidence-1",
                origin_lot_ref="origin-1",
                cost_basis_usd=Decimal("80"),
                acquired_at=1,
                acquisition_sequence=0,
                acquisition_event_id="original-acq",
                acquisition_tx_ref="original-tx",
                source="custodian_statement",
                last_verified=date(2026, 7, 16),
                single_lot_assertion=True,
            )
        ],
        report_window=_window(10, 11),
    )

    lot = result.open_lots[0]
    assert lot.basis_evidence_source == "custodian_statement"
    assert lot.basis_price_source is None
    assert lot.basis_price_as_of is None
    assert lot.origin_lot_ref == "origin-1"
    assert lot.acquisition_event_id == "original-acq"
    assert lot.acquisition_tx_ref == "original-tx"
    assert result.completeness.complete is True


def test_event_level_transfer_override_rejects_multiple_assets() -> None:
    transfer = _ev(
        "move-in",
        EventKind.transfer_in,
        10,
        [_leg("asset-a", "in", "1"), _leg("asset-b", "in", "1")],
        transfer_ref="transfer-1",
        transfer_treatment=TransferTreatment.same_owner,
    )
    with pytest.raises(ValueError, match="exactly one principal in leg"):
        compute_cost_basis(
            [transfer],
            overrides=[
                BasisOverrideInput(
                    event_id="move-in",
                    cost_basis_usd=Decimal("80"),
                    acquired_at=1,
                    source="custodian_statement",
                    last_verified=date(2026, 7, 16),
                    single_lot_assertion=True,
                )
            ],
        )


def test_fee_adjustment_and_fee_asset_disposal_are_counted_once_each() -> None:
    events = [
        _ev("acq", EventKind.acquire, 1, [_leg("eth", "in", "1", "100")]),
        _ev(
            "disp",
            EventKind.dispose,
            2,
            [
                _leg("eth", "out", "0.5", "100"),
                _leg("eth", "out", "0.05", "5", role="fee"),
            ],
            fee_usd="5",
            fee_allocation=FeeAllocation.disposition_proceeds,
            fee_payment=FeePayment.digital_asset,
        ),
    ]

    result = compute_cost_basis(events, report_window=_window(1, 3))
    principal = next(d for d in result.disposals if d.disposition_type == "principal")
    fee = next(d for d in result.disposals if d.disposition_type == "fee_asset")

    assert principal.gross_proceeds_usd == Decimal("100")
    assert principal.fee_adjustment_usd == Decimal("5")
    assert principal.proceeds_usd == Decimal("95")
    assert principal.cost_basis_usd == Decimal("50.0")
    assert principal.realized_gain_usd == Decimal("45.0")
    assert principal.fee_allocation == FeeAllocation.disposition_proceeds
    assert principal.fee_payment == FeePayment.digital_asset
    assert fee.proceeds_usd == Decimal("5")
    assert fee.cost_basis_usd == Decimal("5.00")
    assert fee.realized_gain_usd == Decimal("0.00")
    assert result.totals.realized_gain_usd == Decimal("45.00")


def test_fiat_acquisition_fee_capitalizes_without_fee_asset_disposal() -> None:
    result = compute_cost_basis(
        [
            _ev(
                "acq",
                EventKind.acquire,
                1,
                [_leg("asset", "in", "1", "100")],
                fee_usd="5",
                fee_allocation=FeeAllocation.acquisition_basis,
                fee_payment=FeePayment.fiat,
            )
        ],
        report_window=_window(1, 2),
    )
    assert result.open_lots[0].cost_basis_usd == Decimal("105")
    assert result.open_lots[0].acquisition_fee_usd == Decimal("5")
    assert result.disposals == []


def test_authoritative_basis_and_fee_totals_survive_snapshot_replay() -> None:
    first = compute_cost_basis(
        [
            _ev(
                "acq",
                EventKind.acquire,
                1,
                [_leg("asset", "in", "3", "100")],
                fee_usd="1",
                fee_allocation=FeeAllocation.acquisition_basis,
                fee_payment=FeePayment.fiat,
            ),
            _ev("first-disp", EventKind.dispose, 2, [_leg("asset", "out", "1", "50")]),
        ],
        report_window=_window(1, 3),
    )
    carried = first.open_lots[0]
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="rounding-snapshot",
        as_of=3,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref=carried.lot_ref,
                origin_lot_ref=carried.origin_lot_ref,
                account_ref=carried.account_ref,
                asset=carried.asset,
                quantity=carried.quantity,
                cost_basis_usd=carried.cost_basis_usd,
                unit_cost_usd=carried.unit_cost_usd,
                acquisition_fee_usd=carried.acquisition_fee_usd,
                acquired_at=carried.acquired_at,
                acquisition_sequence=carried.acquisition_sequence,
                acquisition_leg_index=carried.acquisition_leg_index,
                basis_source=carried.basis_source,
                acquisition_event_id=carried.acquisition_event_id,
                acquisition_tx_ref=carried.acquisition_tx_ref,
                basis_price_source=carried.basis_price_source,
                basis_price_as_of=carried.basis_price_as_of,
            )
        ],
    )
    second = compute_cost_basis(
        [_ev("second-disp", EventKind.dispose, 4, [_leg("asset", "out", "2", "100")])],
        report_window=ReportWindowInput(start_at=4, end_at=5, opening_state=opening),
    )

    assert first.disposals[0].cost_basis_usd + second.disposals[0].cost_basis_usd == Decimal("101")
    assert first.disposals[0].basis_fee_adjustment_usd + second.disposals[
        0
    ].basis_fee_adjustment_usd == Decimal("1")
    assert second.completeness.complete is True


def test_full_disposal_conserves_non_terminating_unit_basis_exactly() -> None:
    result = compute_cost_basis(
        [
            _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "3", "100")]),
            _ev("disp", EventKind.dispose, 2, [_leg("asset", "out", "3", "150")]),
        ],
        report_window=_window(1, 3),
    )

    assert result.disposals[0].cost_basis_usd == Decimal("100")
    assert result.disposals[0].realized_gain_usd == Decimal("50")
    assert result.completeness.complete is True


def test_fee_without_allocation_or_payment_is_explicitly_incomplete() -> None:
    result = compute_cost_basis(
        [
            _ev(
                "acq",
                EventKind.acquire,
                1,
                [_leg("asset", "in", "1", "100")],
                fee_usd="5",
            )
        ],
        report_window=_window(1, 2),
    )
    codes = {gap.code for gap in result.completeness.gaps}
    assert {"unknown_fee_allocation", "unknown_fee_payment"} <= codes
    assert result.coverage.unresolved_fee_count == 1


def test_fee_allocation_without_fee_usd_is_an_explicit_gap() -> None:
    result = compute_cost_basis(
        [
            _ev(
                "acq",
                EventKind.acquire,
                1,
                [
                    _leg("asset", "in", "1", "100"),
                    _leg("gas", "out", "0.01", "1", role="fee"),
                ],
                fee_allocation=FeeAllocation.acquisition_basis,
                fee_payment=FeePayment.digital_asset,
            )
        ],
        report_window=_window(1, 2),
    )
    assert "missing_fee_usd" in {gap.code for gap in result.completeness.gaps}
    assert result.coverage.unresolved_fee_count == 1


def test_missing_digital_fee_asset_leg_is_an_explicit_gap() -> None:
    result = compute_cost_basis(
        [
            _ev(
                "acq",
                EventKind.acquire,
                1,
                [_leg("asset", "in", "1", "100")],
                fee_usd="5",
                fee_allocation=FeeAllocation.acquisition_basis,
                fee_payment=FeePayment.digital_asset,
            )
        ],
        report_window=_window(1, 2),
    )
    assert result.open_lots[0].cost_basis_usd == Decimal("105")
    assert "missing_fee_asset_leg" in {gap.code for gap in result.completeness.gaps}
    assert result.coverage.unresolved_fee_count == 1
    assert result.completeness.complete is False


def test_unknown_disposition_proceeds_cannot_be_calculation_complete() -> None:
    result = compute_cost_basis(
        [
            _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
            _ev("disp", EventKind.dispose, 2, [_leg("asset", "out", "1")]),
        ],
        report_window=_window(1, 3),
    )
    assert result.disposals[0].complete is False
    assert "proceeds_usd" in result.disposals[0].missing_fields
    assert "unknown_disposition_proceeds" in {gap.code for gap in result.completeness.gaps}
    assert result.completeness.complete is False


@pytest.mark.parametrize(
    ("proceeds", "expected_missing"),
    [
        (
            None,
            [
                "matching_lot",
                "proceeds_usd",
                "cost_basis_usd",
                "acquired_at",
                "proceeds_price_provenance",
            ],
        ),
        ("10", ["matching_lot", "cost_basis_usd", "acquired_at"]),
    ],
)
def test_unmatched_disposition_reports_exact_missing_fields(
    proceeds: str | None,
    expected_missing: list[str],
) -> None:
    result = compute_cost_basis(
        [_ev("disp", EventKind.dispose, 1, [_leg("asset", "out", "1", proceeds)])],
        report_window=_window(1, 2),
    )

    disposal = result.disposals[0]
    assert disposal.missing_fields == expected_missing
    assert "basis_provenance" not in disposal.missing_fields
    assert disposal.complete is False
    assert result.completeness.complete is False


@pytest.mark.parametrize(
    ("disposed_at", "expected"),
    [
        (_ts(2025, 2, 28), "short"),
        (_ts(2025, 3, 1), "long"),
    ],
)
def test_leap_day_holding_term_uses_calendar_anniversary(disposed_at: int, expected: str) -> None:
    acquired_at = _ts(2024, 2, 29)
    result = compute_cost_basis(
        [
            _ev("acq", EventKind.acquire, acquired_at, [_leg("asset", "in", "1", "10")]),
            _ev(
                "disp",
                EventKind.dispose,
                disposed_at,
                [_leg("asset", "out", "1", "20")],
            ),
        ],
        report_window=_window(acquired_at, disposed_at + 1),
    )
    assert result.disposals[0].term == expected


def test_full_history_replay_uses_half_open_end_boundary() -> None:
    result = compute_cost_basis(
        [
            _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "3", "30")]),
            _ev("in-period", EventKind.dispose, 10, [_leg("asset", "out", "1", "20")]),
            _ev("at-end", EventKind.dispose, 20, [_leg("asset", "out", "1", "22")]),
            _ev("post-period", EventKind.dispose, 30, [_leg("asset", "out", "1", "25")]),
        ],
        report_window=_window(5, 20),
    )

    assert [disposal.disposal_event_id for disposal in result.disposals] == ["in-period"]
    assert result.open_lots[0].quantity == Decimal("2")
    assert result.replay.pre_period_event_count == 1
    assert result.replay.in_period_event_count == 1
    assert result.replay.post_period_excluded_count == 2


def test_post_period_events_do_not_require_replay_sequence() -> None:
    result = compute_cost_basis(
        [
            _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
            _ev("future-a", EventKind.acquire, 20, [_leg("asset", "in", "1", "20")]),
            _ev("future-b", EventKind.acquire, 20, [_leg("asset", "in", "1", "30")]),
        ],
        report_window=_window(1, 10),
    )

    assert result.replay.replayed_event_count == 1
    assert result.replay.post_period_excluded_count == 2
    assert result.open_lots[0].quantity == Decimal("1")


def test_quiet_opening_state_period_returns_open_lots() -> None:
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="quiet-opening",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref="quiet-lot",
                account_ref="acct-a",
                asset=AssetRef(asset_id="asset"),
                quantity=Decimal("2"),
                cost_basis_usd=Decimal("20"),
                unit_cost_usd=Decimal("10"),
                acquired_at=1,
                basis_source="replayed_history",
                basis_price_source="historian",
                basis_price_as_of=1,
            )
        ],
    )
    result = compute_cost_basis(
        [],
        as_of_prices=[
            AsOfPriceInput(
                asset_id="asset",
                unit_price_usd=Decimal("15"),
                source="historian",
                as_of=20,
            )
        ],
        report_window=ReportWindowInput(start_at=10, end_at=20, opening_state=opening),
    )

    assert result.replay.in_period_event_count == 0
    assert result.disposals == []
    assert result.open_lots[0].quantity == Decimal("2")
    assert result.open_lots[0].market_value_usd == Decimal("30")


def test_valid_numeric_envelope_extremes_conserve_partial_disposal_basis() -> None:
    opening_basis = Decimal("1e-36")
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="numeric-envelope-opening",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref="numeric-envelope-lot",
                account_ref="acct-a",
                asset=AssetRef(asset_id="asset"),
                quantity=Decimal("9" * 42),
                cost_basis_usd=opening_basis,
                acquired_at=1,
                basis_source="replayed_history",
            )
        ],
    )

    result = compute_cost_basis(
        [_ev("tiny-disposal", EventKind.dispose, 10, [_leg("asset", "out", "1e-36")])],
        report_window=ReportWindowInput(start_at=10, end_at=11, opening_state=opening),
    )

    disposal_basis = result.disposals[0].cost_basis_usd
    remaining_basis = result.open_lots[0].cost_basis_usd
    assert disposal_basis is not None
    assert remaining_basis is not None
    assert exact_decimal_sum((disposal_basis, remaining_basis)) == opening_basis
    replayed = OpeningLotInput(
        lot_ref=result.open_lots[0].lot_ref,
        account_ref=result.open_lots[0].account_ref,
        asset=result.open_lots[0].asset,
        quantity=result.open_lots[0].quantity,
        cost_basis_usd=remaining_basis,
        unit_cost_usd=result.open_lots[0].unit_cost_usd,
        acquired_at=result.open_lots[0].acquired_at,
        basis_source=result.open_lots[0].basis_source,
        acquisition_fee_usd=result.open_lots[0].acquisition_fee_usd,
    )
    assert replayed.cost_basis_usd == remaining_basis


def test_large_valid_acquisition_output_roundtrips_as_opening_lot() -> None:
    result = compute_cost_basis(
        [
            _ev(
                "large-acquisition",
                EventKind.acquire,
                1,
                [
                    LedgerLeg(
                        asset=AssetRef(asset_id="asset"),
                        direction="in",
                        amount=Decimal("1e41"),
                        unit_price_usd=Decimal("1e41"),
                        price_source="caller_price",
                        price_as_of=1,
                    )
                ],
            )
        ],
        report_window=_window(1, 2),
    )
    lot = result.open_lots[0]

    replayed = OpeningLotInput(
        lot_ref=lot.lot_ref,
        account_ref=lot.account_ref,
        asset=lot.asset,
        quantity=lot.quantity,
        cost_basis_usd=lot.cost_basis_usd,
        unit_cost_usd=lot.unit_cost_usd,
        acquired_at=lot.acquired_at,
        basis_source=lot.basis_source,
        acquisition_fee_usd=lot.acquisition_fee_usd,
        basis_price_source=lot.basis_price_source,
        basis_price_as_of=lot.basis_price_as_of,
    )

    assert lot.cost_basis_usd == Decimal("1e82")
    assert replayed.cost_basis_usd == lot.cost_basis_usd


def test_high_precision_unit_price_product_is_exact_and_dual_value_is_accepted() -> None:
    amount = Decimal("12345678901234567890.123456789012345678")
    unit_price = Decimal("98765432109876543210.987654321098765432")
    exact_value = Decimal(
        "1219326311370217952261850327338667885854.747751864349946654322511812221002896"
    )
    leg = LedgerLeg(
        asset=AssetRef(asset_id="asset"),
        direction="in",
        amount=amount,
        unit_price_usd=unit_price,
        usd_value=exact_value,
        price_source="caller_price",
        price_as_of=1,
    )

    result = compute_cost_basis(
        [_ev("precision-acquisition", EventKind.acquire, 1, [leg])],
        report_window=_window(1, 2),
    )

    assert result.open_lots[0].cost_basis_usd == exact_value


def test_partial_disposal_never_overconsumes_authoritative_cost_or_fee_basis() -> None:
    basis = Decimal("0." + "9" * 36)
    fee_basis = Decimal("0." + "3" * 36)
    disposed = Decimal("0." + "9" * 36)
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="rounding-bound-opening",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref="rounding-bound-lot",
                account_ref="acct-a",
                asset=AssetRef(asset_id="asset"),
                quantity=Decimal(1),
                cost_basis_usd=basis,
                acquired_at=1,
                basis_source="replayed_history",
                acquisition_fee_usd=fee_basis,
                basis_evidence_source="custodian_statement",
                basis_last_verified=date(2026, 7, 16),
            )
        ],
    )

    result = compute_cost_basis(
        [_ev("partial", EventKind.dispose, 10, [_leg("asset", "out", str(disposed), "1")])],
        report_window=ReportWindowInput(start_at=10, end_at=11, opening_state=opening),
    )

    disposal = result.disposals[0]
    remaining = result.open_lots[0]
    assert disposal.cost_basis_usd is not None
    assert disposal.cost_basis_usd <= basis
    assert remaining.cost_basis_usd is not None and remaining.cost_basis_usd >= 0
    assert remaining.acquisition_fee_usd >= 0
    assert exact_decimal_sum((disposal.cost_basis_usd, remaining.cost_basis_usd)) == basis
    assert (
        exact_decimal_sum((disposal.basis_fee_adjustment_usd, remaining.acquisition_fee_usd))
        == fee_basis
    )
    assert result.completeness.complete is True


def test_partial_same_owner_transfer_conserves_nonnegative_basis_fragments() -> None:
    basis = Decimal("0." + "9" * 36)
    fee_basis = Decimal("0." + "3" * 36)
    transferred = Decimal("0." + "9" * 36)
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="transfer-rounding-opening",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref="transfer-rounding-lot",
                account_ref="acct-a",
                asset=AssetRef(asset_id="asset"),
                quantity=Decimal(1),
                cost_basis_usd=basis,
                acquired_at=1,
                basis_source="replayed_history",
                acquisition_fee_usd=fee_basis,
                basis_evidence_source="custodian_statement",
                basis_last_verified=date(2026, 7, 16),
            )
        ],
    )
    events = [
        _ev(
            "transfer-out",
            EventKind.transfer_out,
            10,
            [_leg("asset", "out", str(transferred))],
            transfer_ref="transfer-rounding",
            transfer_treatment=TransferTreatment.same_owner,
        ),
        _ev(
            "transfer-in",
            EventKind.transfer_in,
            11,
            [_leg("asset", "in", str(transferred))],
            account_ref="acct-b",
            transfer_ref="transfer-rounding",
            transfer_treatment=TransferTreatment.same_owner,
        ),
    ]

    result = compute_cost_basis(
        events,
        report_window=ReportWindowInput(start_at=10, end_at=12, opening_state=opening),
    )

    assert all((lot.cost_basis_usd or Decimal(0)) >= 0 for lot in result.open_lots)
    assert all(lot.acquisition_fee_usd >= 0 for lot in result.open_lots)
    assert (
        exact_decimal_sum([lot.cost_basis_usd or Decimal(0) for lot in result.open_lots]) == basis
    )
    assert exact_decimal_sum([lot.acquisition_fee_usd for lot in result.open_lots]) == fee_basis


def test_replay_is_independent_of_ambient_decimal_precision() -> None:
    def calculate(precision: int) -> dict[str, object]:
        with localcontext() as context:
            context.prec = precision
            result = compute_cost_basis(
                [
                    _ev("acquire", EventKind.acquire, 1, [_leg("asset", "in", "3", "100")]),
                    _ev("dispose", EventKind.dispose, 2, [_leg("asset", "out", "1", "50")]),
                ],
                report_window=_window(1, 3),
            )
            return result.model_dump(mode="json")

    assert calculate(6) == calculate(28) == calculate(50)


def test_opening_state_preserves_root_lot_lineage_through_transfer() -> None:
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="lineage-opening",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref="period-lot",
                origin_lot_ref="root-lot",
                account_ref="acct-a",
                asset=AssetRef(asset_id="asset"),
                quantity=Decimal("1"),
                cost_basis_usd=Decimal("10"),
                unit_cost_usd=Decimal("10"),
                acquired_at=1,
                basis_source="replayed_history",
                basis_price_source="historian",
                basis_price_as_of=1,
            )
        ],
    )
    result = compute_cost_basis(
        [
            _ev(
                "move-out",
                EventKind.transfer_out,
                10,
                [_leg("asset", "out", "1")],
                transfer_ref="transfer-1",
                transfer_treatment=TransferTreatment.same_owner,
            ),
            _ev(
                "move-in",
                EventKind.transfer_in,
                11,
                [_leg("asset", "in", "1")],
                account_ref="acct-b",
                transfer_ref="transfer-1",
                transfer_treatment=TransferTreatment.same_owner,
            ),
        ],
        report_window=ReportWindowInput(start_at=10, end_at=12, opening_state=opening),
    )

    assert result.open_lots[0].origin_lot_ref == "root-lot"


def test_conflicting_chain_metadata_for_one_asset_id_is_rejected() -> None:
    ethereum = _leg("shared-id", "in", "1", "10").model_copy(
        update={"asset": AssetRef(asset_id="shared-id", chain="ethereum")}
    )
    solana = _leg("shared-id", "in", "1", "20").model_copy(
        update={"asset": AssetRef(asset_id="shared-id", chain="solana")}
    )
    with pytest.raises(ValueError, match="conflicting chain metadata"):
        compute_cost_basis(
            [
                _ev("eth-acq", EventKind.acquire, 1, [ethereum]),
                _ev("sol-acq", EventKind.acquire, 2, [solana]),
            ]
        )


def test_partial_asset_metadata_is_enriched_before_conflict_detection() -> None:
    unknown = _leg("shared-id", "in", "1", "10")
    ethereum = _leg("shared-id", "in", "1", "20").model_copy(
        update={"asset": AssetRef(asset_id="shared-id", chain="Ethereum")}
    )
    solana = _leg("shared-id", "in", "1", "30").model_copy(
        update={"asset": AssetRef(asset_id="shared-id", chain="solana")}
    )
    with pytest.raises(ValueError, match="conflicting chain metadata"):
        compute_cost_basis(
            [
                _ev("unknown-acq", EventKind.acquire, 1, [unknown]),
                _ev("eth-acq", EventKind.acquire, 2, [ethereum]),
                _ev("sol-acq", EventKind.acquire, 3, [solana]),
            ]
        )


def test_ledger_leg_rejects_inconsistent_usd_fields() -> None:
    with pytest.raises(ValueError, match="usd_value must equal"):
        LedgerLeg(
            asset=AssetRef(asset_id="asset"),
            direction="in",
            amount=Decimal("2"),
            unit_price_usd=Decimal("10"),
            usd_value=Decimal("25"),
        )


def test_account_ref_rejects_embedded_wallet_address() -> None:
    with pytest.raises(ValueError, match="must be opaque"):
        _ev(
            "event",
            EventKind.acquire,
            1,
            [_leg("asset", "in", "1")],
            account_ref=f"account:{'0x' + 'a' * 40}",
        )


def test_report_window_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="greater than start_at"):
        _window(10, 10)


def test_opening_state_replay_uses_versioned_lot_snapshot() -> None:
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="opening-1",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref="lot-1",
                account_ref="acct-a",
                asset=AssetRef(asset_id="asset"),
                quantity=Decimal("2"),
                cost_basis_usd=Decimal("20"),
                unit_cost_usd=Decimal("10"),
                acquired_at=1,
                basis_source="replayed_history",
                acquisition_event_id="original-acq",
                acquisition_tx_ref="original-tx",
                basis_price_source="historian",
                basis_price_as_of=1,
            )
        ],
    )
    result = compute_cost_basis(
        [_ev("disp", EventKind.dispose, 10, [_leg("asset", "out", "1", "25")])],
        report_window=ReportWindowInput(start_at=10, end_at=20, opening_state=opening),
    )

    disposal = result.disposals[0]
    assert disposal.cost_basis_usd == Decimal("10")
    assert disposal.realized_gain_usd == Decimal("15")
    assert disposal.lot_ref == "lot-1"
    assert disposal.acquisition_event_id == "original-acq"
    assert result.replay.mode == "opening_state"
    assert result.replay.opening_state_ref == "opening-1"
    assert result.replay.opening_state_basis_method == "fifo"
    assert result.replay.opening_state_basis_method_version == "2.0.0"
    assert result.replay.opening_state_snapshot_complete is True


def test_split_root_opening_fragments_can_consolidate_without_losing_lineage() -> None:
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="split-root",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref=f"fragment-{account}",
                origin_lot_ref="root-lot",
                account_ref=account,
                asset=AssetRef(asset_id="asset"),
                quantity=Decimal("1"),
                cost_basis_usd=Decimal("10"),
                unit_cost_usd=Decimal("10"),
                acquired_at=1,
                acquisition_sequence=0,
                basis_source="market",
                acquisition_event_id="root-acq",
                basis_price_source="historian",
                basis_price_as_of=1,
            )
            for account in ("acct-a", "acct-b")
        ],
    )
    result = compute_cost_basis(
        [
            _ev(
                "a-out",
                EventKind.transfer_out,
                10,
                [_leg("asset", "out", "1")],
                transfer_ref="transfer-a",
                transfer_treatment=TransferTreatment.same_owner,
            ),
            _ev(
                "a-in",
                EventKind.transfer_in,
                11,
                [_leg("asset", "in", "1")],
                account_ref="acct-c",
                transfer_ref="transfer-a",
                transfer_treatment=TransferTreatment.same_owner,
            ),
            _ev(
                "b-out",
                EventKind.transfer_out,
                12,
                [_leg("asset", "out", "1")],
                account_ref="acct-b",
                transfer_ref="transfer-b",
                transfer_treatment=TransferTreatment.same_owner,
            ),
            _ev(
                "b-in",
                EventKind.transfer_in,
                13,
                [_leg("asset", "in", "1")],
                account_ref="acct-c",
                transfer_ref="transfer-b",
                transfer_treatment=TransferTreatment.same_owner,
            ),
            _ev(
                "disp",
                EventKind.dispose,
                14,
                [_leg("asset", "out", "2", "40")],
                account_ref="acct-c",
            ),
        ],
        report_window=ReportWindowInput(start_at=10, end_at=15, opening_state=opening),
    )

    assert sum(item.cost_basis_usd or Decimal(0) for item in result.disposals) == Decimal("20")
    assert {item.origin_lot_ref for item in result.disposals} == {"root-lot"}
    assert result.completeness.complete is True


def test_split_root_opening_fragments_reject_conflicting_invariants() -> None:
    lots = [
        OpeningLotInput(
            lot_ref=f"fragment-{index}",
            origin_lot_ref="root-lot",
            account_ref=f"acct-{index}",
            asset=AssetRef(asset_id="asset"),
            quantity=Decimal("1"),
            cost_basis_usd=Decimal(str(10 + index)),
            unit_cost_usd=Decimal(str(10 + index)),
            acquired_at=1,
            acquisition_sequence=0,
            basis_source="market",
            acquisition_event_id="root-acq",
        )
        for index in range(2)
    ]
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="conflicting-root",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=lots,
    )
    with pytest.raises(ValueError, match="conflicting lot invariants"):
        compute_cost_basis(
            [],
            report_window=ReportWindowInput(start_at=10, end_at=11, opening_state=opening),
        )


def test_runtime_overrides_reject_conflicting_origin_root_across_accounts() -> None:
    events = [
        _ev(
            f"transfer-in-{index}",
            EventKind.transfer_in,
            10 + index,
            [_leg("asset", "in", "1")],
            account_ref=f"acct-{index}",
            transfer_ref=f"transfer-{index}",
            transfer_treatment=TransferTreatment.same_owner,
        )
        for index in range(2)
    ]
    overrides = [
        BasisOverrideInput(
            event_id=f"transfer-in-{index}",
            cost_basis_usd=Decimal(str(10 + index)),
            acquired_at=1 + index,
            acquisition_sequence=index,
            source="verified_custodian_record",
            last_verified=date(2026, 7, 16),
            single_lot_assertion=True,
            origin_lot_ref="shared-root",
        )
        for index in range(2)
    ]

    with pytest.raises(ValueError, match="conflicting lot invariants"):
        compute_cost_basis(
            events,
            overrides=overrides,
            report_window=_window(0, 20),
        )


def test_disposal_uses_canonical_asset_metadata() -> None:
    later_acquisition = _leg("asset", "in", "1", "30").model_copy(
        update={
            "asset": AssetRef(
                asset_id="asset",
                symbol="TOK",
                chain="Ethereum",
                decimals=18,
            )
        }
    )
    result = compute_cost_basis(
        [
            _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
            _ev("disp", EventKind.dispose, 2, [_leg("asset", "out", "1", "20")]),
            _ev("later-acq", EventKind.acquire, 3, [later_acquisition]),
        ],
        report_window=_window(0, 4),
    )

    assert result.disposals[0].asset == AssetRef(
        asset_id="asset",
        symbol="TOK",
        chain="ethereum",
        decimals=18,
    )
    assert result.completeness.complete is True


def test_provenance_and_lineage_strings_reject_whitespace_only_values() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        LedgerLeg(
            asset=AssetRef(asset_id="asset"),
            direction="in",
            amount=Decimal("1"),
            usd_value=Decimal("10"),
            price_source="   ",
            price_as_of=1,
        )

    with pytest.raises(ValueError, match="must not be blank"):
        BasisOverrideInput(
            event_id="transfer-in",
            cost_basis_usd=Decimal("10"),
            acquired_at=1,
            acquisition_sequence=0,
            source="   ",
            last_verified=date(2026, 7, 16),
            single_lot_assertion=True,
            origin_lot_ref="root",
        )

    with pytest.raises(ValueError, match="must not be blank"):
        BasisOverrideInput(
            event_id="transfer-in",
            cost_basis_usd=Decimal("10"),
            acquired_at=1,
            acquisition_sequence=0,
            source="verified_record",
            last_verified=date(2026, 7, 16),
            single_lot_assertion=True,
            origin_lot_ref="   ",
        )


def test_provenance_strings_are_trimmed_before_output() -> None:
    leg = LedgerLeg(
        asset=AssetRef(asset_id=" asset "),
        direction="in",
        amount=Decimal("1"),
        usd_value=Decimal("10"),
        price_source=" caller_price ",
        price_as_of=1,
    )

    assert leg.asset.asset_id == "asset"
    assert leg.price_source == "caller_price"


@pytest.mark.parametrize(
    ("cost_basis", "fee_basis", "unit_cost", "unit_fee", "message"),
    [
        ("10", "11", "10", "1", "fee basis cannot exceed"),
        ("10", "1", "10", "11", "fee basis cannot exceed"),
        ("10", None, None, "11", "fee basis cannot exceed"),
        (None, "11", "10", None, "fee basis cannot exceed"),
    ],
)
def test_opening_fee_component_cannot_exceed_total_basis(
    cost_basis: str | None,
    fee_basis: str | None,
    unit_cost: str | None,
    unit_fee: str | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        OpeningLotInput(
            lot_ref="lot",
            account_ref="acct",
            asset=AssetRef(asset_id="asset"),
            quantity=Decimal("1"),
            cost_basis_usd=None if cost_basis is None else Decimal(cost_basis),
            unit_cost_usd=None if unit_cost is None else Decimal(unit_cost),
            acquired_at=1,
            basis_source="replayed_history",
            acquisition_fee_usd=None if fee_basis is None else Decimal(fee_basis),
            unit_fee_basis_usd=None if unit_fee is None else Decimal(unit_fee),
        )


def test_high_precision_transfer_and_disposals_conserve_authoritative_totals() -> None:
    fee_total = Decimal("15.15384615384615384615384615")
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="precision-opening",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref="precision-lot",
                account_ref="acct-a",
                asset=AssetRef(asset_id="asset", decimals=36),
                quantity=Decimal("2"),
                cost_basis_usd=Decimal("100"),
                unit_cost_usd=Decimal("50"),
                acquired_at=1,
                basis_source="replayed_history",
                acquisition_fee_usd=fee_total,
                basis_price_source="historian",
                basis_price_as_of=1,
            )
        ],
    )
    result = compute_cost_basis(
        [
            _ev(
                "move-out",
                EventKind.transfer_out,
                10,
                [_leg("asset", "out", "0.2")],
                transfer_ref="move",
                transfer_treatment=TransferTreatment.same_owner,
            ),
            _ev(
                "move-in",
                EventKind.transfer_in,
                11,
                [_leg("asset", "in", "0.2")],
                account_ref="acct-b",
                transfer_ref="move",
                transfer_treatment=TransferTreatment.same_owner,
            ),
            _ev(
                "dispose-b",
                EventKind.dispose,
                12,
                [_leg("asset", "out", "0.2", "20")],
                account_ref="acct-b",
            ),
            _ev(
                "dispose-a",
                EventKind.dispose,
                13,
                [_leg("asset", "out", "0.54", "54")],
            ),
        ],
        report_window=ReportWindowInput(start_at=10, end_at=14, opening_state=opening),
    )

    with localcontext() as context:
        context.prec = 100
        fee_fragments = [item.basis_fee_adjustment_usd for item in result.disposals] + [
            item.acquisition_fee_usd for item in result.open_lots
        ]
        basis_fragments = [item.cost_basis_usd or Decimal(0) for item in result.disposals] + [
            item.cost_basis_usd or Decimal(0) for item in result.open_lots
        ]
        quantity_fragments = [item.quantity for item in result.disposals] + [
            item.quantity for item in result.open_lots
        ]
        assert sum(fee_fragments, Decimal(0)) == fee_total
        assert sum(basis_fragments, Decimal(0)) == Decimal("100")
        assert sum(quantity_fragments, Decimal(0)) == Decimal("2")
    assert result.completeness.complete is True


def test_disparate_weight_allocation_conserves_exact_fee_total() -> None:
    fee_total = Decimal("0.000001334703")
    weighted_legs = [
        _leg("large", "in", "1", "364052020385913935429682.4426"),
        _leg("medium", "in", "1", "92353.6659"),
        _leg("small", "in", "1", "313.2506247013814"),
        _leg("tiny", "in", "1", "0.0002217979718"),
        _leg("smaller", "in", "1", "9.620966240763145981324805270E-7"),
    ]
    result = compute_cost_basis(
        [
            _ev(
                "weighted-acquisition",
                EventKind.acquire,
                1,
                weighted_legs,
                fee_usd=str(fee_total),
                fee_allocation=FeeAllocation.acquisition_basis,
                fee_payment=FeePayment.fiat,
            )
        ],
        report_window=_window(0, 2),
    )

    with localcontext() as context:
        context.prec = 100
        assert all(lot.acquisition_fee_usd >= 0 for lot in result.open_lots)
        assert (
            sum(
                (lot.acquisition_fee_usd for lot in result.open_lots),
                Decimal(0),
            )
            == fee_total
        )
    assert result.completeness.complete is True


def test_opening_state_must_immediately_precede_report_window() -> None:
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="opening-stale",
        as_of=8,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[],
    )
    with pytest.raises(ValueError, match="immediately precede"):
        ReportWindowInput(start_at=10, end_at=20, opening_state=opening)


def test_opening_state_requires_current_fifo_method_attestation() -> None:
    with pytest.raises(ValueError, match="2.0.0"):
        OpeningStateInput(
            schema_version="2.0.0",
            basis_method="fifo",
            basis_method_version="1.0.0",  # type: ignore[arg-type]
            snapshot_complete=True,
            state_ref="wrong-method",
            as_of=9,
            source="private_event_ledger",
            last_verified=date(2026, 7, 16),
            lots=[],
        )


def test_legacy_unit_only_opening_basis_is_accepted_but_not_complete() -> None:
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="unit-only",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[
            OpeningLotInput(
                lot_ref="legacy-lot",
                account_ref="acct-a",
                asset=AssetRef(asset_id="asset"),
                quantity=Decimal("1"),
                unit_cost_usd=Decimal("10"),
                acquired_at=1,
                basis_source="market",
                basis_price_source="historian",
                basis_price_as_of=1,
            )
        ],
    )
    result = compute_cost_basis(
        [],
        report_window=ReportWindowInput(start_at=10, end_at=11, opening_state=opening),
    )

    assert result.open_lots[0].cost_basis_usd == Decimal("10")
    assert "missing_opening_total_basis" in {gap.code for gap in result.completeness.gaps}


def test_equal_time_opening_lots_require_explicit_sequence() -> None:
    lots = [
        OpeningLotInput(
            lot_ref=f"lot-{index}",
            account_ref="acct-a",
            asset=AssetRef(asset_id="asset"),
            quantity=Decimal("1"),
            unit_cost_usd=Decimal(str(10 + index)),
            acquired_at=1,
            basis_source="replayed_history",
        )
        for index in range(2)
    ]
    opening = OpeningStateInput(
        schema_version="2.0.0",
        basis_method="fifo",
        basis_method_version="2.0.0",
        snapshot_complete=True,
        state_ref="opening-order",
        as_of=9,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=lots,
    )
    with pytest.raises(ValueError, match="acquisition_sequence"):
        compute_cost_basis(
            [_ev("disp", EventKind.dispose, 10, [_leg("asset", "out", "1", "20")])],
            report_window=ReportWindowInput(start_at=10, end_at=11, opening_state=opening),
        )


def test_duplicate_refs_and_ambiguous_order_are_rejected() -> None:
    duplicate = _ev("same", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")])
    with pytest.raises(ValueError, match="duplicate event_id"):
        compute_cost_basis([duplicate, duplicate])

    with pytest.raises(ValueError, match="unique sequence"):
        compute_cost_basis(
            [
                _ev("a", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
                _ev("b", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
            ]
        )

    transfer = _ev(
        "transfer",
        EventKind.transfer_in,
        2,
        [_leg("asset", "in", "1")],
        transfer_ref="transfer-1",
        transfer_treatment=TransferTreatment.same_owner,
    )
    with pytest.raises(ValueError, match="duplicate override_ref"):
        compute_cost_basis(
            [transfer],
            overrides=[
                BasisOverrideInput(
                    event_id="transfer",
                    override_ref="override-1",
                    cost_basis_usd=Decimal("1"),
                ),
                BasisOverrideInput(
                    event_id="transfer",
                    override_ref="override-1",
                    cost_basis_usd=Decimal("1"),
                ),
            ],
        )


def test_ambiguous_defi_event_fails_closed_unless_explicitly_classified() -> None:
    acquisition = _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")])
    deposit = _ev(
        "deposit",
        EventKind.deposit,
        2,
        [_leg("asset", "out", "1", "15"), _leg("receipt", "in", "1", "15")],
    )
    unresolved = compute_cost_basis([acquisition, deposit], report_window=_window(1, 3))
    assert unresolved.disposals == []
    assert unresolved.coverage.unresolved_event_count == 1
    assert unresolved.completeness.complete is False

    classified = deposit.model_copy(update={"tax_treatment": TaxTreatment.taxable_exchange})
    result = compute_cost_basis([acquisition, classified], report_window=_window(1, 3))
    assert result.disposals[0].realized_gain_usd == Decimal("5")
    assert result.open_lots[0].asset.asset_id == "receipt"


def test_tax_treatment_is_rejected_when_the_event_kind_ignores_it() -> None:
    with pytest.raises(ValueError, match="only valid for ambiguous DeFi events"):
        _ev(
            "disp",
            EventKind.dispose,
            1,
            [_leg("asset", "out", "1", "10")],
            tax_treatment=TaxTreatment.unknown,
        )


def test_as_of_price_lineage_is_carried_to_open_lot() -> None:
    result = compute_cost_basis(
        [_ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")])],
        as_of_prices=[
            AsOfPriceInput(
                asset_id="asset",
                unit_price_usd=Decimal("12"),
                source="historian",
                as_of=1,
            )
        ],
        report_window=_window(1, 2),
    )
    lot = result.open_lots[0]
    assert lot.market_value_usd == Decimal("12")
    assert lot.market_price_source == "historian"
    assert lot.market_price_as_of == 1
    assert result.methodology.method_version == "2.0.0"
    assert result.methodology.review_status == "approved"


def test_as_of_price_accepts_closing_boundary_but_not_later() -> None:
    event = _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")])
    at_close = AsOfPriceInput(
        asset_id="asset",
        unit_price_usd=Decimal("12"),
        source="historian",
        as_of=2,
    )
    result = compute_cost_basis([event], as_of_prices=[at_close], report_window=_window(1, 2))
    assert result.open_lots[0].market_price_as_of == 2

    with pytest.raises(ValueError, match="after report end_at"):
        compute_cost_basis(
            [event],
            as_of_prices=[at_close.model_copy(update={"as_of": 3})],
            report_window=_window(1, 2),
        )


def test_standalone_fee_event_preserves_legacy_no_metadata_shape() -> None:
    result = compute_cost_basis(
        [
            _ev("acq", EventKind.acquire, 1, [_leg("asset", "in", "1", "10")]),
            _ev("fee", EventKind.fee, 2, [_leg("asset", "out", "0.1", "1")]),
        ],
        report_window=_window(1, 3),
    )
    assert result.disposals[0].disposition_type == "fee_asset"
    assert result.disposals[0].realized_gain_usd == Decimal("0.0")


@pytest.mark.parametrize(
    ("allocation", "payment", "message"),
    [
        (FeeAllocation.acquisition_basis, FeePayment.fiat, "fee_allocation='none'"),
        (FeeAllocation.none, FeePayment.fiat, "fee_payment='digital_asset'"),
    ],
)
def test_standalone_fee_event_rejects_contradictory_metadata(
    allocation: FeeAllocation, payment: FeePayment, message: str
) -> None:
    event = _ev(
        "fee",
        EventKind.fee,
        2,
        [_leg("asset", "out", "0.1", "1")],
        fee_usd="1",
        fee_allocation=allocation,
        fee_payment=payment,
    )
    with pytest.raises(ValueError, match=message):
        compute_cost_basis([event])


def test_standalone_fee_event_rejects_mismatched_redundant_usd_value() -> None:
    event = _ev(
        "fee",
        EventKind.fee,
        2,
        [_leg("asset", "out", "0.1", "1", role="fee")],
        fee_usd="2",
        fee_allocation=FeeAllocation.none,
        fee_payment=FeePayment.digital_asset,
    )
    with pytest.raises(ValueError, match="fee legs do not equal fee_usd"):
        compute_cost_basis([event])
