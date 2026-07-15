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

from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class LedgerEvent(BaseModel):
    """A single normalized event. ``account_ref`` and ``tx_ref`` are OPAQUE — an
    opaque account id (never a wallet address) and an opaque transaction ref."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128)
    account_ref: str = Field(min_length=1, max_length=128)
    kind: EventKind
    timestamp: int = Field(ge=0, description="unix seconds, UTC")
    tx_ref: str | None = Field(default=None, max_length=128)
    legs: list[LedgerLeg] = Field(min_length=1)
    fee_usd: Decimal | None = Field(default=None, ge=0)


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
    movements: list[MovementInput] = Field(min_length=1)
    tx_ref: str | None = Field(default=None, max_length=128)
    protocol_hint: str | None = Field(default=None, max_length=64)
    method: str | None = Field(default=None, max_length=64)
    fee_usd: Decimal | None = Field(default=None, ge=0)


__all__ = [
    "AssetRef",
    "EventKind",
    "EventLedger",
    "LedgerEvent",
    "LedgerLeg",
    "MovementInput",
    "RawTransactionInput",
]
