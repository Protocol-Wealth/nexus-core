# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""nexus-core public web application.

A FastAPI app exposing the regime engine and market data as a public,
read-only REST API plus an MCP-over-HTTP transport. This is the deployable
reference surface served at https://nexusmcp.site.

    from nexus_core.app import create_app
    app = create_app()
"""

from __future__ import annotations

from typing import Any

__all__ = ["build_market_provider", "create_app"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from .main import build_market_provider, create_app

        exports = {
            "build_market_provider": build_market_provider,
            "create_app": create_app,
        }
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
