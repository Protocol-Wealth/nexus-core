# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""nexus-core public web application.

A FastAPI app exposing the regime engine and market data as a public,
read-only REST API plus an MCP-over-HTTP transport. This is the deployable
reference surface served at https://nexusmcp.site.

    from nexus_core.app import create_app
    app = create_app()
"""

from .main import build_market_provider, create_app

__all__ = ["build_market_provider", "create_app"]
