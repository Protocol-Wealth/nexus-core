# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Shared domain models for the onchain-accounting engine.

The de-identified event ledger (the P2 decoder output / P3 cost-basis input) and
the raw-transaction decoder input. Every reference is opaque or a public onchain
fact — no client identity, no wallet-to-client linkage — and money/quantities are
``Decimal`` (never float). ``app/accounting/contract.py`` re-exports these as the
wire contract.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .lots import exact_decimal_multiply

_EVM_ADDRESS = re.compile(r"0x[0-9a-f]{40}", re.IGNORECASE)
_BITCOIN_BECH32 = re.compile(
    r"(?<![0-9a-z])(?:bc1|tb1)[02-9ac-hj-np-z]{20,}(?![0-9a-z])",
    re.IGNORECASE,
)
_BASE58_ADDRESS = re.compile(
    r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}"
    r"(?![1-9A-HJ-NP-Za-km-z])"
)
_BITCOIN_LEGACY = re.compile(
    r"(?<![1-9A-HJ-NP-Za-km-z])[123mn][1-9A-HJ-NP-Za-km-z]{25,34}"
    r"(?![1-9A-HJ-NP-Za-km-z])"
)

ACCOUNTING_DECIMAL_MAX_SCALE = 36
ACCOUNTING_DECIMAL_MAX_INTEGER_DIGITS = 42
ACCOUNTING_TOTAL_MAX_SCALE = 72
ACCOUNTING_TOTAL_MAX_INTEGER_DIGITS = 84
ACCOUNTING_DERIVED_MAX_SCALE = 256
ACCOUNTING_DERIVED_MAX_INTEGER_DIGITS = 128


def validate_non_blank(value: str | None) -> str | None:
    """Canonicalize contract strings and reject whitespace-only evidence or refs."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be blank")
    return normalized


def _validate_decimal_envelope(
    value: Decimal | None,
    *,
    max_scale: int,
    max_integer_digits: int,
    label: str,
) -> Decimal | None:
    if value is None:
        return None
    if not value.is_finite():
        raise ValueError("accounting decimals must be finite")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):  # pragma: no cover - finite values use int exponents
        raise ValueError("accounting decimals must be finite")
    if exponent < -max_scale:
        raise ValueError(f"{label} support at most {max_scale} fractional digits")
    if exponent > max_integer_digits:
        raise ValueError("accounting decimal exponent exceeds the supported magnitude")
    integer_digits = 0 if value.is_zero() or value.adjusted() < 0 else value.adjusted() + 1
    if integer_digits > max_integer_digits:
        raise ValueError(f"{label} support at most {max_integer_digits} integer digits")
    if len(value.as_tuple().digits) > max_integer_digits + max_scale:
        raise ValueError("accounting decimal coefficient exceeds the supported precision")
    return value


def validate_accounting_decimal(value: Decimal | None) -> Decimal | None:
    """Validate direct quantities and unit prices at the wire boundary."""
    return _validate_decimal_envelope(
        value,
        max_scale=ACCOUNTING_DECIMAL_MAX_SCALE,
        max_integer_digits=ACCOUNTING_DECIMAL_MAX_INTEGER_DIGITS,
        label="accounting decimals",
    )


def validate_accounting_total_decimal(value: Decimal | None) -> Decimal | None:
    """Validate explicit monetary totals that may be a product of two inputs."""
    return _validate_decimal_envelope(
        value,
        max_scale=ACCOUNTING_TOTAL_MAX_SCALE,
        max_integer_digits=ACCOUNTING_TOTAL_MAX_INTEGER_DIGITS,
        label="accounting totals",
    )


def validate_derived_accounting_decimal(value: Decimal | None) -> Decimal | None:
    """Validate authoritative values emitted for replay in a later snapshot."""
    return _validate_decimal_envelope(
        value,
        max_scale=ACCOUNTING_DERIVED_MAX_SCALE,
        max_integer_digits=ACCOUNTING_DERIVED_MAX_INTEGER_DIGITS,
        label="derived accounting decimals",
    )


def validate_opaque_account_ref(value: str) -> str:
    """Reject supported-chain wallet shapes where an opaque account ref is required."""
    normalized = validate_non_blank(value)
    if normalized is None:  # pragma: no cover - the field itself is required
        raise ValueError("account_ref must not be blank")
    if (
        _EVM_ADDRESS.search(normalized)
        or _BITCOIN_BECH32.search(normalized)
        or _BITCOIN_LEGACY.search(normalized)
        or _BASE58_ADDRESS.search(normalized)
    ):
        raise ValueError("account_ref must be opaque; raw wallet addresses are not accepted")
    return normalized


class EventKind(str, Enum):
    """Normalized onchain event kinds relevant to accounting."""

    acquire = "acquire"
    dispose = "dispose"
    swap = "swap"
    transfer_in = "transfer_in"
    transfer_out = "transfer_out"
    deposit = "deposit"
    withdraw = "withdraw"
    lp_add = "lp_add"
    lp_remove = "lp_remove"
    stake = "stake"
    unstake = "unstake"
    claim = "claim"
    fee = "fee"
    other = "other"


class TaxTreatment(str, Enum):
    """Caller-reviewed treatment for event kinds that are not unambiguous."""

    taxable_exchange = "taxable_exchange"
    unknown = "unknown"


class TransferTreatment(str, Enum):
    """Ownership treatment for an onchain transfer."""

    same_owner = "same_owner"
    external = "external"
    unknown = "unknown"


class FeeAllocation(str, Enum):
    """Where a USD transaction cost is applied exactly once."""

    acquisition_basis = "acquisition_basis"
    disposition_proceeds = "disposition_proceeds"
    none = "none"
    unknown = "unknown"


class FeePayment(str, Enum):
    """How a transaction fee was paid."""

    fiat = "fiat"
    digital_asset = "digital_asset"
    unknown = "unknown"


class AssetRef(BaseModel):
    """A public, PII-free asset identity. ``asset_id`` is an opaque stable key
    (e.g. a chain-prefixed contract/mint, or a caller-supplied hash)."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=128)
    symbol: str | None = Field(default=None, max_length=32)
    chain: str | None = Field(default=None, min_length=1, max_length=32)
    decimals: int | None = Field(default=None, ge=0, le=36)

    _asset_id_non_blank = field_validator("asset_id")(validate_non_blank)

    @field_validator("chain")
    @classmethod
    def normalize_chain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("chain must not be blank")
        return normalized


class LedgerLeg(BaseModel):
    """One asset movement within an event. ``amount`` is a positive human-readable
    quantity; ``direction`` says whether the account acquired or disposed it."""

    model_config = ConfigDict(extra="forbid")

    asset: AssetRef
    direction: Literal["in", "out"]
    amount: Decimal = Field(gt=0)
    unit_price_usd: Decimal | None = Field(default=None, ge=0)
    usd_value: Decimal | None = Field(default=None, ge=0)
    role: Literal["principal", "fee"] = "principal"
    price_source: str | None = Field(default=None, min_length=1, max_length=128)
    price_as_of: int | None = Field(default=None, ge=0)

    _price_source_non_blank = field_validator("price_source")(validate_non_blank)
    _bounded_scalars = field_validator("amount", "unit_price_usd")(validate_accounting_decimal)
    _bounded_total = field_validator("usd_value")(validate_accounting_total_decimal)

    @model_validator(mode="after")
    def validate_price_provenance(self) -> Self:
        if (self.price_source is None) != (self.price_as_of is None):
            raise ValueError("price_source and price_as_of must be supplied together")
        if (
            self.unit_price_usd is not None
            and self.usd_value is not None
            and exact_decimal_multiply(self.unit_price_usd, self.amount) != self.usd_value
        ):
            raise ValueError("usd_value must equal unit_price_usd multiplied by amount")
        if self.role == "fee" and self.direction != "out":
            raise ValueError("fee legs must have direction='out'")
        return self


class LedgerEvent(BaseModel):
    """A single normalized event. ``account_ref`` and ``tx_ref`` are OPAQUE — an
    opaque account id (never a wallet address) and an opaque transaction ref."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128)
    account_ref: str = Field(min_length=1, max_length=128)
    kind: EventKind
    timestamp: int = Field(ge=0, description="unix seconds, UTC")
    sequence: int | None = Field(
        default=None,
        ge=0,
        description="caller-assigned order for events sharing a timestamp",
    )
    tx_ref: str | None = Field(default=None, max_length=128)
    legs: list[LedgerLeg] = Field(min_length=1)
    fee_usd: Decimal | None = Field(default=None, ge=0)
    fee_allocation: FeeAllocation | None = None
    fee_payment: FeePayment | None = None
    transfer_ref: str | None = Field(default=None, min_length=1, max_length=128)
    transfer_treatment: TransferTreatment | None = None
    tax_treatment: TaxTreatment | None = None

    _opaque_account_ref = field_validator("account_ref")(validate_opaque_account_ref)
    _refs_non_blank = field_validator("event_id", "tx_ref", "transfer_ref")(validate_non_blank)
    _bounded_fee = field_validator("fee_usd")(validate_accounting_total_decimal)

    @model_validator(mode="after")
    def validate_treatment_shape(self) -> Self:
        is_transfer = self.kind in (EventKind.transfer_in, EventKind.transfer_out)
        if not is_transfer and (
            self.transfer_ref is not None or self.transfer_treatment is not None
        ):
            raise ValueError("transfer metadata is only valid for transfer events")
        treatment_kinds = {
            EventKind.deposit,
            EventKind.withdraw,
            EventKind.lp_add,
            EventKind.lp_remove,
            EventKind.stake,
            EventKind.unstake,
        }
        if self.tax_treatment is not None and self.kind not in treatment_kinds:
            raise ValueError("tax_treatment is only valid for ambiguous DeFi events")

        fee_legs = [leg for leg in self.legs if leg.role == "fee"]
        if self.fee_payment == FeePayment.fiat and fee_legs:
            raise ValueError("fiat fee_payment cannot include fee legs")
        return self


class EventLedger(BaseModel):
    """The de-identified event ledger a consumer sends to the accounting tools."""

    model_config = ConfigDict(extra="forbid")

    events: list[LedgerEvent] = Field(default_factory=list)


# --- decoder input (P2) ------------------------------------------------------
#
# A raw transaction is the asset movements the caller already resolved (pw-api's
# trackers give per-tx token deltas), plus optional protocol/method hints. The
# decoder classifies each into a LedgerEvent kind.


class MovementInput(BaseModel):
    """One asset movement within a raw transaction (decoder input)."""

    model_config = ConfigDict(extra="forbid")

    asset: AssetRef
    direction: Literal["in", "out"]
    amount: Decimal = Field(gt=0)
    counterparty: str | None = Field(default=None, max_length=256)
    unit_price_usd: Decimal | None = Field(default=None, ge=0)
    usd_value: Decimal | None = Field(default=None, ge=0)
    role: Literal["principal", "fee"] = "principal"
    price_source: str | None = Field(default=None, min_length=1, max_length=128)
    price_as_of: int | None = Field(default=None, ge=0)

    _price_source_non_blank = field_validator("price_source")(validate_non_blank)
    _bounded_scalars = field_validator("amount", "unit_price_usd")(validate_accounting_decimal)
    _bounded_total = field_validator("usd_value")(validate_accounting_total_decimal)

    @model_validator(mode="after")
    def validate_price_provenance(self) -> Self:
        if (self.price_source is None) != (self.price_as_of is None):
            raise ValueError("price_source and price_as_of must be supplied together")
        if (
            self.unit_price_usd is not None
            and self.usd_value is not None
            and exact_decimal_multiply(self.unit_price_usd, self.amount) != self.usd_value
        ):
            raise ValueError("usd_value must equal unit_price_usd multiplied by amount")
        if self.role == "fee" and self.direction != "out":
            raise ValueError("fee movements must have direction='out'")
        return self


class RawTransactionInput(BaseModel):
    """A raw onchain transaction to decode: its movements + optional hints.

    ``protocol_hint`` is the caller's protocol label (e.g. ``uniswap_v3``,
    ``marinade``) — pw-api's tracker/DeBank data usually carries it. ``method``
    is an optional instruction/method name (e.g. ``deposit``, ``unstake``).
    """

    model_config = ConfigDict(extra="forbid")

    account_ref: str = Field(min_length=1, max_length=128)
    chain: str = Field(min_length=1, max_length=32)
    timestamp: int = Field(ge=0, description="unix seconds, UTC")
    sequence: int | None = Field(default=None, ge=0)
    movements: list[MovementInput] = Field(min_length=1)
    tx_ref: str | None = Field(default=None, max_length=128)
    protocol_hint: str | None = Field(default=None, max_length=64)
    method: str | None = Field(default=None, max_length=64)
    fee_usd: Decimal | None = Field(default=None, ge=0)
    fee_allocation: FeeAllocation | None = None
    fee_payment: FeePayment | None = None
    transfer_ref: str | None = Field(default=None, min_length=1, max_length=128)
    transfer_treatment: TransferTreatment | None = None
    tax_treatment: TaxTreatment | None = None

    _opaque_account_ref = field_validator("account_ref")(validate_opaque_account_ref)
    _refs_non_blank = field_validator("tx_ref", "transfer_ref")(validate_non_blank)
    _bounded_fee = field_validator("fee_usd")(validate_accounting_total_decimal)

    @field_validator("chain")
    @classmethod
    def normalize_chain(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("chain must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_transaction_shape(self) -> Self:
        fee_movements = [movement for movement in self.movements if movement.role == "fee"]
        if self.fee_payment == FeePayment.fiat and fee_movements:
            raise ValueError("fiat fee_payment cannot include fee movements")
        if any(
            movement.asset.chain is not None and movement.asset.chain != self.chain
            for movement in self.movements
        ):
            raise ValueError("movement asset chain must match transaction chain")
        return self


# --- cost-basis input (P3) ---------------------------------------------------


class BasisOverrideInput(BaseModel):
    """A manual opening cost basis for a position transferred in (from a
    custodian or another wallet), keyed to the transfer-in event's ``event_id``.
    ``acquired_at`` carries the original acquisition time for the holding period.
    Omitting it preserves an unknown date and prevents statement completeness.
    Statement-complete use also identifies the single source lot, its original
    order, and verified evidence for the asserted total basis."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128)
    override_ref: str | None = Field(default=None, min_length=1, max_length=128)
    cost_basis_usd: Decimal = Field(ge=0)
    acquired_at: int | None = Field(default=None, ge=0)
    acquisition_sequence: int | None = Field(default=None, ge=0)
    acquisition_leg_index: int = Field(default=0, ge=0)
    acquisition_event_id: str | None = Field(default=None, min_length=1, max_length=128)
    acquisition_tx_ref: str | None = Field(default=None, min_length=1, max_length=128)
    source: str | None = Field(default=None, min_length=1, max_length=128)
    last_verified: date | None = None
    single_lot_assertion: Literal[True] | None = None
    origin_lot_ref: str | None = Field(default=None, min_length=1, max_length=128)

    _refs_and_source_non_blank = field_validator(
        "event_id",
        "override_ref",
        "acquisition_event_id",
        "acquisition_tx_ref",
        "source",
        "origin_lot_ref",
    )(validate_non_blank)
    _bounded_cost_basis = field_validator("cost_basis_usd")(validate_accounting_total_decimal)


class AsOfPriceInput(BaseModel):
    """A current unit price used to value open lots (unrealized PnL)."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=128)
    unit_price_usd: Decimal = Field(ge=0)
    source: str | None = Field(default=None, min_length=1, max_length=128)
    as_of: int | None = Field(default=None, ge=0)

    _identity_and_source_non_blank = field_validator("asset_id", "source")(validate_non_blank)
    _bounded_price = field_validator("unit_price_usd")(validate_accounting_decimal)

    @model_validator(mode="after")
    def validate_price_provenance(self) -> Self:
        if (self.source is None) != (self.as_of is None):
            raise ValueError("source and as_of must be supplied together")
        return self


class OpeningLotInput(BaseModel):
    """One de-identified FIFO lot from an opening-state snapshot.

    ``cost_basis_usd`` and ``acquisition_fee_usd`` are authoritative remaining
    totals. Per-unit fields preserve original lot-rate metadata and support
    legacy snapshots, but Decimal division residue is never reconstructed from
    them for statement-complete replay.
    """

    model_config = ConfigDict(extra="forbid")

    lot_ref: str = Field(min_length=1, max_length=128)
    account_ref: str = Field(min_length=1, max_length=128)
    asset: AssetRef
    quantity: Decimal = Field(gt=0)
    cost_basis_usd: Decimal | None = Field(default=None, ge=0)
    unit_cost_usd: Decimal | None = Field(default=None, ge=0)
    acquired_at: int | None = Field(default=None, ge=0)
    acquisition_sequence: int | None = Field(default=None, ge=0)
    acquisition_leg_index: int = Field(default=0, ge=0)
    basis_source: str = Field(min_length=1, max_length=128)
    basis_override_ref: str | None = Field(default=None, min_length=1, max_length=128)
    basis_last_verified: date | None = None
    acquisition_fee_usd: Decimal | None = Field(default=None, ge=0)
    unit_fee_basis_usd: Decimal | None = Field(default=None, ge=0)
    acquisition_event_id: str | None = Field(default=None, max_length=128)
    acquisition_tx_ref: str | None = Field(default=None, max_length=128)
    origin_lot_ref: str | None = Field(default=None, min_length=1, max_length=128)
    basis_evidence_source: str | None = Field(default=None, min_length=1, max_length=128)
    basis_price_source: str | None = Field(default=None, min_length=1, max_length=128)
    basis_price_as_of: int | None = Field(default=None, ge=0)

    _opaque_account_ref = field_validator("account_ref")(validate_opaque_account_ref)
    _refs_and_sources_non_blank = field_validator(
        "lot_ref",
        "basis_source",
        "basis_override_ref",
        "acquisition_event_id",
        "acquisition_tx_ref",
        "origin_lot_ref",
        "basis_evidence_source",
        "basis_price_source",
    )(validate_non_blank)
    _bounded_quantity = field_validator("quantity")(validate_accounting_decimal)
    _bounded_derived_decimals = field_validator(
        "cost_basis_usd",
        "unit_cost_usd",
        "acquisition_fee_usd",
        "unit_fee_basis_usd",
    )(validate_derived_accounting_decimal)

    @model_validator(mode="after")
    def validate_price_provenance(self) -> Self:
        if (self.basis_price_source is None) != (self.basis_price_as_of is None):
            raise ValueError("basis_price_source and basis_price_as_of must be supplied together")
        effective_cost_basis = (
            self.cost_basis_usd
            if self.cost_basis_usd is not None
            else None
            if self.unit_cost_usd is None
            else exact_decimal_multiply(self.unit_cost_usd, self.quantity)
        )
        effective_fee_basis = (
            self.acquisition_fee_usd
            if self.acquisition_fee_usd is not None
            else exact_decimal_multiply(self.unit_fee_basis_usd or Decimal(0), self.quantity)
        )
        validate_derived_accounting_decimal(effective_cost_basis)
        validate_derived_accounting_decimal(effective_fee_basis)
        if effective_cost_basis is not None and effective_fee_basis > effective_cost_basis:
            raise ValueError("acquisition fee basis cannot exceed effective cost basis")
        if (
            self.unit_cost_usd is not None
            and self.unit_fee_basis_usd is not None
            and self.unit_fee_basis_usd > self.unit_cost_usd
        ):
            raise ValueError("unit fee basis cannot exceed unit cost basis")
        return self


class OpeningStateInput(BaseModel):
    """Method-pinned complete lot snapshot immediately preceding a report window."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0.0"]
    basis_method: Literal["fifo"]
    basis_method_version: Literal["2.0.0"]
    snapshot_complete: Literal[True]
    state_ref: str = Field(min_length=1, max_length=128)
    as_of: int = Field(ge=0)
    source: str = Field(min_length=1, max_length=128)
    last_verified: date
    lots: list[OpeningLotInput] = Field(default_factory=list, max_length=5000)

    _refs_and_source_non_blank = field_validator("state_ref", "source")(validate_non_blank)


class ReportWindowInput(BaseModel):
    """Half-open report bounds plus exactly one opening-history assertion."""

    model_config = ConfigDict(extra="forbid")

    replay_version: Literal["1.0.0"] = "1.0.0"
    start_at: int = Field(ge=0)
    end_at: int = Field(ge=0)
    full_history: bool = False
    opening_state: OpeningStateInput | None = None

    @model_validator(mode="after")
    def validate_replay_source(self) -> Self:
        if self.end_at <= self.start_at:
            raise ValueError("report window end_at must be greater than start_at")
        if self.full_history == (self.opening_state is not None):
            raise ValueError("choose exactly one of full_history or opening_state")
        if self.opening_state is not None and self.opening_state.as_of != self.start_at - 1:
            raise ValueError("opening_state.as_of must immediately precede report start_at")
        return self


__all__ = [
    "AsOfPriceInput",
    "AssetRef",
    "BasisOverrideInput",
    "EventKind",
    "EventLedger",
    "FeeAllocation",
    "FeePayment",
    "LedgerEvent",
    "LedgerLeg",
    "MovementInput",
    "OpeningLotInput",
    "OpeningStateInput",
    "RawTransactionInput",
    "ReportWindowInput",
    "TaxTreatment",
    "TransferTreatment",
    "validate_accounting_decimal",
    "validate_accounting_total_decimal",
    "validate_derived_accounting_decimal",
    "validate_non_blank",
    "validate_opaque_account_ref",
]
