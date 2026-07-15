# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the P3 FIFO cost-basis engine (hand-checked fixtures)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from nexus_core.engine.accounting import (
    AsOfPriceInput,
    AssetRef,
    BasisOverrideInput,
    EventKind,
    LedgerEvent,
    LedgerLeg,
    compute_cost_basis,
)
from nexus_core.engine.accounting.lots import Lot, LotBook

_DAY = 86_400


def _leg(
    asset_id: str, direction: Literal["in", "out"], amount: str, usd: str | None = None
) -> LedgerLeg:
    return LedgerLeg(
        asset=AssetRef(asset_id=asset_id),
        direction=direction,
        amount=Decimal(amount),
        usd_value=None if usd is None else Decimal(usd),
    )


def _ev(
    event_id: str, kind: EventKind, ts: int, legs: list[LedgerLeg], account_ref: str = "acct-1"
) -> LedgerEvent:
    return LedgerEvent(
        event_id=event_id, account_ref=account_ref, kind=kind, timestamp=ts, legs=legs
    )


# --- LotBook -----------------------------------------------------------------


def _lot(asset_id: str, qty: str, unit: str | None, at: int) -> Lot:
    return Lot(
        asset_id=asset_id,
        quantity=Decimal(qty),
        unit_cost_usd=None if unit is None else Decimal(unit),
        acquired_at=at,
        basis_source="test",
    )


def test_lotbook_consumes_fifo_and_reports_shortfall() -> None:
    book = LotBook()
    book.add(_lot("A", "1", "10", at=1))
    book.add(_lot("A", "1", "20", at=2))
    matched, shortfall = book.consume("A", Decimal("1.5"))
    # oldest lot fully (1 @ 10), then 0.5 of the next (@ 20)
    assert [(str(c.quantity), str(c.lot.unit_cost_usd)) for c in matched] == [("1", "10"), ("0.5", "20")]
    assert shortfall == 0
    # 0.5 of the @20 lot remains
    remaining = book.open_lots()
    assert len(remaining) == 1
    assert remaining[0].quantity == Decimal("0.5")


def test_lotbook_shortfall_when_over_consumed() -> None:
    book = LotBook()
    book.add(_lot("A", "3", "10", at=1))
    matched, shortfall = book.consume("A", Decimal("5"))
    assert sum(c.quantity for c in matched) == Decimal("3")
    assert shortfall == Decimal("2")
    assert book.open_lots() == []


# --- compute_cost_basis: the worked fixture ----------------------------------


def test_full_lifecycle_fifo_deposit_basis_and_override() -> None:
    events = [
        _ev("e1", EventKind.acquire, 100, [_leg("usdc", "in", "1000", "1000")]),
        _ev("e2", EventKind.swap, 200, [_leg("usdc", "out", "1000", "1000"), _leg("weth", "in", "0.5", "1000")]),
        _ev("e3", EventKind.deposit, 300, [_leg("weth", "out", "0.5", "1200"), _leg("vweth", "in", "0.5")]),
        _ev("e4", EventKind.transfer_in, 400, [_leg("btc", "in", "0.1", "4000")]),
    ]
    overrides = [BasisOverrideInput(event_id="e4", cost_basis_usd=Decimal("3000"), acquired_at=50)]
    as_of = [
        AsOfPriceInput(asset_id="vweth", unit_price_usd=Decimal("2500")),
        AsOfPriceInput(asset_id="btc", unit_price_usd=Decimal("45000")),
    ]

    result = compute_cost_basis(events, overrides=overrides, as_of_prices=as_of)

    # open lots: vWETH (deposit basis 1200) + BTC (override basis 3000)
    by_asset = {lot.asset.asset_id: lot for lot in result.open_lots}
    assert set(by_asset) == {"vweth", "btc"}
    assert by_asset["vweth"].cost_basis_usd == Decimal("1200")
    assert by_asset["vweth"].basis_source == "deposit"
    assert by_asset["btc"].cost_basis_usd == Decimal("3000")
    assert by_asset["btc"].basis_source == "override"
    assert by_asset["btc"].acquired_at == 50  # from the override, not the transfer date

    # realized: USDC swap gain 0, WETH deposit gain 200 → total 200
    gains = {d.asset.asset_id: d.realized_gain_usd for d in result.disposals}
    assert gains["usdc"] == Decimal("0")
    assert gains["weth"] == Decimal("200")
    assert result.totals.realized_gain_usd == Decimal("200")

    # unrealized: vWETH 1250-1200=50, BTC 4500-3000=1500 → 1550
    assert by_asset["vweth"].unrealized_pnl_usd == Decimal("50.0")
    assert by_asset["btc"].unrealized_pnl_usd == Decimal("1500.0")
    assert result.totals.open_cost_basis_usd == Decimal("4200")
    assert result.totals.open_unrealized_pnl_usd == Decimal("1550.0")


def test_fifo_realized_gain_consumes_oldest_first() -> None:
    events = [
        _ev("b1", EventKind.acquire, 1, [_leg("a", "in", "1", "10")]),
        _ev("b2", EventKind.acquire, 2, [_leg("a", "in", "1", "20")]),
        _ev("s1", EventKind.dispose, 3, [_leg("a", "out", "1", "30")]),
    ]
    result = compute_cost_basis(events)
    # sold 1 → matched the @10 lot: gain 30-10 = 20
    assert len(result.disposals) == 1
    assert result.disposals[0].cost_basis_usd == Decimal("10")
    assert result.disposals[0].realized_gain_usd == Decimal("20")
    # the @20 lot remains open
    assert [lot.cost_basis_usd for lot in result.open_lots] == [Decimal("20")]


def test_transfer_in_without_override_assumes_market_and_warns() -> None:
    result = compute_cost_basis(
        [_ev("t1", EventKind.transfer_in, 1, [_leg("btc", "in", "0.1", "4000")])]
    )
    lot = result.open_lots[0]
    assert lot.cost_basis_usd == Decimal("4000")
    assert lot.basis_source == "market_on_transfer_assumed"
    assert any("supply an override" in w for w in result.warnings)


def test_unpriced_acquisition_basis_is_none_not_zero() -> None:
    result = compute_cost_basis([_ev("u1", EventKind.acquire, 1, [_leg("x", "in", "1")])])
    assert result.open_lots[0].cost_basis_usd is None
    assert result.totals.open_cost_basis_usd is None  # a total with an unknown is unknown
    assert any("basis unknown" in w for w in result.warnings)


def test_disposal_shortfall_is_flagged_not_fabricated() -> None:
    events = [
        _ev("a1", EventKind.acquire, 1, [_leg("y", "in", "3", "30")]),
        _ev("d1", EventKind.dispose, 2, [_leg("y", "out", "5", "50")]),
    ]
    result = compute_cost_basis(events)
    shortfall = [d for d in result.disposals if d.cost_basis_usd is None]
    assert len(shortfall) == 1
    assert shortfall[0].quantity == Decimal("2")
    assert any("no matching lot" in w for w in result.warnings)


def test_holding_period_term_short_vs_long() -> None:
    short = compute_cost_basis(
        [
            _ev("a", EventKind.acquire, 0, [_leg("z", "in", "1", "10")]),
            _ev("d", EventKind.dispose, 100 * _DAY, [_leg("z", "out", "1", "12")]),
        ]
    )
    assert short.disposals[0].term == "short"
    long_ = compute_cost_basis(
        [
            _ev("a", EventKind.acquire, 0, [_leg("z", "in", "1", "10")]),
            _ev("d", EventKind.dispose, 400 * _DAY, [_leg("z", "out", "1", "12")]),
        ]
    )
    assert long_.disposals[0].term == "long"
