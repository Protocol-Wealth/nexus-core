# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""HTTP tool gateway for the planning engine.

``POST /mcp/tools/{tool_id}`` runs a registered planning tool; ``GET /mcp/tools``
reports the contract version and the available tool ids (a lightweight version
handshake the consumer can poll).

Contract behaviour (see :mod:`.contract`):

- **Public, no auth.** Browser-callable; CORS + preflight are handled by the
  app-level CORS middleware.
- **PII-free.** Any identity-shaped key in the body is rejected ``400``.
- **Versioned.** Every successful response echoes ``contractVersion``.
- **Human-readable errors.** Error bodies are plain text shown verbatim in the
  consumer UI: ``400`` bad/invalid request, ``404`` unknown tool, ``422``
  infeasible plan, ``500`` engine error.

The router must be mounted **before** the FastMCP ``/mcp`` transport so these
explicit routes win over the mount.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from ...data.providers import MarketDataProvider
from .contract import (
    CONTRACT_VERSION,
    PlanningInfeasibleError,
    PlanningInputError,
    find_identity_keys,
)
from .tools import build_tool_handlers

logger = logging.getLogger(__name__)


def _error(status_code: int, message: str) -> PlainTextResponse:
    """Plain-text error — the body is surfaced verbatim in the consumer UI."""
    return PlainTextResponse(message, status_code=status_code, headers={"Cache-Control": "no-store"})


def build_planning_router(*, market: MarketDataProvider) -> APIRouter:
    """Build the planning tool-gateway router with its data dependencies injected."""
    router = APIRouter(tags=["planning"])
    handlers = build_tool_handlers(market=market)
    available = sorted(handlers)

    @router.get("/mcp/tools", summary="Planning tools + contract version")
    def list_planning_tools() -> dict[str, Any]:
        """Version handshake + tool discovery for the planning contract."""
        return {"contractVersion": CONTRACT_VERSION, "tools": available}

    @router.post("/mcp/tools/{tool_id}", summary="Invoke a planning tool", response_model=None)
    async def call_planning_tool(
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
                "Planning uses age, not date of birth; remove any name/contact/id fields.",
            )

        handler = handlers.get(tool_id)
        if handler is None:
            return _error(404, f"unknown tool '{tool_id}'; available: {', '.join(available)}")

        try:
            payload = handler(body)
        except PlanningInputError as exc:
            return _error(400, str(exc))
        except PlanningInfeasibleError as exc:
            return _error(422, str(exc))
        except Exception:  # defensive: log server-side, never leak internals to the client
            logger.exception("planning tool %r raised", tool_id)
            return _error(500, "internal planning engine error")

        payload.setdefault("contractVersion", CONTRACT_VERSION)
        return JSONResponse(payload, headers={"Cache-Control": "no-store"})

    return router


__all__ = ["build_planning_router"]
