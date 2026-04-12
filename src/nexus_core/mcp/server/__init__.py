# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""FastMCP server — regime-aware tool orchestration with compliance-gated output.

Quick start::

    from nexus_core.mcp.server import build_server
    from nexus_core.engine.regime import RegimeEngine

    server = build_server(regime_engine=RegimeEngine(...))
    server.run()

See :mod:`nexus_core.mcp.server.app` for the full API.
"""

from .app import ResponseFilter, build_server

__all__ = ["ResponseFilter", "build_server"]
