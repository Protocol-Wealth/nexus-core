# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""MCP-over-HTTP sub-application for the FastAPI deployment.

Isolates the optional ``fastmcp`` dependency: importing this module is always
safe, but :func:`build_mcp_app` raises :class:`ImportError` if ``fastmcp`` is
not installed. The application factory treats that as "serve REST only".
"""

from __future__ import annotations

from typing import Any

from ..data.derivatives import DeribitClient
from ..data.onchain import DefiLlamaClient
from ..data.providers import MacroDataProvider, MarketDataProvider
from ..engine.regime import RegimeEngine
from ..mcp.server import build_server
from .scoring import build_scoring_context, build_scoring_framework


def build_mcp_app(
    regime_engine: RegimeEngine,
    market: MarketDataProvider,
    macro: MacroDataProvider,
) -> Any:
    """Return a Starlette ASGI app exposing the nexus-core MCP server over HTTP.

    Wires the full educational tool set — regime (current_regime, regime_signals),
    the EMF ``score_asset`` (sharing the REST ``/api/score`` context builder +
    framework, so MCP and REST return identical scores), market quotes/history,
    FRED economic series, DefiLlama TVL, and the options pricing/overlay +
    Deribit crypto-option tools. The returned app carries a ``.lifespan`` the
    parent FastAPI app must adopt for the MCP session manager to initialise.

    Args:
        regime_engine: Configured regime engine.
        market: Market data provider (scoring context + market/options tools).
        macro: Macro data provider (FRED economic-series tool).

    Raises:
        ImportError: If ``fastmcp`` is not installed (``build_server`` guards).
    """
    server = build_server(
        name="nexus-core",
        regime_engine=regime_engine,
        scoring_framework=build_scoring_framework(),
        score_context_factory=lambda ticker: build_scoring_context(
            ticker, market=market, regime_engine=regime_engine
        ),
        market=market,
        macro=macro,
        deribit=DeribitClient(),
        defillama=DefiLlamaClient(),
    )
    return server.http_app(path="/")


__all__ = ["build_mcp_app"]
