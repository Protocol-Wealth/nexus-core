# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""HTTP tool gateway for the onchain-accounting engine.

``POST /api/accounting/tools/{tool_id}`` runs a registered accounting tool;
``GET /api/accounting/tools`` reports the contract version and available tool
ids. Mirrors the planning gateway (``app/planning/gateway.py``) so a consumer
uses the same version-handshake + PII-free posture across both engines.

Contract behaviour (see :mod:`.contract`):

- **Public by default, gated when configured** by the app-level access gate.
- **PII-free.** Any identity-shaped key in the body is rejected ``400``.
- **Versioned.** Every successful response echoes ``contractVersion``.
- **Human-readable errors.** Plain-text bodies: ``400`` bad/invalid request,
  ``404`` unknown tool, ``500`` engine error.

The router must be mounted **before** the FastMCP ``/mcp`` transport.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from ...disclaimers import TERSE
from .contract import (
    ACCOUNTING_CONTRACT_VERSION,
    AccountingInputError,
    find_identity_keys,
)
from .tools import build_tool_handlers

logger = logging.getLogger(__name__)


def _error(status_code: int, message: str) -> PlainTextResponse:
    """Plain-text error — the body is surfaced verbatim in the consumer UI."""
    return PlainTextResponse(message, status_code=status_code, headers={"Cache-Control": "no-store"})


def build_accounting_router() -> APIRouter:
    """Build the accounting tool-gateway router.

    Phase 0 registers only the ``describe`` scaffold tool; the router takes no
    data dependencies yet. Later phases inject a price provider etc.
    """
    router = APIRouter(tags=["accounting"])
    handlers = build_tool_handlers()
    available = sorted(handlers)

    @router.get("/api/accounting/tools", summary="Accounting tools + contract version")
    def list_accounting_tools() -> dict[str, Any]:
        """Version handshake + tool discovery for the accounting contract."""
        return {"contractVersion": ACCOUNTING_CONTRACT_VERSION, "tools": available}

    @router.post(
        "/api/accounting/tools/{tool_id}",
        summary="Invoke an accounting tool",
        response_model=None,
    )
    async def call_accounting_tool(
        tool_id: str, request: Request
    ) -> JSONResponse | PlainTextResponse:
        """Dispatch ``tool_id`` against the request body; return its JSON result."""
        try:
            body = await request.json()
        except Exception:
            return _error(400, "request body must be valid JSON")
        if not isinstance(body, dict):
            return _error(400, "request body must be a JSON object")

        identity = find_identity_keys(body)
        if identity:
            offenders = ", ".join(sorted(set(identity)))
            return _error(
                400,
                f"identity fields are not accepted by this PII-free engine: {offenders}. "
                "Accounting uses opaque references and public onchain facts; remove any "
                "name/contact/id/wallet-address fields.",
            )

        handler = handlers.get(tool_id)
        if handler is None:
            return _error(404, f"unknown tool '{tool_id}'; available: {', '.join(available)}")

        try:
            payload = handler(body)
        except AccountingInputError as exc:
            return _error(400, exc.public_message)
        except Exception:  # defensive: never return a traceback from the public gateway
            logger.warning("accounting tool %r failed with an internal engine error", tool_id)
            return _error(500, "internal accounting engine error")

        payload.setdefault("contractVersion", ACCOUNTING_CONTRACT_VERSION)
        payload.setdefault("disclaimer", TERSE)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    return router


__all__ = ["build_accounting_router"]
