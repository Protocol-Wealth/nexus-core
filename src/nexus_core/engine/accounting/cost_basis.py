# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Account-scoped FIFO cost basis with replay, lineage, transfers, and fees.

The engine consumes only de-identified facts. Opaque account, event, transfer,
transaction, lot, and provenance references are carried through the result; no
client identity or wallet-to-client linkage belongs here.

Unknown is never zero. Unresolved transfer/tax/fee treatment, unknown basis,
missing price lineage, and incomplete replay state are structured completeness
gaps. They are not silently converted into statement-ready figures.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .lots import (
    Lot,
    LotBook,
    bounded_decimal_share,
    deterministic_decimal_divide,
    exact_decimal_multiply,
    exact_decimal_subtract,
    exact_decimal_sum,
)
from .models import (
    AsOfPriceInput,
    AssetRef,
    BasisOverrideInput,
    EventKind,
    FeeAllocation,
    FeePayment,
    LedgerEvent,
    LedgerLeg,
    OpeningLotInput,
    ReportWindowInput,
    TaxTreatment,
    TransferTreatment,
)

ACCOUNTING_METHOD_VERSION = "2.0.0"
ACCOUNTING_METHOD_SOURCE = "nexus-core/docs/ONCHAIN-ACCOUNTING.md"
ACCOUNTING_METHOD_LAST_VERIFIED = date(2026, 7, 17)
ACCOUNTING_METHODOLOGY_REVIEW_STATUS: Literal["pending_governance_review", "approved"] = (
    "approved"
)

_AMBIGUOUS_DEFI_KINDS = frozenset(
    {
        EventKind.deposit,
        EventKind.withdraw,
        EventKind.lp_add,
        EventKind.lp_remove,
        EventKind.stake,
        EventKind.unstake,
    }
)

EVENT_TREATMENT_MATRIX: dict[str, str] = {
    EventKind.acquire.value: "acquisition",
    EventKind.dispose.value: "taxable_disposition",
    EventKind.swap.value: "taxable_exchange",
    EventKind.transfer_in.value: "explicit_transfer_treatment",
    EventKind.transfer_out.value: "explicit_transfer_treatment",
    EventKind.deposit.value: "explicit_tax_treatment_required",
    EventKind.withdraw.value: "explicit_tax_treatment_required",
    EventKind.lp_add.value: "explicit_tax_treatment_required",
    EventKind.lp_remove.value: "explicit_tax_treatment_required",
    EventKind.stake.value: "explicit_tax_treatment_required",
    EventKind.unstake.value: "explicit_tax_treatment_required",
    EventKind.claim.value: "income_basis_acquisition",
    EventKind.fee.value: "fee_asset_disposition",
    EventKind.other.value: "unresolved",
}


class MethodologyMetadata(BaseModel):
    """Versioned public methodology provenance."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["fifo"]
    method_version: str
    source: str
    last_verified: date
    review_status: Literal["pending_governance_review", "approved"]
    holding_period_rule: str
    event_treatment: dict[str, str]
    transfer_rule: str
    fee_rule: str


class CalculationGap(BaseModel):
    """One structured reason a result is not statement-complete."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    event_id: str | None = None
    account_ref: str | None = None
    asset_id: str | None = None


class CalculationAssumption(BaseModel):
    """One explicit caller assertion used by the calculation."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    event_id: str | None = None
    transfer_ref: str | None = None


class ReplayMetadata(BaseModel):
    """How the report-period opening state was established."""

    model_config = ConfigDict(extra="forbid")

    replay_version: Literal["1.0.0"]
    mode: Literal["all_events", "full_history", "opening_state"]
    start_at: int | None
    end_at: int | None
    opening_state_ref: str | None
    opening_state_schema_version: str | None
    opening_state_source: str | None
    opening_state_last_verified: date | None
    opening_state_basis_method: str | None
    opening_state_basis_method_version: str | None
    opening_state_snapshot_complete: bool | None
    input_event_count: int
    replayed_event_count: int
    pre_period_event_count: int
    in_period_event_count: int
    post_period_excluded_count: int


class CoverageMetadata(BaseModel):
    """Quantitative coverage for the calculation inputs and outputs."""

    model_config = ConfigDict(extra="forbid")

    account_count: int
    asset_count: int
    open_lot_count: int
    known_basis_open_lot_count: int
    unknown_basis_open_lot_count: int
    disposition_count: int
    complete_disposition_count: int
    incomplete_disposition_count: int
    unresolved_event_count: int
    unresolved_transfer_count: int
    unresolved_fee_count: int


class CalculationCompleteness(BaseModel):
    """Structured calculation completeness and statement-readiness gate."""

    model_config = ConfigDict(extra="forbid")

    complete: bool
    statement_ready: bool
    gap_count: int
    gaps: list[CalculationGap]


class CostLot(BaseModel):
    """An open account-scoped FIFO lot with acquisition lineage."""

    model_config = ConfigDict(extra="forbid")

    lot_ref: str
    account_ref: str
    asset: AssetRef
    quantity: Decimal
    cost_basis_usd: Decimal | None
    unit_cost_usd: Decimal | None
    acquired_at: int | None
    acquisition_sequence: int | None
    acquisition_leg_index: int
    basis_source: str
    basis_override_ref: str | None
    basis_last_verified: date | None
    basis_evidence_source: str | None
    acquisition_fee_usd: Decimal
    acquisition_event_id: str | None
    acquisition_tx_ref: str | None
    origin_lot_ref: str | None
    basis_price_source: str | None
    basis_price_as_of: int | None
    market_value_usd: Decimal | None = None
    unrealized_pnl_usd: Decimal | None = None
    market_price_source: str | None = None
    market_price_as_of: int | None = None


class DisposalRecord(BaseModel):
    """A realized principal or fee-asset disposal of one FIFO lot fragment."""

    model_config = ConfigDict(extra="forbid")

    disposition_ref: str
    disposition_type: Literal["principal", "fee_asset"]
    account_ref: str
    asset: AssetRef
    quantity: Decimal
    gross_proceeds_usd: Decimal | None
    fee_adjustment_usd: Decimal
    proceeds_usd: Decimal | None
    cost_basis_usd: Decimal | None
    realized_gain_usd: Decimal | None
    lot_ref: str | None
    acquisition_event_id: str | None
    acquisition_tx_ref: str | None
    origin_lot_ref: str | None
    disposal_event_id: str
    disposal_tx_ref: str | None
    basis_source: str | None
    basis_override_ref: str | None
    basis_last_verified: date | None
    basis_evidence_source: str | None
    basis_fee_adjustment_usd: Decimal
    basis_price_source: str | None
    basis_price_as_of: int | None
    proceeds_price_source: str | None
    proceeds_price_as_of: int | None
    fee_allocation: FeeAllocation | None
    fee_payment: FeePayment | None
    acquired_at: int | None
    disposed_at: int
    holding_days: int | None
    term: Literal["short", "long"] | None
    complete: bool
    missing_fields: list[str]


class CostBasisTotals(BaseModel):
    """Aggregate figures. A total including an unknown component is ``None``."""

    model_config = ConfigDict(extra="forbid")

    open_cost_basis_usd: Decimal | None
    open_market_value_usd: Decimal | None
    open_unrealized_pnl_usd: Decimal | None
    realized_gain_usd: Decimal | None


class CostBasisResult(BaseModel):
    """The versioned cost-basis engine output."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["fifo"]
    methodology: MethodologyMetadata
    replay: ReplayMetadata
    coverage: CoverageMetadata
    completeness: CalculationCompleteness
    assumptions: list[CalculationAssumption]
    open_lots: list[CostLot]
    disposals: list[DisposalRecord]
    totals: CostBasisTotals
    warnings: list[str]


@dataclass
class _EngineCounts:
    unresolved_event_count: int = 0
    unresolved_fee_count: int = 0
    unresolved_transfer_keys: set[str] = field(default_factory=set)

    def mark_unresolved_transfer(self, event: LedgerEvent) -> None:
        key = event.transfer_ref or f"event:{event.event_id}"
        self.unresolved_transfer_keys.add(key)

    @property
    def unresolved_transfer_count(self) -> int:
        return len(self.unresolved_transfer_keys)


def _leg_usd(leg: LedgerLeg) -> Decimal | None:
    if leg.usd_value is not None:
        return leg.usd_value
    if leg.unit_price_usd is not None:
        return exact_decimal_multiply(leg.unit_price_usd, leg.amount)
    return None


def _sum_opt(values: Sequence[Decimal | None]) -> Decimal | None:
    """Sum values, returning ``None`` if any component is unknown."""
    known: list[Decimal] = []
    for value in values:
        if value is None:
            return None
        known.append(value)
    return exact_decimal_sum(known)


def _allocate_weighted(total: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """Allocate nonnegative shares while preserving the exact input total."""
    if not weights:
        return []
    if total < 0 or any(weight < 0 for weight in weights):
        raise ValueError("weighted allocation requires nonnegative totals and weights")
    weight_sum = exact_decimal_sum(weights)
    if weight_sum <= 0:
        weights = [Decimal(1) for _ in weights]
        weight_sum = Decimal(len(weights))
    remaining_total = total
    remaining_weight = weight_sum
    allocated: list[Decimal] = []
    for weight in weights[:-1]:
        share = (
            Decimal(0)
            if remaining_total == 0 or remaining_weight == 0
            else bounded_decimal_share(remaining_total, weight, remaining_weight)
        )
        share = min(remaining_total, max(Decimal(0), share))
        allocated.append(share)
        remaining_total = exact_decimal_subtract(remaining_total, share)
        remaining_weight = exact_decimal_subtract(remaining_weight, weight)
    allocated.append(remaining_total)
    return allocated


def _allocate(total: Decimal, legs: Sequence[LedgerLeg]) -> list[Decimal]:
    """Allocate a USD total by priced value, then quantity, while conserving it."""
    usds = [_leg_usd(leg) for leg in legs]
    if all(value is not None for value in usds):
        weights = [value for value in usds if value is not None]
        weight_sum = exact_decimal_sum(weights)
        if weight_sum > 0:
            return _allocate_weighted(total, weights)
    quantity_sum = exact_decimal_sum([leg.amount for leg in legs])
    if quantity_sum > 0:
        return _allocate_weighted(total, [leg.amount for leg in legs])
    return _allocate_weighted(total, [Decimal(1) for _ in legs])


def _merge_asset_metadata(assets: dict[str, AssetRef], incoming: AssetRef) -> AssetRef:
    """Merge compatible partial metadata so later conflicts cannot hide behind nulls."""
    prior = assets.get(incoming.asset_id)
    if prior is None:
        assets[incoming.asset_id] = incoming
        return incoming
    for field_name in ("chain", "decimals"):
        old_value = getattr(prior, field_name)
        new_value = getattr(incoming, field_name)
        if old_value is not None and new_value is not None and old_value != new_value:
            raise ValueError(f"conflicting {field_name} metadata for asset_id: {incoming.asset_id}")
    merged = prior.model_copy(
        update={
            "symbol": prior.symbol or incoming.symbol,
            "chain": prior.chain or incoming.chain,
            "decimals": prior.decimals if prior.decimals is not None else incoming.decimals,
        }
    )
    assets[incoming.asset_id] = merged
    return merged


def _one_year_anniversary(value: date) -> date:
    try:
        return value.replace(year=value.year + 1)
    except ValueError:
        # February 29 has no same-numbered anniversary in a non-leap year.
        return value.replace(year=value.year + 1, day=28)


def _holding_period(
    acquired_at: int | None, disposed_at: int
) -> tuple[int | None, Literal["short", "long"] | None]:
    if acquired_at is None:
        return None, None
    if disposed_at < acquired_at:
        raise ValueError("disposal timestamp cannot precede its acquisition timestamp")
    acquired = datetime.fromtimestamp(acquired_at, tz=UTC).date()
    disposed = datetime.fromtimestamp(disposed_at, tz=UTC).date()
    holding_days = (disposed - acquired).days
    term: Literal["short", "long"] = (
        "long" if disposed > _one_year_anniversary(acquired) else "short"
    )
    return holding_days, term


def _methodology(method: str) -> MethodologyMetadata:
    if method != "fifo":
        raise ValueError("only fifo cost basis is supported")
    return MethodologyMetadata(
        method="fifo",
        method_version=ACCOUNTING_METHOD_VERSION,
        source=ACCOUNTING_METHOD_SOURCE,
        last_verified=ACCOUNTING_METHOD_LAST_VERIFIED,
        review_status=ACCOUNTING_METHODOLOGY_REVIEW_STATUS,
        holding_period_rule=(
            "calendar dates; count from the day after acquisition through disposition; "
            "long term only after the one-year anniversary"
        ),
        event_treatment=dict(EVENT_TREATMENT_MATRIX),
        transfer_rule=(
            "same_owner requires an opaque transfer_ref and preserves FIFO lot quantity, "
            "basis, and acquisition date; external or unknown treatment is unresolved"
        ),
        fee_rule=(
            "fee_usd is allocated exactly once to acquisition basis or disposition proceeds; "
            "a digital-asset fee leg is also a separate disposition"
        ),
    )


def _gap(
    gaps: list[CalculationGap],
    code: str,
    message: str,
    *,
    event: LedgerEvent | None = None,
    account_ref: str | None = None,
    asset_id: str | None = None,
) -> None:
    gaps.append(
        CalculationGap(
            code=code,
            message=message,
            event_id=None if event is None else event.event_id,
            account_ref=account_ref if event is None else event.account_ref,
            asset_id=asset_id,
        )
    )


def _validate_inputs(
    events: Sequence[LedgerEvent],
    overrides: Sequence[BasisOverrideInput],
    as_of_prices: Sequence[AsOfPriceInput],
    report_window: ReportWindowInput | None,
) -> None:
    event_by_id: dict[str, LedgerEvent] = {}
    asset_metadata: dict[str, AssetRef] = {}
    by_timestamp: dict[int, list[LedgerEvent]] = {}
    transfer_directions: set[tuple[str, EventKind]] = set()
    for event in events:
        if event.event_id in event_by_id:
            raise ValueError(f"duplicate event_id: {event.event_id}")
        event_by_id[event.event_id] = event
        for leg in event.legs:
            _merge_asset_metadata(asset_metadata, leg.asset)
        # Sequence values exist only to make replay order deterministic. Events
        # outside a bounded report are counted as excluded input, not replayed,
        # so their relative order cannot affect this calculation.
        if report_window is None or event.timestamp < report_window.end_at:
            by_timestamp.setdefault(event.timestamp, []).append(event)
        if event.kind in (EventKind.transfer_in, EventKind.transfer_out) and event.transfer_ref:
            key = (event.transfer_ref, event.kind)
            if key in transfer_directions:
                raise ValueError(
                    f"duplicate {event.kind.value} for transfer_ref: {event.transfer_ref}"
                )
            transfer_directions.add(key)

    for timestamp, group in by_timestamp.items():
        if len(group) < 2:
            continue
        sequences = [event.sequence for event in group]
        if any(sequence is None for sequence in sequences) or len(set(sequences)) != len(group):
            raise ValueError(f"events sharing timestamp {timestamp} require unique sequence values")

    override_refs: set[str] = set()
    override_events: set[str] = set()
    for override in overrides:
        override_ref = override.override_ref or override.event_id
        if override_ref in override_refs:
            raise ValueError(f"duplicate override_ref: {override_ref}")
        if override.event_id in override_events:
            raise ValueError(f"duplicate override for event_id: {override.event_id}")
        override_refs.add(override_ref)
        override_events.add(override.event_id)
        override_event = event_by_id.get(override.event_id)
        if override_event is None:
            raise ValueError(f"orphan basis override: {override.event_id}")
        if override_event.kind != EventKind.transfer_in:
            raise ValueError("basis overrides are accepted only for transfer_in events")
        principal_ins = [
            leg for leg in override_event.legs if leg.role == "principal" and leg.direction == "in"
        ]
        if len(principal_ins) != 1:
            raise ValueError("event-level basis override requires exactly one principal in leg")
        if override.acquired_at is not None and override.acquired_at > override_event.timestamp:
            raise ValueError(f"basis override acquired_at cannot follow event {override.event_id}")

    price_assets: set[str] = set()
    for price in as_of_prices:
        if price.asset_id in price_assets:
            raise ValueError(f"duplicate as_of price for asset_id: {price.asset_id}")
        price_assets.add(price.asset_id)
        if (
            report_window is not None
            and price.as_of is not None
            and price.as_of > report_window.end_at
        ):
            raise ValueError(f"as_of price for {price.asset_id} is after report end_at")

    if report_window is None or report_window.opening_state is None:
        return
    opening_state = report_window.opening_state
    if any(event.timestamp < report_window.start_at for event in events):
        raise ValueError("opening_state replay cannot also include pre-period events")
    lot_refs: set[str] = set()
    opening_order: dict[tuple[str, int], list[OpeningLotInput]] = {}
    roots: dict[str, OpeningLotInput] = {}
    for lot in opening_state.lots:
        if lot.lot_ref in lot_refs:
            raise ValueError(f"duplicate opening lot_ref: {lot.lot_ref}")
        lot_refs.add(lot.lot_ref)
        _merge_asset_metadata(asset_metadata, lot.asset)
        root_ref = lot.origin_lot_ref or lot.lot_ref
        prior_root = roots.get(root_ref)
        if prior_root is None:
            roots[root_ref] = lot
        else:
            invariant_fields = (
                "acquired_at",
                "acquisition_sequence",
                "acquisition_leg_index",
                "unit_cost_usd",
                "basis_source",
                "basis_override_ref",
                "basis_last_verified",
                "basis_evidence_source",
                "unit_fee_basis_usd",
                "acquisition_event_id",
                "acquisition_tx_ref",
                "basis_price_source",
                "basis_price_as_of",
            )
            if prior_root.asset.asset_id != lot.asset.asset_id or any(
                getattr(prior_root, field_name) != getattr(lot, field_name)
                for field_name in invariant_fields
            ):
                raise ValueError(
                    "opening fragments sharing origin_lot_ref have conflicting lot invariants"
                )
            if lot.unit_cost_usd is None:
                raise ValueError(
                    "split opening fragments sharing origin_lot_ref require unit_cost_usd"
                )
        if lot.acquired_at is not None and lot.acquired_at > opening_state.as_of:
            raise ValueError(f"opening lot {lot.lot_ref} was acquired after snapshot as_of")
        if lot.acquired_at is not None:
            opening_key = (lot.asset.asset_id, lot.acquired_at)
            opening_order.setdefault(opening_key, []).append(lot)
    for (asset_id, acquired_at), lots in opening_order.items():
        if len(lots) < 2:
            continue
        for index, lot in enumerate(lots):
            root_ref = lot.origin_lot_ref or lot.lot_ref
            for other in lots[index + 1 :]:
                other_root_ref = other.origin_lot_ref or other.lot_ref
                if root_ref == other_root_ref:
                    continue
                sequence_orders = (
                    lot.acquisition_sequence is not None
                    and other.acquisition_sequence is not None
                    and lot.acquisition_sequence != other.acquisition_sequence
                )
                same_event_leg_orders = (
                    lot.acquisition_event_id is not None
                    and lot.acquisition_event_id == other.acquisition_event_id
                    and lot.acquisition_leg_index != other.acquisition_leg_index
                )
                if not sequence_orders and not same_event_leg_orders:
                    raise ValueError(
                        "opening lots sharing asset/acquired_at require unique "
                        "acquisition_sequence or intra-event leg order values: "
                        f"{asset_id}/{acquired_at}"
                    )


def _event_sort_key(event: LedgerEvent) -> tuple[int, int, str]:
    return (event.timestamp, event.sequence or 0, event.event_id)


def _price_provenance(legs: Sequence[LedgerLeg]) -> tuple[str | None, int | None]:
    if not legs or any(leg.price_source is None or leg.price_as_of is None for leg in legs):
        return None, None
    sources = {leg.price_source for leg in legs}
    timestamps = {leg.price_as_of for leg in legs}
    source = next(iter(sources)) if len(sources) == 1 else "multiple"
    as_of = next(iter(timestamps)) if len(timestamps) == 1 else max(ts for ts in timestamps if ts)
    return source, as_of


def _opening_lot(lot: OpeningLotInput) -> Lot:
    total_basis = (
        lot.cost_basis_usd
        if lot.cost_basis_usd is not None
        else None
        if lot.unit_cost_usd is None
        else exact_decimal_multiply(lot.unit_cost_usd, lot.quantity)
    )
    total_fee_basis = (
        lot.acquisition_fee_usd
        if lot.acquisition_fee_usd is not None
        else exact_decimal_multiply(lot.unit_fee_basis_usd or Decimal(0), lot.quantity)
    )
    return Lot(
        lot_ref=lot.lot_ref,
        account_ref=lot.account_ref,
        asset_id=lot.asset.asset_id,
        quantity=lot.quantity,
        unit_cost_usd=lot.unit_cost_usd,
        acquired_at=lot.acquired_at,
        basis_source=lot.basis_source,
        remaining_cost_basis_usd=total_basis,
        remaining_fee_basis_usd=total_fee_basis,
        acquisition_sequence=lot.acquisition_sequence,
        acquisition_leg_index=lot.acquisition_leg_index,
        basis_override_ref=lot.basis_override_ref,
        basis_last_verified=lot.basis_last_verified,
        basis_evidence_source=lot.basis_evidence_source,
        unit_fee_basis_usd=lot.unit_fee_basis_usd or Decimal(0),
        acquisition_event_id=lot.acquisition_event_id,
        acquisition_tx_ref=lot.acquisition_tx_ref,
        origin_lot_ref=lot.origin_lot_ref,
        basis_price_source=lot.basis_price_source,
        basis_price_as_of=lot.basis_price_as_of,
        symbol=lot.asset.symbol,
        chain=lot.asset.chain,
    )


def _record_disposals(
    book: LotBook,
    *,
    leg: LedgerLeg,
    asset: AssetRef,
    leg_index: int,
    gross_proceeds: Decimal | None,
    fee_adjustment: Decimal,
    event: LedgerEvent,
    disposition_type: Literal["principal", "fee_asset"],
    disposals: list[DisposalRecord],
    gaps: list[CalculationGap],
    warnings: list[str],
) -> None:
    net_proceeds = (
        None if gross_proceeds is None else exact_decimal_subtract(gross_proceeds, fee_adjustment)
    )
    if net_proceeds is not None and net_proceeds < 0:
        raise ValueError(f"fee allocation exceeds proceeds in event {event.event_id}")
    matched, shortfall = book.consume(event.account_ref, leg.asset.asset_id, leg.amount)
    quantities = [consumed.quantity for consumed in matched]
    if shortfall > 0:
        quantities.append(shortfall)
    gross_allocations = (
        None if gross_proceeds is None else _allocate_weighted(gross_proceeds, quantities)
    )
    fee_allocations = _allocate_weighted(fee_adjustment, quantities)
    for fragment_index, consumed in enumerate(matched):
        gross = None if gross_allocations is None else gross_allocations[fragment_index]
        fee = fee_allocations[fragment_index]
        proceeds = None if gross is None else exact_decimal_subtract(gross, fee)
        basis = consumed.cost_basis_usd
        gain = (
            None if proceeds is None or basis is None else exact_decimal_subtract(proceeds, basis)
        )
        holding_days, term = _holding_period(consumed.lot.acquired_at, event.timestamp)
        missing: list[str] = []
        if proceeds is None:
            missing.append("proceeds_usd")
        if basis is None:
            missing.append("cost_basis_usd")
        if consumed.lot.acquired_at is None:
            missing.append("acquired_at")
        if (consumed.lot.basis_price_source is None or consumed.lot.basis_price_as_of is None) and (
            consumed.lot.basis_evidence_source is None or consumed.lot.basis_last_verified is None
        ):
            missing.append("basis_provenance")
        if leg.price_source is None or leg.price_as_of is None:
            missing.append("proceeds_price_provenance")
        complete = not missing
        disposals.append(
            DisposalRecord(
                disposition_ref=(f"{event.event_id}:out:{leg_index}:fragment:{fragment_index}"),
                disposition_type=disposition_type,
                account_ref=event.account_ref,
                asset=asset,
                quantity=consumed.quantity,
                gross_proceeds_usd=gross,
                fee_adjustment_usd=fee,
                proceeds_usd=proceeds,
                cost_basis_usd=basis,
                realized_gain_usd=gain,
                lot_ref=consumed.lot.lot_ref,
                acquisition_event_id=consumed.lot.acquisition_event_id,
                acquisition_tx_ref=consumed.lot.acquisition_tx_ref,
                origin_lot_ref=consumed.lot.origin_lot_ref or consumed.lot.lot_ref,
                disposal_event_id=event.event_id,
                disposal_tx_ref=event.tx_ref,
                basis_source=consumed.lot.basis_source,
                basis_override_ref=consumed.lot.basis_override_ref,
                basis_last_verified=consumed.lot.basis_last_verified,
                basis_evidence_source=consumed.lot.basis_evidence_source,
                basis_fee_adjustment_usd=consumed.fee_basis_usd,
                basis_price_source=consumed.lot.basis_price_source,
                basis_price_as_of=consumed.lot.basis_price_as_of,
                proceeds_price_source=leg.price_source,
                proceeds_price_as_of=leg.price_as_of,
                fee_allocation=event.fee_allocation,
                fee_payment=event.fee_payment,
                acquired_at=consumed.lot.acquired_at,
                disposed_at=event.timestamp,
                holding_days=holding_days,
                term=term,
                complete=complete,
                missing_fields=missing,
            )
        )
    if shortfall <= 0:
        return
    shortfall_index = len(matched)
    gross = None if gross_allocations is None else gross_allocations[shortfall_index]
    fee = fee_allocations[shortfall_index]
    proceeds = None if gross is None else exact_decimal_subtract(gross, fee)
    missing = ["matching_lot"]
    if proceeds is None:
        missing.append("proceeds_usd")
    missing.extend(["cost_basis_usd", "acquired_at"])
    if leg.price_source is None or leg.price_as_of is None:
        missing.append("proceeds_price_provenance")
    disposals.append(
        DisposalRecord(
            disposition_ref=f"{event.event_id}:out:{leg_index}:shortfall",
            disposition_type=disposition_type,
            account_ref=event.account_ref,
            asset=asset,
            quantity=shortfall,
            gross_proceeds_usd=gross,
            fee_adjustment_usd=fee,
            proceeds_usd=proceeds,
            cost_basis_usd=None,
            realized_gain_usd=None,
            lot_ref=None,
            acquisition_event_id=None,
            acquisition_tx_ref=None,
            origin_lot_ref=None,
            disposal_event_id=event.event_id,
            disposal_tx_ref=event.tx_ref,
            basis_source=None,
            basis_override_ref=None,
            basis_last_verified=None,
            basis_evidence_source=None,
            basis_fee_adjustment_usd=Decimal(0),
            basis_price_source=None,
            basis_price_as_of=None,
            proceeds_price_source=leg.price_source,
            proceeds_price_as_of=leg.price_as_of,
            fee_allocation=event.fee_allocation,
            fee_payment=event.fee_payment,
            acquired_at=None,
            disposed_at=event.timestamp,
            holding_days=None,
            term=None,
            complete=False,
            missing_fields=missing,
        )
    )
    message = (
        f"disposed {shortfall} of {leg.asset.asset_id} in account {event.account_ref} "
        f"({event.event_id}) with no matching lot"
    )
    warnings.append(f"{message} (basis unknown)")
    _gap(
        gaps,
        "unmatched_disposition",
        message,
        event=event,
        asset_id=leg.asset.asset_id,
    )


def _add_acquisition_lots(
    book: LotBook,
    *,
    event: LedgerEvent,
    ins: Sequence[tuple[int, LedgerLeg]],
    outs: Sequence[LedgerLeg],
    fee_addition: Decimal,
    override: BasisOverrideInput | None,
    gaps: list[CalculationGap],
    warnings: list[str],
) -> None:
    if not ins:
        return
    in_legs = [leg for _, leg in ins]
    fee_by_leg = (
        _allocate(fee_addition, in_legs) if fee_addition > 0 else [Decimal(0) for _ in in_legs]
    )
    if override is not None:
        if fee_addition:
            raise ValueError("an override and acquisition fee allocation cannot target one event")
        acquired_at = override.acquired_at
        bases: list[Decimal | None] = []
        bases.extend(_allocate(override.cost_basis_usd, in_legs))
        basis_source = "override"
        basis_override_ref = override.override_ref or override.event_id
        basis_last_verified = override.last_verified
        price_source = None
        price_as_of = None
        if acquired_at is None:
            _gap(
                gaps,
                "missing_transfer_acquisition_date",
                "transfer basis override is missing the original acquisition date",
                event=event,
            )
        if override.source is None or override.last_verified is None:
            _gap(
                gaps,
                "missing_override_provenance",
                "basis override requires source and last_verified for statement use",
                event=event,
            )
        if override.single_lot_assertion is not True:
            _gap(
                gaps,
                "unconfirmed_single_lot_override",
                "event-level transfer basis requires an explicit single-original-lot assertion",
                event=event,
            )
        if override.origin_lot_ref is None:
            _gap(
                gaps,
                "missing_override_origin_lot_ref",
                "single-lot transfer basis requires an opaque source-lot reference",
                event=event,
            )
        if override.acquisition_sequence is None:
            _gap(
                gaps,
                "missing_transfer_acquisition_sequence",
                "single-lot transfer basis requires original acquisition order",
                event=event,
            )
    elif outs:
        total_out = _sum_opt([_leg_usd(leg) for leg in outs])
        if total_out is None:
            bases = [None for _ in in_legs]
        else:
            bases = []
            bases.extend(_allocate(exact_decimal_sum((total_out, fee_addition)), in_legs))
        basis_source = "taxable_exchange"
        basis_override_ref = None
        basis_last_verified = None
        price_source, price_as_of = _price_provenance(outs)
    else:
        leg_values = [_leg_usd(leg) for leg in in_legs]
        if fee_addition:
            if any(value is None for value in leg_values):
                bases = [None for _ in in_legs]
            else:
                bases = [
                    exact_decimal_sum((value, fee))
                    for value, fee in zip(leg_values, fee_by_leg, strict=True)
                    if value is not None
                ]
        else:
            bases = leg_values
        basis_source = "income_market" if event.kind == EventKind.claim else "market"
        basis_override_ref = None
        basis_last_verified = None
        price_source = None
        price_as_of = None

    for (leg_index, leg), basis_total, fee_for_leg in zip(ins, bases, fee_by_leg, strict=True):
        if not outs and override is None:
            leg_price_source = leg.price_source
            leg_price_as_of = leg.price_as_of
        else:
            leg_price_source = price_source
            leg_price_as_of = price_as_of
        if basis_total is None:
            message = f"acquisition basis unknown for {leg.asset.asset_id} ({event.event_id})"
            warnings.append(message)
            _gap(gaps, "unknown_basis", message, event=event, asset_id=leg.asset.asset_id)
        leg_evidence_source = override.source if override is not None else None
        if basis_total is not None and (
            (leg_price_source is None or leg_price_as_of is None)
            and (leg_evidence_source is None or basis_last_verified is None)
        ):
            _gap(
                gaps,
                "missing_price_provenance",
                "known acquisition basis is missing price source/as_of",
                event=event,
                asset_id=leg.asset.asset_id,
            )
        book.add(
            Lot(
                lot_ref=f"{event.event_id}:in:{leg_index}",
                account_ref=event.account_ref,
                asset_id=leg.asset.asset_id,
                quantity=leg.amount,
                unit_cost_usd=(
                    None
                    if basis_total is None
                    else deterministic_decimal_divide(basis_total, leg.amount)
                ),
                acquired_at=acquired_at if override is not None else event.timestamp,
                basis_source=basis_source,
                remaining_cost_basis_usd=basis_total,
                remaining_fee_basis_usd=fee_for_leg,
                acquisition_sequence=(
                    override.acquisition_sequence if override is not None else event.sequence
                ),
                acquisition_leg_index=(
                    override.acquisition_leg_index if override is not None else leg_index
                ),
                basis_override_ref=basis_override_ref,
                basis_last_verified=basis_last_verified,
                basis_evidence_source=leg_evidence_source,
                unit_fee_basis_usd=deterministic_decimal_divide(fee_for_leg, leg.amount),
                acquisition_event_id=(
                    override.acquisition_event_id if override is not None else event.event_id
                ),
                acquisition_tx_ref=(
                    override.acquisition_tx_ref if override is not None else event.tx_ref
                ),
                origin_lot_ref=None if override is None else override.origin_lot_ref,
                basis_price_source=leg_price_source,
                basis_price_as_of=leg_price_as_of,
                symbol=leg.asset.symbol,
                chain=leg.asset.chain,
            )
        )


def _consume_transfer_out(
    book: LotBook,
    *,
    event: LedgerEvent,
    outs: Sequence[tuple[int, LedgerLeg]],
    pending: dict[str, list[Lot]],
    gaps: list[CalculationGap],
    counts: _EngineCounts,
) -> None:
    transfer_ref = event.transfer_ref
    if transfer_ref is None:
        _gap(gaps, "missing_transfer_ref", "transfer requires transfer_ref", event=event)
        return
    fragments = pending.setdefault(transfer_ref, [])
    for leg_index, leg in outs:
        matched, shortfall = book.consume(event.account_ref, leg.asset.asset_id, leg.amount)
        for fragment_index, consumed in enumerate(matched):
            fragments.append(
                Lot(
                    lot_ref=(f"{event.event_id}:transfer:{leg_index}:fragment:{fragment_index}"),
                    account_ref=event.account_ref,
                    asset_id=leg.asset.asset_id,
                    quantity=consumed.quantity,
                    unit_cost_usd=consumed.lot.unit_cost_usd,
                    acquired_at=consumed.lot.acquired_at,
                    basis_source=consumed.lot.basis_source,
                    remaining_cost_basis_usd=consumed.cost_basis_usd,
                    remaining_fee_basis_usd=consumed.fee_basis_usd,
                    acquisition_sequence=consumed.lot.acquisition_sequence,
                    acquisition_leg_index=consumed.lot.acquisition_leg_index,
                    basis_override_ref=consumed.lot.basis_override_ref,
                    basis_last_verified=consumed.lot.basis_last_verified,
                    basis_evidence_source=consumed.lot.basis_evidence_source,
                    unit_fee_basis_usd=consumed.lot.unit_fee_basis_usd,
                    acquisition_event_id=consumed.lot.acquisition_event_id,
                    acquisition_tx_ref=consumed.lot.acquisition_tx_ref,
                    origin_lot_ref=consumed.lot.origin_lot_ref or consumed.lot.lot_ref,
                    basis_price_source=consumed.lot.basis_price_source,
                    basis_price_as_of=consumed.lot.basis_price_as_of,
                    symbol=leg.asset.symbol,
                    chain=leg.asset.chain,
                )
            )
        if shortfall > 0:
            counts.mark_unresolved_transfer(event)
            fragments.append(
                Lot(
                    lot_ref=f"{event.event_id}:transfer:{leg_index}:shortfall",
                    account_ref=event.account_ref,
                    asset_id=leg.asset.asset_id,
                    quantity=shortfall,
                    unit_cost_usd=None,
                    acquired_at=None,
                    basis_source="unknown_transfer_source",
                    acquisition_sequence=None,
                    origin_lot_ref=None,
                    symbol=leg.asset.symbol,
                    chain=leg.asset.chain,
                )
            )
            _gap(
                gaps,
                "transfer_source_shortfall",
                "same-owner transfer_out exceeds source-account lots",
                event=event,
                asset_id=leg.asset.asset_id,
            )


def _add_transfer_in_from_pending(
    book: LotBook,
    *,
    event: LedgerEvent,
    ins: Sequence[tuple[int, LedgerLeg]],
    pending: dict[str, list[Lot]],
    override: BasisOverrideInput | None,
    gaps: list[CalculationGap],
    warnings: list[str],
    assumptions: list[CalculationAssumption],
    counts: _EngineCounts,
) -> None:
    transfer_ref = event.transfer_ref
    if transfer_ref is None:
        _gap(gaps, "missing_transfer_ref", "transfer requires transfer_ref", event=event)
        return
    fragments = pending.get(transfer_ref, [])
    if not fragments and override is not None:
        _add_acquisition_lots(
            book,
            event=event,
            ins=ins,
            outs=[],
            fee_addition=Decimal(0),
            override=override,
            gaps=gaps,
            warnings=warnings,
        )
        assumptions.append(
            CalculationAssumption(
                code="same_owner_transfer_override",
                message=(
                    "caller asserted same ownership and supplied original basis/date for a "
                    "source account outside this ledger"
                ),
                event_id=event.event_id,
                transfer_ref=transfer_ref,
            )
        )
        return
    if override is not None:
        raise ValueError("basis override cannot be combined with a matched same-owner transfer")
    if any(fragment.account_ref == event.account_ref for fragment in fragments):
        raise ValueError("same-owner transfer source and destination account_ref must differ")

    for leg_index, leg in ins:
        remaining = leg.amount
        destination_index = 0
        for fragment in list(fragments):
            if remaining <= 0:
                break
            if fragment.asset_id != leg.asset.asset_id or fragment.quantity <= 0:
                continue
            quantity = min(remaining, fragment.quantity)
            quantity_before = fragment.quantity
            consume_all = quantity == quantity_before
            cost_basis = fragment.remaining_cost_basis_usd
            if cost_basis is not None and not consume_all:
                cost_basis = bounded_decimal_share(cost_basis, quantity, quantity_before)
            fee_basis = fragment.remaining_fee_basis_usd or Decimal(0)
            if not consume_all:
                fee_basis = bounded_decimal_share(fee_basis, quantity, quantity_before)
            book.add(
                Lot(
                    lot_ref=f"{event.event_id}:in:{leg_index}:transfer:{destination_index}",
                    account_ref=event.account_ref,
                    asset_id=leg.asset.asset_id,
                    quantity=quantity,
                    unit_cost_usd=fragment.unit_cost_usd,
                    acquired_at=fragment.acquired_at,
                    basis_source=fragment.basis_source,
                    remaining_cost_basis_usd=cost_basis,
                    remaining_fee_basis_usd=fee_basis,
                    acquisition_sequence=fragment.acquisition_sequence,
                    acquisition_leg_index=fragment.acquisition_leg_index,
                    basis_override_ref=fragment.basis_override_ref,
                    basis_last_verified=fragment.basis_last_verified,
                    basis_evidence_source=fragment.basis_evidence_source,
                    unit_fee_basis_usd=fragment.unit_fee_basis_usd,
                    acquisition_event_id=fragment.acquisition_event_id,
                    acquisition_tx_ref=fragment.acquisition_tx_ref,
                    origin_lot_ref=fragment.origin_lot_ref or fragment.lot_ref,
                    basis_price_source=fragment.basis_price_source,
                    basis_price_as_of=fragment.basis_price_as_of,
                    symbol=leg.asset.symbol,
                    chain=leg.asset.chain,
                )
            )
            fragment.quantity = exact_decimal_subtract(fragment.quantity, quantity)
            if fragment.remaining_cost_basis_usd is not None and cost_basis is not None:
                fragment.remaining_cost_basis_usd = exact_decimal_subtract(
                    fragment.remaining_cost_basis_usd,
                    cost_basis,
                )
            if fragment.remaining_fee_basis_usd is not None:
                fragment.remaining_fee_basis_usd = exact_decimal_subtract(
                    fragment.remaining_fee_basis_usd,
                    fee_basis,
                )
            remaining = exact_decimal_subtract(remaining, quantity)
            destination_index += 1
        if remaining > 0:
            counts.mark_unresolved_transfer(event)
            book.add(
                Lot(
                    lot_ref=f"{event.event_id}:in:{leg_index}:unmatched",
                    account_ref=event.account_ref,
                    asset_id=leg.asset.asset_id,
                    quantity=remaining,
                    unit_cost_usd=None,
                    acquired_at=None,
                    basis_source="unmatched_same_owner_transfer",
                    acquisition_sequence=None,
                    symbol=leg.asset.symbol,
                    chain=leg.asset.chain,
                )
            )
            _gap(
                gaps,
                "unmatched_transfer_in",
                "same-owner transfer_in lacks a matching source lot or basis override",
                event=event,
                asset_id=leg.asset.asset_id,
            )
    pending[transfer_ref] = [fragment for fragment in fragments if fragment.quantity > 0]
    assumptions.append(
        CalculationAssumption(
            code="same_owner_transfer",
            message="caller asserted same ownership for the linked transfer",
            event_id=event.event_id,
            transfer_ref=transfer_ref,
        )
    )


def _consume_unresolved_transfer(
    book: LotBook,
    *,
    event: LedgerEvent,
    ins: Sequence[tuple[int, LedgerLeg]],
    outs: Sequence[tuple[int, LedgerLeg]],
    override: BasisOverrideInput | None,
    gaps: list[CalculationGap],
    warnings: list[str],
    gap_code: str,
    gap_message: str,
) -> None:
    for _, leg in outs:
        book.consume(event.account_ref, leg.asset.asset_id, leg.amount)
    if ins:
        if override is not None:
            _add_acquisition_lots(
                book,
                event=event,
                ins=ins,
                outs=[],
                fee_addition=Decimal(0),
                override=override,
                gaps=gaps,
                warnings=warnings,
            )
        else:
            for leg_index, leg in ins:
                book.add(
                    Lot(
                        lot_ref=f"{event.event_id}:in:{leg_index}:unresolved",
                        account_ref=event.account_ref,
                        asset_id=leg.asset.asset_id,
                        quantity=leg.amount,
                        unit_cost_usd=None,
                        acquired_at=None,
                        basis_source="unresolved_transfer",
                        acquisition_sequence=None,
                        symbol=leg.asset.symbol,
                        chain=leg.asset.chain,
                    )
                )
    _gap(
        gaps,
        gap_code,
        gap_message,
        event=event,
    )


def _fee_policy(
    event: LedgerEvent,
    principal_ins: Sequence[tuple[int, LedgerLeg]],
    principal_outs: Sequence[tuple[int, LedgerLeg]],
    fee_legs: Sequence[tuple[int, LedgerLeg]],
    gaps: list[CalculationGap],
    counts: _EngineCounts,
    assumptions: list[CalculationAssumption],
) -> tuple[Decimal, list[Decimal]]:
    """Return acquisition fee addition and per-principal-out fee reductions."""
    fee_usd = event.fee_usd or Decimal(0)
    reductions = [Decimal(0) for _ in principal_outs]
    if event.kind == EventKind.fee:
        if principal_ins:
            raise ValueError("fee events cannot have principal in legs")
        if principal_outs and fee_legs:
            raise ValueError("fee event legs must use one role consistently")
        standalone_fee_legs = [leg for _, leg in (fee_legs or principal_outs)]
        if not standalone_fee_legs:
            raise ValueError("fee events require at least one asset out leg")
        if event.fee_allocation not in (None, FeeAllocation.none):
            raise ValueError("standalone fee events require fee_allocation='none'")
        if event.fee_payment not in (None, FeePayment.digital_asset):
            raise ValueError("standalone fee events require fee_payment='digital_asset'")
        if event.fee_usd is not None:
            priced_total = _sum_opt([_leg_usd(leg) for leg in standalone_fee_legs])
            if priced_total is None:
                raise ValueError("standalone fee event fee_usd requires priced asset legs")
            if priced_total != event.fee_usd:
                raise ValueError(f"event {event.event_id} fee legs do not equal fee_usd")
        return Decimal(0), reductions

    if fee_usd == 0 and not fee_legs and event.fee_allocation is None and event.fee_payment is None:
        return Decimal(0), reductions

    unresolved = False
    allocation = event.fee_allocation
    if event.kind in (EventKind.transfer_in, EventKind.transfer_out) and allocation not in (
        None,
        FeeAllocation.none,
        FeeAllocation.unknown,
    ):
        raise ValueError("transfer fees cannot adjust acquisition basis or disposition proceeds")
    if allocation is None or allocation == FeeAllocation.unknown:
        _gap(
            gaps,
            "unknown_fee_allocation",
            "fee_usd requires an explicit acquisition/disposition/none allocation",
            event=event,
        )
        unresolved = True
    elif allocation == FeeAllocation.acquisition_basis:
        if not principal_ins:
            raise ValueError(f"event {event.event_id} has no acquisition to receive its fee")
        if event.fee_usd is None:
            _gap(
                gaps,
                "missing_fee_usd",
                "acquisition-basis fee allocation requires fee_usd",
                event=event,
            )
            unresolved = True
    elif allocation == FeeAllocation.disposition_proceeds:
        if not principal_outs:
            raise ValueError(f"event {event.event_id} has no disposition to receive its fee")
        if event.fee_usd is None:
            _gap(
                gaps,
                "missing_fee_usd",
                "disposition-proceeds fee allocation requires fee_usd",
                event=event,
            )
            unresolved = True
        else:
            reductions = _allocate(fee_usd, [leg for _, leg in principal_outs])

    payment = event.fee_payment
    if payment is None or payment == FeePayment.unknown:
        _gap(
            gaps,
            "unknown_fee_payment",
            "fee payment asset/fiat treatment is not specified",
            event=event,
        )
        unresolved = True
    elif payment == FeePayment.digital_asset:
        if not fee_legs:
            _gap(
                gaps,
                "missing_fee_asset_leg",
                "digital-asset fee payment is missing its separate asset out leg",
                event=event,
            )
            unresolved = True
        else:
            fee_leg_total = _sum_opt([_leg_usd(leg) for _, leg in fee_legs])
            if event.fee_usd is not None and fee_leg_total is not None and fee_leg_total != fee_usd:
                raise ValueError(f"event {event.event_id} fee legs do not equal fee_usd")
    elif fee_legs:
        raise ValueError(
            f"event {event.event_id} has fee legs but fee_payment is not digital_asset"
        )

    if unresolved:
        counts.unresolved_fee_count += 1
    if allocation is not None and allocation != FeeAllocation.unknown:
        assumptions.append(
            CalculationAssumption(
                code="fee_allocation",
                message=f"caller selected fee allocation: {allocation.value}",
                event_id=event.event_id,
            )
        )
    acquisition_addition = fee_usd if allocation == FeeAllocation.acquisition_basis else Decimal(0)
    return acquisition_addition, reductions


def _build_open_lots(
    book: LotBook,
    price_by_asset: dict[str, AsOfPriceInput],
    asset_by_id: dict[str, AssetRef],
) -> list[CostLot]:
    result: list[CostLot] = []
    for lot in book.open_lots():
        cost_basis = lot.remaining_cost_basis_usd
        price = price_by_asset.get(lot.asset_id)
        market_value = (
            None if price is None else exact_decimal_multiply(price.unit_price_usd, lot.quantity)
        )
        unrealized = (
            None
            if market_value is None or cost_basis is None
            else exact_decimal_subtract(market_value, cost_basis)
        )
        asset = asset_by_id.get(lot.asset_id) or AssetRef(
            asset_id=lot.asset_id,
            symbol=lot.symbol,
            chain=lot.chain,
        )
        result.append(
            CostLot(
                lot_ref=lot.lot_ref,
                account_ref=lot.account_ref,
                asset=asset,
                quantity=lot.quantity,
                cost_basis_usd=cost_basis,
                unit_cost_usd=lot.unit_cost_usd,
                acquired_at=lot.acquired_at,
                acquisition_sequence=lot.acquisition_sequence,
                acquisition_leg_index=lot.acquisition_leg_index,
                basis_source=lot.basis_source,
                basis_override_ref=lot.basis_override_ref,
                basis_last_verified=lot.basis_last_verified,
                basis_evidence_source=lot.basis_evidence_source,
                acquisition_fee_usd=lot.remaining_fee_basis_usd or Decimal(0),
                acquisition_event_id=lot.acquisition_event_id,
                acquisition_tx_ref=lot.acquisition_tx_ref,
                origin_lot_ref=lot.origin_lot_ref or lot.lot_ref,
                basis_price_source=lot.basis_price_source,
                basis_price_as_of=lot.basis_price_as_of,
                market_value_usd=market_value,
                unrealized_pnl_usd=unrealized,
                market_price_source=None if price is None else price.source,
                market_price_as_of=None if price is None else price.as_of,
            )
        )
    return result


def _replay_metadata(
    events: Sequence[LedgerEvent], report_window: ReportWindowInput | None
) -> tuple[ReplayMetadata, list[LedgerEvent]]:
    if report_window is None:
        replayed = list(events)
        return (
            ReplayMetadata(
                replay_version="1.0.0",
                mode="all_events",
                start_at=None,
                end_at=None,
                opening_state_ref=None,
                opening_state_schema_version=None,
                opening_state_source=None,
                opening_state_last_verified=None,
                opening_state_basis_method=None,
                opening_state_basis_method_version=None,
                opening_state_snapshot_complete=None,
                input_event_count=len(events),
                replayed_event_count=len(events),
                pre_period_event_count=0,
                in_period_event_count=len(events),
                post_period_excluded_count=0,
            ),
            replayed,
        )
    replayed = [event for event in events if event.timestamp < report_window.end_at]
    pre = sum(1 for event in replayed if event.timestamp < report_window.start_at)
    in_period = len(replayed) - pre
    opening = report_window.opening_state
    return (
        ReplayMetadata(
            replay_version=report_window.replay_version,
            mode="full_history" if report_window.full_history else "opening_state",
            start_at=report_window.start_at,
            end_at=report_window.end_at,
            opening_state_ref=None if opening is None else opening.state_ref,
            opening_state_schema_version=None if opening is None else opening.schema_version,
            opening_state_source=None if opening is None else opening.source,
            opening_state_last_verified=None if opening is None else opening.last_verified,
            opening_state_basis_method=None if opening is None else opening.basis_method,
            opening_state_basis_method_version=(
                None if opening is None else opening.basis_method_version
            ),
            opening_state_snapshot_complete=(
                None if opening is None else opening.snapshot_complete
            ),
            input_event_count=len(events),
            replayed_event_count=len(replayed),
            pre_period_event_count=pre,
            in_period_event_count=in_period,
            post_period_excluded_count=len(events) - len(replayed),
        ),
        replayed,
    )


def compute_cost_basis(
    events: Sequence[LedgerEvent],
    *,
    overrides: Sequence[BasisOverrideInput] | None = None,
    as_of_prices: Sequence[AsOfPriceInput] | None = None,
    report_window: ReportWindowInput | None = None,
    method: str = "fifo",
) -> CostBasisResult:
    """Compute account-scoped FIFO basis over a bounded or legacy all-event replay."""
    override_inputs = list(overrides or [])
    price_inputs = list(as_of_prices or [])
    _validate_inputs(events, override_inputs, price_inputs, report_window)
    methodology = _methodology(method)
    override_by_event = {override.event_id: override for override in override_inputs}
    price_by_asset = {price.asset_id: price for price in price_inputs}
    replay, replayed_events = _replay_metadata(events, report_window)

    book = LotBook()
    disposals: list[DisposalRecord] = []
    warnings: list[str] = []
    gaps: list[CalculationGap] = []
    assumptions: list[CalculationAssumption] = []
    counts = _EngineCounts()
    asset_by_id: dict[str, AssetRef] = {}
    pending_transfers: dict[str, list[Lot]] = {}

    if report_window is not None and report_window.opening_state is not None:
        for opening in report_window.opening_state.lots:
            _merge_asset_metadata(asset_by_id, opening.asset)
    for event in replayed_events:
        for leg in event.legs:
            _merge_asset_metadata(asset_by_id, leg.asset)

    if report_window is None:
        _gap(
            gaps,
            "missing_report_window",
            "statement use requires report bounds and full-history or opening-state replay",
        )
    elif report_window.full_history:
        assumptions.append(
            CalculationAssumption(
                code="full_history_assertion",
                message="caller asserted that supplied pre-period events are complete history",
            )
        )
    elif report_window.opening_state is not None:
        opening_lots = sorted(
            report_window.opening_state.lots,
            key=lambda lot: (
                lot.acquired_at is None,
                lot.acquired_at or 0,
                lot.acquisition_sequence is None,
                lot.acquisition_sequence or 0,
                lot.acquisition_event_id or "",
                lot.acquisition_leg_index,
                lot.lot_ref,
            ),
        )
        assumptions.append(
            CalculationAssumption(
                code="opening_state_assertion",
                message=(
                    "caller supplied a complete FIFO opening snapshot compatible with "
                    f"method version {report_window.opening_state.basis_method_version}"
                ),
            )
        )
        for opening in opening_lots:
            book.add(_opening_lot(opening))
            if opening.cost_basis_usd is None and opening.unit_cost_usd is None:
                _gap(
                    gaps,
                    "unknown_opening_basis",
                    "opening-state lot has unknown basis",
                    account_ref=opening.account_ref,
                    asset_id=opening.asset.asset_id,
                )
            elif opening.cost_basis_usd is None:
                _gap(
                    gaps,
                    "missing_opening_total_basis",
                    "statement replay requires authoritative opening total basis",
                    account_ref=opening.account_ref,
                    asset_id=opening.asset.asset_id,
                )
            if opening.acquired_at is None:
                _gap(
                    gaps,
                    "unknown_opening_acquisition_date",
                    "opening-state lot has unknown acquisition date",
                    account_ref=opening.account_ref,
                    asset_id=opening.asset.asset_id,
                )
            if (
                (opening.cost_basis_usd is not None or opening.unit_cost_usd is not None)
                and (opening.basis_price_source is None or opening.basis_price_as_of is None)
                and (opening.basis_evidence_source is None or opening.basis_last_verified is None)
            ):
                _gap(
                    gaps,
                    "missing_opening_basis_provenance",
                    "known opening-state basis requires price or verified evidence provenance",
                    account_ref=opening.account_ref,
                    asset_id=opening.asset.asset_id,
                )

    for event in sorted(replayed_events, key=_event_sort_key):
        principal_ins = [
            (index, leg)
            for index, leg in enumerate(event.legs)
            if leg.role == "principal" and leg.direction == "in"
        ]
        principal_outs = [
            (index, leg)
            for index, leg in enumerate(event.legs)
            if leg.role == "principal" and leg.direction == "out"
        ]
        fee_legs = [(index, leg) for index, leg in enumerate(event.legs) if leg.role == "fee"]
        for leg in event.legs:
            if _leg_usd(leg) is not None and (leg.price_source is None or leg.price_as_of is None):
                _gap(
                    gaps,
                    "missing_price_provenance",
                    "priced event leg is missing price_source/price_as_of",
                    event=event,
                    asset_id=leg.asset.asset_id,
                )

        override = override_by_event.get(event.event_id)
        acquisition_fee, disposition_fees = _fee_policy(
            event,
            principal_ins,
            principal_outs,
            fee_legs,
            gaps,
            counts,
            assumptions,
        )

        if event.kind in (EventKind.transfer_in, EventKind.transfer_out):
            if event.transfer_ref is None:
                counts.mark_unresolved_transfer(event)
                _consume_unresolved_transfer(
                    book,
                    event=event,
                    ins=principal_ins,
                    outs=principal_outs,
                    override=override,
                    gaps=gaps,
                    warnings=warnings,
                    gap_code="missing_transfer_ref",
                    gap_message="transfer requires an opaque transfer_ref",
                )
            elif event.transfer_treatment is None:
                counts.mark_unresolved_transfer(event)
                _consume_unresolved_transfer(
                    book,
                    event=event,
                    ins=principal_ins,
                    outs=principal_outs,
                    override=override,
                    gaps=gaps,
                    warnings=warnings,
                    gap_code="missing_transfer_treatment",
                    gap_message="transfer requires an explicit ownership treatment",
                )
            elif event.transfer_treatment == TransferTreatment.same_owner:
                if event.kind == EventKind.transfer_out:
                    if principal_ins or not principal_outs:
                        raise ValueError("transfer_out requires only principal out legs")
                    _consume_transfer_out(
                        book,
                        event=event,
                        outs=principal_outs,
                        pending=pending_transfers,
                        gaps=gaps,
                        counts=counts,
                    )
                else:
                    if principal_outs or not principal_ins:
                        raise ValueError("transfer_in requires only principal in legs")
                    _add_transfer_in_from_pending(
                        book,
                        event=event,
                        ins=principal_ins,
                        pending=pending_transfers,
                        override=override,
                        gaps=gaps,
                        warnings=warnings,
                        assumptions=assumptions,
                        counts=counts,
                    )
            else:
                counts.mark_unresolved_transfer(event)
                _consume_unresolved_transfer(
                    book,
                    event=event,
                    ins=principal_ins,
                    outs=principal_outs,
                    override=override,
                    gaps=gaps,
                    warnings=warnings,
                    gap_code="unresolved_transfer_treatment",
                    gap_message=(
                        "external or unknown transfer treatment cannot produce a tax conclusion"
                    ),
                )
        elif event.kind in (EventKind.acquire, EventKind.claim):
            if principal_outs or not principal_ins:
                raise ValueError(f"{event.kind.value} requires only principal in legs")
            _add_acquisition_lots(
                book,
                event=event,
                ins=principal_ins,
                outs=[],
                fee_addition=acquisition_fee,
                override=override,
                gaps=gaps,
                warnings=warnings,
            )
        elif event.kind == EventKind.dispose:
            if principal_ins or not principal_outs:
                raise ValueError("dispose requires only principal out legs")
            for (leg_index, leg), reduction in zip(principal_outs, disposition_fees, strict=True):
                _record_disposals(
                    book,
                    leg=leg,
                    asset=asset_by_id[leg.asset.asset_id],
                    leg_index=leg_index,
                    gross_proceeds=_leg_usd(leg),
                    fee_adjustment=reduction,
                    event=event,
                    disposition_type="principal",
                    disposals=disposals,
                    gaps=gaps,
                    warnings=warnings,
                )
        elif event.kind == EventKind.swap or (
            event.kind in _AMBIGUOUS_DEFI_KINDS
            and event.tax_treatment == TaxTreatment.taxable_exchange
        ):
            if not principal_ins or not principal_outs:
                raise ValueError(f"{event.kind.value} taxable exchange requires in and out legs")
            for (leg_index, leg), reduction in zip(principal_outs, disposition_fees, strict=True):
                _record_disposals(
                    book,
                    leg=leg,
                    asset=asset_by_id[leg.asset.asset_id],
                    leg_index=leg_index,
                    gross_proceeds=_leg_usd(leg),
                    fee_adjustment=reduction,
                    event=event,
                    disposition_type="principal",
                    disposals=disposals,
                    gaps=gaps,
                    warnings=warnings,
                )
            _add_acquisition_lots(
                book,
                event=event,
                ins=principal_ins,
                outs=[leg for _, leg in principal_outs],
                fee_addition=acquisition_fee,
                override=override,
                gaps=gaps,
                warnings=warnings,
            )
            if event.kind in _AMBIGUOUS_DEFI_KINDS:
                assumptions.append(
                    CalculationAssumption(
                        code="taxable_defi_exchange",
                        message=f"caller classified {event.kind.value} as a taxable exchange",
                        event_id=event.event_id,
                    )
                )
        elif event.kind in _AMBIGUOUS_DEFI_KINDS or event.kind == EventKind.other:
            counts.unresolved_event_count += 1
            _gap(
                gaps,
                "unresolved_event_treatment",
                (
                    f"{event.kind.value} requires explicit taxable_exchange treatment"
                    if event.kind in _AMBIGUOUS_DEFI_KINDS
                    else "other events require upstream classification"
                ),
                event=event,
            )
        elif event.kind == EventKind.fee:
            if principal_ins:
                raise ValueError("fee events cannot have principal in legs")
            if principal_outs and fee_legs:
                raise ValueError("fee event legs must use one role consistently")
            fee_legs = fee_legs or principal_outs

        for leg_index, leg in fee_legs:
            _record_disposals(
                book,
                leg=leg,
                asset=asset_by_id[leg.asset.asset_id],
                leg_index=leg_index,
                gross_proceeds=_leg_usd(leg),
                fee_adjustment=Decimal(0),
                event=event,
                disposition_type="fee_asset",
                disposals=disposals,
                gaps=gaps,
                warnings=warnings,
            )

    has_unmatched_transfer_inventory = False
    for transfer_ref, fragments in pending_transfers.items():
        if any(fragment.quantity > 0 for fragment in fragments):
            has_unmatched_transfer_inventory = True
            counts.unresolved_transfer_keys.add(transfer_ref)
            _gap(
                gaps,
                "unmatched_transfer_out",
                (
                    f"same-owner transfer_ref {transfer_ref} has no complete destination match; "
                    "closing inventory totals are unknown"
                ),
            )

    if report_window is not None:
        disposals = [
            disposal
            for disposal in disposals
            if report_window.start_at <= disposal.disposed_at < report_window.end_at
        ]

    for disposal in disposals:
        if disposal.proceeds_usd is None:
            _gap(
                gaps,
                "unknown_disposition_proceeds",
                "disposition proceeds are unknown",
                account_ref=disposal.account_ref,
                asset_id=disposal.asset.asset_id,
            )

    open_lots = _build_open_lots(book, price_by_asset, asset_by_id)
    for lot in open_lots:
        if lot.cost_basis_usd is None:
            _gap(
                gaps,
                "unknown_open_lot_basis",
                "open lot has unknown cost basis",
                account_ref=lot.account_ref,
                asset_id=lot.asset.asset_id,
            )
        if lot.market_value_usd is not None and (
            lot.market_price_source is None or lot.market_price_as_of is None
        ):
            _gap(
                gaps,
                "missing_as_of_price_provenance",
                "open-lot valuation is missing as-of price source/as_of",
                account_ref=lot.account_ref,
                asset_id=lot.asset.asset_id,
            )

    totals = CostBasisTotals(
        open_cost_basis_usd=(
            None
            if has_unmatched_transfer_inventory
            else _sum_opt([lot.cost_basis_usd for lot in open_lots])
        ),
        open_market_value_usd=(
            None
            if has_unmatched_transfer_inventory
            else _sum_opt([lot.market_value_usd for lot in open_lots])
        ),
        open_unrealized_pnl_usd=(
            None
            if has_unmatched_transfer_inventory
            else _sum_opt([lot.unrealized_pnl_usd for lot in open_lots])
        ),
        realized_gain_usd=_sum_opt([disposal.realized_gain_usd for disposal in disposals]),
    )
    accounts = (
        {event.account_ref for event in replayed_events}
        | {lot.account_ref for lot in open_lots}
        | {disposal.account_ref for disposal in disposals}
    )
    assets = set(asset_by_id)
    complete_disposals = sum(1 for disposal in disposals if disposal.complete)
    coverage = CoverageMetadata(
        account_count=len(accounts),
        asset_count=len(assets),
        open_lot_count=len(open_lots),
        known_basis_open_lot_count=sum(1 for lot in open_lots if lot.cost_basis_usd is not None),
        unknown_basis_open_lot_count=sum(1 for lot in open_lots if lot.cost_basis_usd is None),
        disposition_count=len(disposals),
        complete_disposition_count=complete_disposals,
        incomplete_disposition_count=len(disposals) - complete_disposals,
        unresolved_event_count=counts.unresolved_event_count,
        unresolved_transfer_count=counts.unresolved_transfer_count,
        unresolved_fee_count=counts.unresolved_fee_count,
    )
    complete = not gaps
    completeness = CalculationCompleteness(
        complete=complete,
        statement_ready=(
            complete and report_window is not None and methodology.review_status == "approved"
        ),
        gap_count=len(gaps),
        gaps=gaps,
    )
    return CostBasisResult(
        method="fifo",
        methodology=methodology,
        replay=replay,
        coverage=coverage,
        completeness=completeness,
        assumptions=assumptions,
        open_lots=open_lots,
        disposals=disposals,
        totals=totals,
        warnings=warnings,
    )


__all__ = [
    "ACCOUNTING_METHOD_LAST_VERIFIED",
    "ACCOUNTING_METHOD_SOURCE",
    "ACCOUNTING_METHOD_VERSION",
    "ACCOUNTING_METHODOLOGY_REVIEW_STATUS",
    "EVENT_TREATMENT_MATRIX",
    "CalculationAssumption",
    "CalculationCompleteness",
    "CalculationGap",
    "CostBasisResult",
    "CostBasisTotals",
    "CostLot",
    "CoverageMetadata",
    "DisposalRecord",
    "MethodologyMetadata",
    "ReplayMetadata",
    "compute_cost_basis",
]
