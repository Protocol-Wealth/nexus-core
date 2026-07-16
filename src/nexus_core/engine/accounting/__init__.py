# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Onchain-accounting engine (epic nexus-core#248).

Cost-basis, decoding, price-history, and realized-PnL math over a de-identified
event ledger. P1 the price historian, P2 the event decoder, P3 the FIFO
cost-basis engine.
"""

from __future__ import annotations

from .cost_basis import (
    ACCOUNTING_METHOD_LAST_VERIFIED,
    ACCOUNTING_METHOD_SOURCE,
    ACCOUNTING_METHOD_VERSION,
    ACCOUNTING_METHODOLOGY_REVIEW_STATUS,
    EVENT_TREATMENT_MATRIX,
    CalculationAssumption,
    CalculationCompleteness,
    CalculationGap,
    CostBasisResult,
    CostBasisTotals,
    CostLot,
    CoverageMetadata,
    DisposalRecord,
    MethodologyMetadata,
    ReplayMetadata,
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
    FeeAllocation,
    FeePayment,
    LedgerEvent,
    LedgerLeg,
    MovementInput,
    OpeningLotInput,
    OpeningStateInput,
    RawTransactionInput,
    ReportWindowInput,
    TaxTreatment,
    TransferTreatment,
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
    "ACCOUNTING_METHOD_LAST_VERIFIED",
    "ACCOUNTING_METHOD_SOURCE",
    "ACCOUNTING_METHOD_VERSION",
    "ACCOUNTING_METHODOLOGY_REVIEW_STATUS",
    "EVENT_TREATMENT_MATRIX",
    "AsOfPriceInput",
    "AssetRef",
    "BasisOverrideInput",
    "CalculationAssumption",
    "CalculationCompleteness",
    "CalculationGap",
    "CostBasisResult",
    "CostBasisTotals",
    "CostLot",
    "CoverageMetadata",
    "DefiLlamaPriceSource",
    "DisposalRecord",
    "EventKind",
    "EventLedger",
    "FeeAllocation",
    "FeePayment",
    "JupiterPriceSource",
    "LedgerEvent",
    "LedgerLeg",
    "MovementInput",
    "MethodologyMetadata",
    "OpeningLotInput",
    "OpeningStateInput",
    "PnlBucket",
    "PnlReport",
    "PnlYear",
    "PriceHistorian",
    "PricePoint",
    "PriceQuery",
    "PriceResult",
    "PriceSource",
    "RawTransactionInput",
    "ReplayMetadata",
    "ReportWindowInput",
    "TaxTreatment",
    "TransferTreatment",
    "build_default_historian",
    "classify_kind",
    "compute_cost_basis",
    "decode_transaction",
    "decode_transactions",
    "onchain_pnl_report",
    "resolve_category",
]
