# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""MCP-over-HTTP sub-application for the FastAPI deployment.

Isolates the optional ``fastmcp`` dependency: importing this module is always
safe, but :func:`build_mcp_app` raises :class:`ImportError` if ``fastmcp`` is
not installed. The application factory treats that as "serve REST only".
"""

from __future__ import annotations

from typing import Any

from ..engine.regime import RegimeEngine
from ..mcp.server import build_server


def build_mcp_app(regime_engine: RegimeEngine) -> Any:
    """Return a Starlette ASGI app exposing the nexus-core MCP server over HTTP.

    The returned app carries a ``.lifespan`` that the parent FastAPI app must
    adopt for the MCP session manager to initialise.

    Args:
        regime_engine: Configured regime engine wired into the MCP tools.

    Raises:
        ImportError: If ``fastmcp`` is not installed (``build_server`` guards).
    """
    server = build_server(
        name="nexus-core",
        regime_engine=regime_engine,
        scoring_framework=None,
    )
    return server.http_app(path="/")


__all__ = ["build_mcp_app"]
