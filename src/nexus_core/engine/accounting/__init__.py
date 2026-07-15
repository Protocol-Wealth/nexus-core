# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Onchain-accounting engine (epic nexus-core#248).

Cost-basis, decoding, price-history, and realized-PnL math over a de-identified
event ledger. P1 the price historian, P2 the event decoder, P3 the FIFO
cost-basis engine.
"""

from __future__ import annotations

from .cost_basis import (
    CostBasisResult,
    CostBasisTotals,
    CostLot,
    DisposalRecord,
    compute_cost_basis,
)
from .event_decoder import (
    PROTOCOL_CATEGORIES,
    classify_kind,
    decode_transaction,
    decode_transactions,
    resolve_category,
)
from .models import (
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
from .pnl import (
    PnlBucket,
    PnlReport,
    PnlYear,
    onchain_pnl_report,
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
    "AsOfPriceInput",
    "AssetRef",
    "BasisOverrideInput",
    "CostBasisResult",
    "CostBasisTotals",
    "CostLot",
    "DefiLlamaPriceSource",
    "DisposalRecord",
    "EventKind",
    "EventLedger",
    "JupiterPriceSource",
    "LedgerEvent",
    "LedgerLeg",
    "MovementInput",
    "PnlBucket",
    "PnlReport",
    "PnlYear",
    "PriceHistorian",
    "PricePoint",
    "PriceQuery",
    "PriceResult",
    "PriceSource",
    "RawTransactionInput",
    "build_default_historian",
    "classify_kind",
    "compute_cost_basis",
    "decode_transaction",
    "decode_transactions",
    "onchain_pnl_report",
    "resolve_category",
]
