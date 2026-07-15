# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Onchain-accounting tool handlers.

Phase 0 (this scaffold) ships a single ``describe`` introspection tool. The
roadmap phases add the real tools (epic nexus-core#248):

- ``price_history`` (P1) — multi-oracle historical prices.
- ``decode_onchain_events`` (P2) — raw tx/logs to a normalized event ledger.
- ``compute_cost_basis`` (P3) — FIFO lot tracking over the ledger.
- ``onchain_pnl_report`` (P4) — realized PnL / disposition tracking.

Handlers are pure ``dict -> dict`` callables, dispatched by the gateway.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .contract import EventLedger

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
    """Scaffold introspection: the planned tool set and the ledger input schema.

    Lets a consumer discover the accounting contract and validate its
    event-ledger shape against the published JSON schema before any real tool
    exists. Ignores its body.
    """
    return {
        "engine": "onchain-accounting",
        "status": "scaffold",
        "plannedTools": list(PLANNED_TOOLS),
        "eventLedgerSchema": EventLedger.model_json_schema(),
    }


def build_tool_handlers() -> dict[str, ToolHandler]:
    """Build the accounting tool-handler registry. Phase 0: ``describe`` only."""
    return {"describe": _describe}


__all__ = ["PLANNED_TOOLS", "ToolHandler", "build_tool_handlers"]
