# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Onchain-accounting engine (epic nexus-core#248).

Cost-basis, decoding, price-history, and realized-PnL math over a de-identified
event ledger. P1 ships the multi-oracle price historian; P2 the event decoder.
"""

from __future__ import annotations

from .event_decoder import (
    PROTOCOL_CATEGORIES,
    classify_kind,
    decode_transaction,
    decode_transactions,
    resolve_category,
)
from .models import (
    AssetRef,
    EventKind,
    EventLedger,
    LedgerEvent,
    LedgerLeg,
    MovementInput,
    RawTransactionInput,
)
from .price_historian import (
    DefiLlamaPriceSource,
    JupiterPriceSource,
    PriceHistorian,
    PricePoint,
    PriceQuery,
    PriceResult,
    PriceSource,
    build_default_historian,
)

__all__ = [
    "PROTOCOL_CATEGORIES",
    "AssetRef",
    "DefiLlamaPriceSource",
    "EventKind",
    "EventLedger",
    "JupiterPriceSource",
    "LedgerEvent",
    "LedgerLeg",
    "MovementInput",
    "PriceHistorian",
    "PricePoint",
    "PriceQuery",
    "PriceResult",
    "PriceSource",
    "RawTransactionInput",
    "build_default_historian",
    "classify_kind",
    "decode_transaction",
    "decode_transactions",
    "resolve_category",
]
