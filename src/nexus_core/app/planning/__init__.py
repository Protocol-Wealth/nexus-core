# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Planning MCP tool gateway (consumer contract for pwplan-core).

A small HTTP surface — ``POST /mcp/tools/{tool_id}`` — that runs the pure
:mod:`nexus_core.engine.planning` tools behind a versioned, PII-free, browser-
callable contract. See :mod:`nexus_core.app.planning.contract` for the wire
rules and :mod:`nexus_core.app.planning.gateway` for the router.
"""

from .contract import CONTRACT_VERSION
from .gateway import build_planning_router

__all__ = ["CONTRACT_VERSION", "build_planning_router"]
