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

_EVM_ADDRESS = re.compile(r"0x[0-9a-f]{40}", re.IGNORECASE)
_BITCOIN_BECH32 = re.compile(r"(?:bc1|tb1)[02-9ac-hj-np-z]{20,}", re.IGNORECASE)
_BASE58_ADDRESS = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
_BITCOIN_LEGACY = re.compile(r"[123mn][1-9A-HJ-NP-Za-km-z]{25,34}")


def validate_opaque_account_ref(value: str) -> str:
    """Reject supported-chain wallet shapes where an opaque account ref is required."""
    if (
        _EVM_ADDRESS.fullmatch(value)
        or _BITCOIN_BECH32.fullmatch(value)
        or _BITCOIN_LEGACY.fullmatch(value)
        or _BASE58_ADDRESS.fullmatch(value)
    ):
        raise ValueError("account_ref must be opaque; raw wallet addresses are not accepted")
    return value


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
    chain: str | None = Field(default=None, max_length=32)
    decimals: int | None = Field(default=None, ge=0, le=36)


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

    @model_validator(mode="after")
    def validate_price_provenance(self) -> Self:
        if (self.price_source is None) != (self.price_as_of is None):
            raise ValueError("price_source and price_as_of must be supplied together")
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

    @model_validator(mode="after")
    def validate_treatment_shape(self) -> Self:
        is_transfer = self.kind in (EventKind.transfer_in, EventKind.transfer_out)
        if not is_transfer and (
            self.transfer_ref is not None or self.transfer_treatment is not None
        ):
            raise ValueError("transfer metadata is only valid for transfer events")

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

    @model_validator(mode="after")
    def validate_price_provenance(self) -> Self:
        if (self.price_source is None) != (self.price_as_of is None):
            raise ValueError("price_source and price_as_of must be supplied together")
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

    @model_validator(mode="after")
    def validate_fee_shape(self) -> Self:
        fee_movements = [movement for movement in self.movements if movement.role == "fee"]
        if self.fee_payment == FeePayment.fiat and fee_movements:
            raise ValueError("fiat fee_payment cannot include fee movements")
        return self


# --- cost-basis input (P3) ---------------------------------------------------


class BasisOverrideInput(BaseModel):
    """A manual opening cost basis for a position transferred in (from a
    custodian or another wallet), keyed to the transfer-in event's ``event_id``.
    ``acquired_at`` carries the original acquisition time for the holding period.
    Omitting it preserves an unknown date and prevents statement completeness."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128)
    override_ref: str | None = Field(default=None, min_length=1, max_length=128)
    cost_basis_usd: Decimal = Field(ge=0)
    acquired_at: int | None = Field(default=None, ge=0)
    source: str | None = Field(default=None, min_length=1, max_length=128)
    last_verified: date | None = None


class AsOfPriceInput(BaseModel):
    """A current unit price used to value open lots (unrealized PnL)."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(min_length=1, max_length=128)
    unit_price_usd: Decimal = Field(ge=0)
    source: str | None = Field(default=None, min_length=1, max_length=128)
    as_of: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_price_provenance(self) -> Self:
        if (self.source is None) != (self.as_of is None):
            raise ValueError("source and as_of must be supplied together")
        return self


class OpeningLotInput(BaseModel):
    """One de-identified FIFO lot from an opening-state snapshot."""

    model_config = ConfigDict(extra="forbid")

    lot_ref: str = Field(min_length=1, max_length=128)
    account_ref: str = Field(min_length=1, max_length=128)
    asset: AssetRef
    quantity: Decimal = Field(gt=0)
    unit_cost_usd: Decimal | None = Field(default=None, ge=0)
    acquired_at: int | None = Field(default=None, ge=0)
    acquisition_sequence: int | None = Field(default=None, ge=0)
    basis_source: str = Field(min_length=1, max_length=128)
    basis_override_ref: str | None = Field(default=None, min_length=1, max_length=128)
    basis_last_verified: date | None = None
    unit_fee_basis_usd: Decimal = Field(default=Decimal(0), ge=0)
    acquisition_event_id: str | None = Field(default=None, max_length=128)
    acquisition_tx_ref: str | None = Field(default=None, max_length=128)
    basis_price_source: str | None = Field(default=None, min_length=1, max_length=128)
    basis_price_as_of: int | None = Field(default=None, ge=0)

    _opaque_account_ref = field_validator("account_ref")(validate_opaque_account_ref)

    @model_validator(mode="after")
    def validate_price_provenance(self) -> Self:
        if (self.basis_price_source is None) != (self.basis_price_as_of is None):
            raise ValueError("basis_price_source and basis_price_as_of must be supplied together")
        return self


class OpeningStateInput(BaseModel):
    """Versioned, de-identified lot snapshot immediately preceding a report window."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"]
    state_ref: str = Field(min_length=1, max_length=128)
    as_of: int = Field(ge=0)
    source: str = Field(min_length=1, max_length=128)
    last_verified: date
    lots: list[OpeningLotInput] = Field(default_factory=list, max_length=5000)


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
    "validate_opaque_account_ref",
]
