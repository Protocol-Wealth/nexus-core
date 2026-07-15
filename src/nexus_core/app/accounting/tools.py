# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Onchain-accounting tool handlers.

Ships a ``describe`` introspection tool always, and ``price_history`` (P1) when
a :class:`PriceHistorian` is injected. The remaining roadmap tools land later
(epic nexus-core#248):

- ``price_history`` (P1) — multi-oracle historical prices. **DONE**
- ``decode_onchain_events`` (P2) — raw tx/logs to a normalized event ledger.
- ``compute_cost_basis`` (P3) — FIFO lot tracking over the ledger.
- ``onchain_pnl_report`` (P4) — realized PnL / disposition tracking.

Handlers are pure ``dict -> dict`` callables, dispatched by the gateway.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from ...engine.accounting import PriceHistorian, PriceQuery, PriceResult
from .contract import AccountingInputError, EventLedger, PriceHistoryRequest

#: A tool handler: takes a validated JSON-object body, returns a JSON-able dict.
ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

#: Tools this engine will expose as the roadmap phases land (epic nexus-core#248).
PLANNED_TOOLS: tuple[str, ...] = (
    "price_history",
    "decode_onchain_events",
    "compute_cost_basis",
    "onchain_pnl_report",
)


def _describe(_body: dict[str, Any]) -> dict[str, Any]:
    """Scaffold introspection: the planned tool set and the ledger input schema."""
    return {
        "engine": "onchain-accounting",
        "status": "scaffold",
        "plannedTools": list(PLANNED_TOOLS),
        "eventLedgerSchema": EventLedger.model_json_schema(),
    }


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
    handlers: dict[str, ToolHandler] = {"describe": _describe}
    if price_historian is not None:
        handlers["price_history"] = _make_price_history_handler(price_historian)
    return handlers


__all__ = ["PLANNED_TOOLS", "ToolHandler", "build_tool_handlers"]
