# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""FIFO cost-basis engine for the onchain-accounting engine (P3).

Walks a de-identified, priced :class:`EventLedger` in time order and maintains
FIFO tax lots. Acquisitions open lots; disposals consume the oldest lots first
and record realized gain/loss per matched lot fragment. Reports the remaining
open lots (with unrealized PnL vs a caller-supplied as-of price) and the
disposals.

Opening basis, by decision:
- an event that gives up assets (swap / deposit / lp_add / stake) sets the
  received asset's basis to the value given up (**deposit = basis**);
- a plain acquisition uses the market value at acquisition;
- a position transferred in uses a **manual override** (basis + date) when the
  caller supplies one — otherwise the market-on-transfer value, flagged.

UNKNOWN IS NOT ZERO: an unpriced acquisition with no override carries a ``None``
basis all the way through, and a total that includes an unknown component is
reported as ``None`` (incomplete), never a fabricated ``0``. FIFO only in v1
(other methods are a follow-on). Clean-room; no AGPL code.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from .lots import Lot, LotBook
from .models import AsOfPriceInput, AssetRef, BasisOverrideInput, EventKind, LedgerEvent, LedgerLeg

_SECONDS_PER_DAY = 86_400
_LONG_TERM_DAYS = 365
_DEPOSIT_KINDS = (EventKind.deposit, EventKind.lp_add, EventKind.stake)


class CostLot(BaseModel):
    """An open (remaining) tax lot."""

    model_config = ConfigDict(extra="forbid")

    asset: AssetRef
    quantity: Decimal
    cost_basis_usd: Decimal | None
    unit_cost_usd: Decimal | None
    acquired_at: int
    basis_source: str
    market_value_usd: Decimal | None = None
    unrealized_pnl_usd: Decimal | None = None


class DisposalRecord(BaseModel):
    """A realized disposal of one lot fragment (FIFO-matched)."""

    model_config = ConfigDict(extra="forbid")

    asset: AssetRef
    quantity: Decimal
    proceeds_usd: Decimal | None
    cost_basis_usd: Decimal | None
    realized_gain_usd: Decimal | None
    acquired_at: int | None
    disposed_at: int
    holding_days: int | None
    term: str | None  # "short" | "long" | None


class CostBasisTotals(BaseModel):
    """Aggregate figures. A total including an unknown component is ``None``."""

    model_config = ConfigDict(extra="forbid")

    open_cost_basis_usd: Decimal | None
    open_market_value_usd: Decimal | None
    open_unrealized_pnl_usd: Decimal | None
    realized_gain_usd: Decimal | None


class CostBasisResult(BaseModel):
    """The cost-basis engine's output."""

    model_config = ConfigDict(extra="forbid")

    method: str
    open_lots: list[CostLot]
    disposals: list[DisposalRecord]
    totals: CostBasisTotals
    warnings: list[str]


def _leg_usd(leg: LedgerLeg) -> Decimal | None:
    if leg.usd_value is not None:
        return leg.usd_value
    if leg.unit_price_usd is not None:
        return leg.unit_price_usd * leg.amount
    return None


def _term(holding_days: int | None) -> str | None:
    if holding_days is None:
        return None
    return "long" if holding_days > _LONG_TERM_DAYS else "short"


def _sum_opt(values: list[Decimal | None]) -> Decimal | None:
    """Sum, but return ``None`` if any component is unknown (partial != total)."""
    total = Decimal(0)
    for value in values:
        if value is None:
            return None
        total += value
    return total


def _allocate(total: Decimal, legs: list[LedgerLeg]) -> list[Decimal]:
    """Split ``total`` across ``legs`` by USD value, falling back to amount, then
    equal. Returns a list parallel to ``legs``."""
    usds = [_leg_usd(leg) for leg in legs]
    if all(u is not None for u in usds):
        weights = [u for u in usds if u is not None]
        weight_sum = sum(weights, Decimal(0))
        if weight_sum > 0:
            return [total * (w / weight_sum) for w in weights]
    amounts = [leg.amount for leg in legs]
    amount_sum = sum(amounts, Decimal(0))
    if amount_sum > 0:
        return [total * (a / amount_sum) for a in amounts]
    count = len(legs)
    return [total / count for _ in legs] if count else []


def _acquisition_bases(
    ins: list[LedgerLeg],
    outs: list[LedgerLeg],
    total_out_usd: Decimal | None,
    event: LedgerEvent,
    override: BasisOverrideInput | None,
    warnings: list[str],
) -> list[tuple[Decimal | None, str, int]]:
    """For each in-leg, the (basis_total, basis_source, acquired_at)."""
    if not ins:
        return []

    if override is not None:
        acquired_at = override.acquired_at if override.acquired_at is not None else event.timestamp
        alloc = _allocate(override.cost_basis_usd, ins)
        return [(alloc[i], "override", acquired_at) for i in range(len(ins))]

    if outs:
        source = "deposit" if event.kind in _DEPOSIT_KINDS else "cost"
        if total_out_usd is None:
            for leg in ins:
                warnings.append(
                    f"acquisition of {leg.asset.asset_id} in {event.event_id}: "
                    "basis unknown (disposed side unpriced)"
                )
            return [(None, source, event.timestamp) for _ in ins]
        alloc = _allocate(total_out_usd, ins)
        return [(alloc[i], source, event.timestamp) for i in range(len(ins))]

    # in-only: acquire / claim / transfer_in without an override
    result: list[tuple[Decimal | None, str, int]] = []
    for leg in ins:
        usd = _leg_usd(leg)
        if event.kind == EventKind.transfer_in:
            source = "market_on_transfer_assumed"
            if usd is None:
                warnings.append(
                    f"transfer_in of {leg.asset.asset_id} ({event.event_id}): "
                    "basis unknown; supply an override"
                )
            else:
                warnings.append(
                    f"transfer_in of {leg.asset.asset_id} ({event.event_id}): basis assumed = "
                    "market on transfer; supply an override for the original basis"
                )
        else:
            source = "market"
            if usd is None:
                warnings.append(
                    f"acquisition of {leg.asset.asset_id} ({event.event_id}): basis unknown (unpriced)"
                )
        result.append((usd, source, event.timestamp))
    return result


def _record_disposals(
    book: LotBook,
    leg: LedgerLeg,
    proceeds: Decimal | None,
    event: LedgerEvent,
    disposals: list[DisposalRecord],
    warnings: list[str],
) -> None:
    matched, shortfall = book.consume(leg.asset.asset_id, leg.amount)
    for consumed in matched:
        share = (consumed.quantity / leg.amount) if leg.amount > 0 else Decimal(0)
        leg_proceeds = None if proceeds is None else proceeds * share
        basis = (
            None
            if consumed.lot.unit_cost_usd is None
            else consumed.lot.unit_cost_usd * consumed.quantity
        )
        gain = None if (leg_proceeds is None or basis is None) else leg_proceeds - basis
        holding_days = max(0, event.timestamp - consumed.lot.acquired_at) // _SECONDS_PER_DAY
        disposals.append(
            DisposalRecord(
                asset=leg.asset,
                quantity=consumed.quantity,
                proceeds_usd=leg_proceeds,
                cost_basis_usd=basis,
                realized_gain_usd=gain,
                acquired_at=consumed.lot.acquired_at,
                disposed_at=event.timestamp,
                holding_days=holding_days,
                term=_term(holding_days),
            )
        )
    if shortfall > 0:
        share = (shortfall / leg.amount) if leg.amount > 0 else Decimal(0)
        leg_proceeds = None if proceeds is None else proceeds * share
        disposals.append(
            DisposalRecord(
                asset=leg.asset,
                quantity=shortfall,
                proceeds_usd=leg_proceeds,
                cost_basis_usd=None,
                realized_gain_usd=None,
                acquired_at=None,
                disposed_at=event.timestamp,
                holding_days=None,
                term=None,
            )
        )
        warnings.append(
            f"disposed {shortfall} of {leg.asset.asset_id} ({event.event_id}) with no matching "
            "lot (basis unknown)"
        )


def _build_open_lots(
    book: LotBook, price_by_asset: dict[str, Decimal], asset_by_id: dict[str, AssetRef]
) -> list[CostLot]:
    lots: list[CostLot] = []
    for lot in book.open_lots():
        cost_basis = None if lot.unit_cost_usd is None else lot.unit_cost_usd * lot.quantity
        price = price_by_asset.get(lot.asset_id)
        market_value = None if price is None else price * lot.quantity
        unrealized = (
            None if (market_value is None or cost_basis is None) else market_value - cost_basis
        )
        asset = asset_by_id.get(lot.asset_id) or AssetRef(
            asset_id=lot.asset_id, symbol=lot.symbol, chain=lot.chain
        )
        lots.append(
            CostLot(
                asset=asset,
                quantity=lot.quantity,
                cost_basis_usd=cost_basis,
                unit_cost_usd=lot.unit_cost_usd,
                acquired_at=lot.acquired_at,
                basis_source=lot.basis_source,
                market_value_usd=market_value,
                unrealized_pnl_usd=unrealized,
            )
        )
    return lots


def compute_cost_basis(
    events: Sequence[LedgerEvent],
    *,
    overrides: Sequence[BasisOverrideInput] | None = None,
    as_of_prices: Sequence[AsOfPriceInput] | None = None,
    method: str = "fifo",
) -> CostBasisResult:
    """Compute FIFO cost basis + realized/unrealized PnL over a priced ledger."""
    override_by_event = {o.event_id: o for o in (overrides or [])}
    price_by_asset = {p.asset_id: p.unit_price_usd for p in (as_of_prices or [])}
    book = LotBook()
    disposals: list[DisposalRecord] = []
    warnings: list[str] = []
    asset_by_id: dict[str, AssetRef] = {}

    for event in sorted(events, key=lambda e: e.timestamp):
        ins = [leg for leg in event.legs if leg.direction == "in"]
        outs = [leg for leg in event.legs if leg.direction == "out"]
        for leg in event.legs:
            asset_by_id.setdefault(leg.asset.asset_id, leg.asset)

        total_out_usd: Decimal | None = Decimal(0)
        for leg in outs:
            proceeds = _leg_usd(leg)
            if proceeds is None:
                total_out_usd = None
            elif total_out_usd is not None:
                total_out_usd += proceeds
            _record_disposals(book, leg, proceeds, event, disposals, warnings)

        override = override_by_event.get(event.event_id)
        bases = _acquisition_bases(ins, outs, total_out_usd, event, override, warnings)
        for leg, (basis_total, source, acquired_at) in zip(ins, bases, strict=True):
            unit_cost = None if basis_total is None else basis_total / leg.amount
            book.add(
                Lot(
                    asset_id=leg.asset.asset_id,
                    quantity=leg.amount,
                    unit_cost_usd=unit_cost,
                    acquired_at=acquired_at,
                    basis_source=source,
                    symbol=leg.asset.symbol,
                    chain=leg.asset.chain,
                )
            )

    open_lots = _build_open_lots(book, price_by_asset, asset_by_id)
    totals = CostBasisTotals(
        open_cost_basis_usd=_sum_opt([lot.cost_basis_usd for lot in open_lots]),
        open_market_value_usd=_sum_opt([lot.market_value_usd for lot in open_lots]),
        open_unrealized_pnl_usd=_sum_opt([lot.unrealized_pnl_usd for lot in open_lots]),
        realized_gain_usd=_sum_opt([d.realized_gain_usd for d in disposals]),
    )
    return CostBasisResult(
        method=method,
        open_lots=open_lots,
        disposals=disposals,
        totals=totals,
        warnings=warnings,
    )


__all__ = [
    "CostBasisResult",
    "CostBasisTotals",
    "CostLot",
    "DisposalRecord",
    "compute_cost_basis",
]
