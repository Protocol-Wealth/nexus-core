# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Onchain-accounting tool handlers.

Ships ``describe`` + ``decode_onchain_events`` + ``compute_cost_basis`` +
``onchain_pnl_report`` always; adds ``price_history`` when a
:class:`PriceHistorian` is injected. Roadmap complete (epic nexus-core#248):

- ``price_history`` (P1) — multi-oracle historical prices. **DONE**
- ``decode_onchain_events`` (P2) — raw tx/logs to a normalized event ledger. **DONE**
- ``compute_cost_basis`` (P3) — FIFO lot tracking over the ledger. **DONE**
- ``onchain_pnl_report`` (P4) — realized PnL / disposition tracking. **DONE**

Handlers are pure ``dict -> dict`` callables, dispatched by the gateway.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from ...engine.accounting import (
    ACCOUNTING_METHOD_LAST_VERIFIED,
    ACCOUNTING_METHOD_SOURCE,
    ACCOUNTING_METHOD_VERSION,
    ACCOUNTING_METHODOLOGY_REVIEW_STATUS,
    EVENT_TREATMENT_MATRIX,
    PriceHistorian,
    PriceQuery,
    PriceResult,
    compute_cost_basis,
    decode_transactions,
    onchain_pnl_report,
)
from .contract import (
    AccountingInputError,
    CostBasisRequest,
    DecodeRequest,
    EventLedger,
    PnlReportRequest,
    PriceHistoryRequest,
)

#: A tool handler: takes a validated JSON-object body, returns a JSON-able dict.
ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

#: Tools this engine will expose as the roadmap phases land (epic nexus-core#248).
PLANNED_TOOLS: tuple[str, ...] = (
    "price_history",
    "decode_onchain_events",
    "compute_cost_basis",
    "onchain_pnl_report",
)


def _make_describe_handler(*, price_history_available: bool) -> ToolHandler:
    """Bind introspection to the actual optional-tool registry."""
    available = [
        "describe",
        "decode_onchain_events",
        "compute_cost_basis",
        "onchain_pnl_report",
    ]
    if price_history_available:
        available.append("price_history")

    def handler(_body: dict[str, Any]) -> dict[str, Any]:
        return {
            "engine": "onchain-accounting",
            "status": "available",
            "tools": sorted(available),
            # Compatibility alias retained for contract 0.1.0 consumers.
            "plannedTools": list(PLANNED_TOOLS),
            "eventLedgerSchema": EventLedger.model_json_schema(),
            "costBasisRequestSchema": CostBasisRequest.model_json_schema(),
            "pnlReportRequestSchema": PnlReportRequest.model_json_schema(),
            "methodology": {
                "method": "fifo",
                "methodVersion": ACCOUNTING_METHOD_VERSION,
                "source": ACCOUNTING_METHOD_SOURCE,
                "lastVerified": ACCOUNTING_METHOD_LAST_VERIFIED.isoformat(),
                "reviewStatus": ACCOUNTING_METHODOLOGY_REVIEW_STATUS,
                "eventTreatment": EVENT_TREATMENT_MATRIX,
            },
        }

    return handler


def _decode_onchain_events(body: dict[str, Any]) -> dict[str, Any]:
    """Decode raw transactions into a normalized event ledger. Pure; no I/O."""
    try:
        request = DecodeRequest.model_validate(body)
    except ValidationError as exc:
        raise AccountingInputError("invalid decode_onchain_events request body") from exc
    ledger = decode_transactions(request.transactions)
    counts: dict[str, int] = {}
    for event in ledger.events:
        counts[event.kind.value] = counts.get(event.kind.value, 0) + 1
    payload: dict[str, Any] = ledger.model_dump(mode="json")
    payload["eventCountsByKind"] = counts
    return payload


def _compute_cost_basis(body: dict[str, Any]) -> dict[str, Any]:
    """FIFO cost basis + realized/unrealized PnL over a priced ledger. Pure; no I/O."""
    try:
        request = CostBasisRequest.model_validate(body)
    except ValidationError as exc:
        raise AccountingInputError("invalid compute_cost_basis request body") from exc
    try:
        result = compute_cost_basis(
            request.events,
            overrides=request.overrides,
            as_of_prices=request.as_of_prices,
            report_window=request.report_window,
            method=request.method,
        )
    except ValueError as exc:
        raise AccountingInputError(str(exc)) from exc
    payload: dict[str, Any] = result.model_dump(mode="json")
    return payload


def _onchain_pnl_report(body: dict[str, Any]) -> dict[str, Any]:
    """Realized-PnL / disposition report (FIFO) over a priced ledger. Pure; no I/O."""
    try:
        request = PnlReportRequest.model_validate(body)
    except ValidationError as exc:
        raise AccountingInputError("invalid onchain_pnl_report request body") from exc
    try:
        report = onchain_pnl_report(
            request.events,
            overrides=request.overrides,
            report_window=request.report_window,
            method=request.method,
        )
    except ValueError as exc:
        raise AccountingInputError(str(exc)) from exc
    payload: dict[str, Any] = report.model_dump(mode="json")
    return payload


def _serialize_result(result: PriceResult) -> dict[str, Any]:
    """Wire shape for a price result. Money as a string; a gap as an explicit null."""
    return {
        "coin": result.coin,
        "timestamp": result.timestamp,
        "status": result.status,
        "priceUsd": None if result.price_usd is None else str(result.price_usd),
        "source": result.source,
        "asOf": result.as_of,
        "confidence": result.confidence,
        "reason": result.reason,
    }


def _make_price_history_handler(historian: PriceHistorian) -> ToolHandler:
    """Bind the ``price_history`` tool to a historian instance."""

    def handler(body: dict[str, Any]) -> dict[str, Any]:
        try:
            request = PriceHistoryRequest.model_validate(body)
        except ValidationError as exc:
            raise AccountingInputError("invalid price_history request body") from exc
        queries = [PriceQuery(coin=q.coin, timestamp=q.timestamp) for q in request.queries]
        overrides = {(o.coin, o.timestamp): o.price_usd for o in request.overrides}
        results = historian.price(queries, overrides)
        return {"prices": [_serialize_result(r) for r in results]}

    return handler


def build_tool_handlers(*, price_historian: PriceHistorian | None = None) -> dict[str, ToolHandler]:
    """Build the accounting tool-handler registry.

    ``describe`` is always present; ``price_history`` is registered when a
    historian is injected (production always injects one).
    """
    handlers: dict[str, ToolHandler] = {
        "describe": _make_describe_handler(price_history_available=price_historian is not None),
        "decode_onchain_events": _decode_onchain_events,
        "compute_cost_basis": _compute_cost_basis,
        "onchain_pnl_report": _onchain_pnl_report,
    }
    if price_historian is not None:
        handlers["price_history"] = _make_price_history_handler(price_historian)
    return handlers


__all__ = ["PLANNED_TOOLS", "ToolHandler", "build_tool_handlers"]
