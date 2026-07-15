# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Wire contract for the onchain-accounting tool gateway.

The accounting engine (epic nexus-core#248) computes cost basis, decodes onchain
events, prices history, and reports realized PnL over a **de-identified event
ledger**. Like the planning gateway, it is PII-free by construction:

- ``ACCOUNTING_CONTRACT_VERSION`` — echoed in every successful response; the
  consumer rejects a mismatch.
- The event ledger carries **opaque** asset / account / transaction references
  and public onchain facts only. It never carries client identity, a name, a
  contact, a government id, or a wallet-to-client linkage. Any identity-shaped
  key anywhere in a request body is rejected fail-closed (belt-and-braces with
  ``extra="forbid"`` on every model), and the consumer (pw-api) additionally
  scrubs values before egress.
- Money and quantities are ``Decimal`` — never float — because this is
  accounting math where representation error is a correctness bug.

Clean-room: the accounting methodology is re-derived from public accounting
rules (IRS FIFO / specific-ID) and protocol specifications. No AGPL code (e.g.
Rotki) is copied; patterns may be studied, bytes may not.
"""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: The accounting contract version. Bump on any breaking request/response change.
ACCOUNTING_CONTRACT_VERSION = "0.1.0"

_MAX_PUBLIC_ERROR_CHARS = 500
_TRACEBACK_MARKERS = (
    "Traceback (most recent call last):",
    "\n  File ",
    "\n    ",
)

#: Identity-shaped keys the engine refuses (case-insensitive, separators ignored).
#: Accounting is done on opaque references and public onchain facts; no name,
#: contact, government id, client id, or wallet-to-client linkage is ever needed.
IDENTITY_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "firstname",
        "lastname",
        "fullname",
        "dob",
        "dateofbirth",
        "birthdate",
        "ssn",
        "taxid",
        "email",
        "phone",
        "address",
        "clientid",
        "client",
        "householdid",
        "walletaddress",
        "wallet",
    }
)


def _public_error_message(message: object, *, fallback: str) -> str:
    """Sanitize an error message for the public gateway (no tracebacks, bounded)."""
    if not isinstance(message, str):
        return fallback
    if any(marker in message for marker in _TRACEBACK_MARKERS):
        return fallback
    text = " ".join(message.split()).strip()
    if not text:
        return fallback
    if len(text) > _MAX_PUBLIC_ERROR_CHARS:
        return f"{text[: _MAX_PUBLIC_ERROR_CHARS - 3].rstrip()}..."
    return text


class AccountingInputError(Exception):
    """A malformed or invalid request (maps to HTTP 400)."""

    def __init__(self, message: str) -> None:
        self.public_message = _public_error_message(message, fallback="invalid accounting request")
        super().__init__(self.public_message)


def _normalise_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def find_identity_keys(payload: Any) -> list[str]:
    """Return any identity-shaped keys found anywhere in ``payload``.

    Recurses through nested dicts and lists. Matching is case-insensitive and
    ignores non-alphanumeric separators (so ``client_id`` and ``clientId`` both
    match ``clientid``). The original key spelling is returned for the message.
    """
    found: list[str] = []
    _scan(payload, found)
    return found


def _scan(node: Any, found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and _normalise_key(key) in IDENTITY_KEYS:
                found.append(key)
            _scan(value, found)
    elif isinstance(node, list):
        for item in node:
            _scan(item, found)


# --- The de-identified event ledger ------------------------------------------
#
# The normalized event stream a consumer sends. It is the output of the P2
# decoders and the input to the P3 cost-basis engine. Every reference is opaque
# or a public onchain fact; there is no client-identifying data.


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


# --- price_history tool input (P1) -------------------------------------------
#
# A coin id is DefiLlama-style: ``{chain}:{address}`` (EVM), ``solana:{mint}``,
# or ``coingecko:{id}`` — all public asset identity, no client linkage.


class PriceQueryInput(BaseModel):
    """One coin's USD price at one unix-seconds timestamp."""

    model_config = ConfigDict(extra="forbid")

    coin: str = Field(min_length=1, max_length=256)
    timestamp: int = Field(ge=0, description="unix seconds, UTC")


class PriceOverrideInput(BaseModel):
    """A caller-supplied known price for a (coin, timestamp) the oracles miss."""

    model_config = ConfigDict(extra="forbid")

    coin: str = Field(min_length=1, max_length=256)
    timestamp: int = Field(ge=0)
    price_usd: Decimal = Field(ge=0)


class PriceHistoryRequest(BaseModel):
    """Input to the ``price_history`` tool."""

    model_config = ConfigDict(extra="forbid")

    queries: list[PriceQueryInput] = Field(min_length=1, max_length=500)
    overrides: list[PriceOverrideInput] = Field(default_factory=list, max_length=500)


__all__ = [
    "ACCOUNTING_CONTRACT_VERSION",
    "IDENTITY_KEYS",
    "AccountingInputError",
    "AssetRef",
    "EventKind",
    "EventLedger",
    "LedgerEvent",
    "LedgerLeg",
    "PriceHistoryRequest",
    "PriceOverrideInput",
    "PriceQueryInput",
    "find_identity_keys",
]
