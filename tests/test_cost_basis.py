# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hand-checked fixtures for the account-scoped accounting contract v2."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
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
from nexus_core.engine.accounting.lots import Lot, LotBook


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
    assert result.completeness.complete is True
    assert result.completeness.statement_ready is False  # governance review remains required


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
    assert result.disposals[0].acquired_at is None
    assert result.disposals[0].complete is False
    assert result.totals.realized_gain_usd is None

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


def test_report_window_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="greater than start_at"):
        _window(10, 10)


def test_opening_state_replay_uses_versioned_lot_snapshot() -> None:
    opening = OpeningStateInput(
        schema_version="1.0.0",
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


def test_opening_state_must_immediately_precede_report_window() -> None:
    opening = OpeningStateInput(
        schema_version="1.0.0",
        state_ref="opening-stale",
        as_of=8,
        source="private_event_ledger",
        last_verified=date(2026, 7, 16),
        lots=[],
    )
    with pytest.raises(ValueError, match="immediately precede"):
        ReportWindowInput(start_at=10, end_at=20, opening_state=opening)


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
        schema_version="1.0.0",
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
    assert result.methodology.review_status == "pending_governance_review"


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
