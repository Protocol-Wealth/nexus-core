# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Wire contract for the onchain-accounting tool gateway.

The accounting engine (epic nexus-core#248) computes cost basis, decodes onchain
events, prices history, and reports realized PnL over a **de-identified event
ledger**. Like the planning gateway, it is PII-free by construction:

- ``ACCOUNTING_CONTRACT_VERSION`` — echoed in every successful response.
- Domain models (the event ledger + raw-decoder input) live in
  ``engine/accounting/models.py`` and are re-exported here as the wire contract.
  Every reference is opaque or a public onchain fact; there is no client
  identity, and ``extra="forbid"`` on every model rejects a smuggled field.
- Any identity-shaped key anywhere in a request body is rejected fail-closed;
  the consumer (pw-api) additionally scrubs values before egress.
- Money and quantities are ``Decimal`` — never float.

Clean-room: the accounting methodology is re-derived from public accounting
rules and protocol specs. No AGPL code (e.g. Rotki) is copied.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...engine.accounting.models import (
    AsOfPriceInput,
    AssetRef,
    BasisOverrideInput,
    EventKind,
    EventLedger,
    LedgerEvent,
    LedgerLeg,
    MovementInput,
    RawTransactionInput,
)

#: The accounting contract version. Bump on any breaking request/response change.
ACCOUNTING_CONTRACT_VERSION = "0.1.0"

_MAX_PUBLIC_ERROR_CHARS = 500
_TRACEBACK_MARKERS = (
    "Traceback (most recent call last):",
    "\n  File ",
    "\n    ",
)

#: Identity-shaped keys the engine refuses (case-insensitive, separators ignored).
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
    ignores non-alphanumeric separators.
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


# --- price_history tool input (P1) -------------------------------------------


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


# --- decode_onchain_events tool input (P2) -----------------------------------


class DecodeRequest(BaseModel):
    """Input to the ``decode_onchain_events`` tool: raw transactions to normalize."""

    model_config = ConfigDict(extra="forbid")

    transactions: list[RawTransactionInput] = Field(min_length=1, max_length=2000)


# --- compute_cost_basis tool input (P3) --------------------------------------


class CostBasisRequest(BaseModel):
    """Input to the ``compute_cost_basis`` tool: a priced event ledger, opening-
    basis overrides for transferred-in positions, and optional as-of prices for
    unrealized PnL. FIFO only in v1."""

    model_config = ConfigDict(extra="forbid")

    events: list[LedgerEvent] = Field(min_length=1, max_length=5000)
    overrides: list[BasisOverrideInput] = Field(default_factory=list, max_length=1000)
    as_of_prices: list[AsOfPriceInput] = Field(default_factory=list, max_length=2000)
    method: Literal["fifo"] = "fifo"


__all__ = [
    "ACCOUNTING_CONTRACT_VERSION",
    "IDENTITY_KEYS",
    "AccountingInputError",
    "AsOfPriceInput",
    "AssetRef",
    "BasisOverrideInput",
    "CostBasisRequest",
    "DecodeRequest",
    "EventKind",
    "EventLedger",
    "LedgerEvent",
    "LedgerLeg",
    "MovementInput",
    "PriceHistoryRequest",
    "PriceOverrideInput",
    "PriceQueryInput",
    "RawTransactionInput",
    "find_identity_keys",
]
