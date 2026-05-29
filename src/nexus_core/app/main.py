# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""FastAPI application factory for the nexus-core public deployment.

:func:`create_app` wires the data providers, the regime engine, the REST
routes, CORS, rate limiting, the landing page, and — when ``fastmcp`` is
available — the MCP-over-HTTP transport into a single ASGI application.

Configuration is environment-driven so the same image runs unchanged in
local dev and on Cloud Run:

================================  ===========================================
Environment variable              Effect
================================  ===========================================
``FRED_API_KEY``                  Enables the FRED economic-data endpoints.
``MBOUM_API_KEY``                 Adds MBOUM as a market-data fallback.
``MARKETSTACK_API_KEY``           Adds MarketStack as a market-data fallback.
``COINGECKO_API_KEY``             Raises CoinGecko rate limits (optional).
``NEXUS_RATE_LIMIT_PER_MIN``      Per-IP request budget (default ``60``).
``NEXUS_CORS_ORIGINS``            Comma-separated allow-list (default ``*``).
================================  ===========================================
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .. import __version__
from ..data.macro import FredMacroData
from ..data.market import (
    CoinGeckoMarketData,
    CompositeMarketData,
    MarketStackMarketData,
    MboumMarketData,
    YFinanceMarketData,
)
from ..data.providers import MacroDataProvider, MarketDataProvider
from ..engine.regime import RegimeEngine
from .landing import render_landing
from .mcp_mount import build_mcp_app
from .options import build_options_router
from .ratelimit import RateLimitMiddleware
from .routes import build_router
from .scoring import build_score_router

logger = logging.getLogger(__name__)

_DESCRIPTION = """\
Open, regime-adaptive financial analysis — market data, macro signals, and
regime classification. Public and read-only: no account, no API key, no
authentication required.

This is the analytical substrate of the [Protocol Wealth](https://protocolwealthllc.com)
research engine, extracted under Apache-2.0. It carries no client data and no
advisory workflows.

*For educational and research purposes only. Not investment advice.*
"""


def build_market_provider() -> CompositeMarketData:
    """Assemble the composite market data provider from available sources.

    yfinance is the keyless default. MBOUM, MarketStack, and CoinGecko are
    consulted in turn; a keyed provider with no configured key short-circuits
    to a miss without issuing a request.
    """
    providers: list[MarketDataProvider] = []
    try:
        providers.append(YFinanceMarketData())
    except ImportError:
        logger.warning("yfinance not installed; the keyless market provider is unavailable")
    providers.append(MboumMarketData())
    providers.append(MarketStackMarketData())
    providers.append(CoinGeckoMarketData())
    return CompositeMarketData(providers)


def _try_build_mcp_app(engine: RegimeEngine, market: MarketDataProvider) -> Any:
    """Build the MCP-over-HTTP sub-app, or return ``None`` if unavailable."""
    try:
        return build_mcp_app(engine, market)
    except Exception as exc:  # fastmcp missing, or transport build failure
        logger.warning("MCP HTTP transport unavailable (%s); serving REST API only", exc)
        return None


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid %s=%r; falling back to %d", name, raw, default)
        return default


def create_app(
    *,
    market: MarketDataProvider | None = None,
    macro: MacroDataProvider | None = None,
    engine: RegimeEngine | None = None,
    enable_mcp: bool = True,
) -> FastAPI:
    """Build and return the nexus-core FastAPI application.

    Args:
        market: Market data provider. Defaults to the composite of all
            configured sources. Inject a fake for hermetic tests.
        macro: Macro data provider. Defaults to a FRED provider.
        engine: Regime engine. Defaults to one wired from ``market`` + ``macro``.
        enable_mcp: Whether to mount the MCP-over-HTTP transport. Set ``False``
            in tests that only exercise the REST API.
    """
    if market is None:
        market = build_market_provider()
    if macro is None:
        macro = FredMacroData()
    if engine is None:
        engine = RegimeEngine(market_data=market, macro_data=macro)

    # The MCP sub-app must be built before the FastAPI app so its lifespan can
    # be adopted at construction time.
    mcp_app = _try_build_mcp_app(engine, market) if enable_mcp else None
    lifespan = mcp_app.lifespan if mcp_app is not None else None

    app = FastAPI(
        title="Nexus Core",
        description=_DESCRIPTION,
        version=__version__,
        license_info={
            "name": "Apache-2.0",
            "url": "https://www.apache.org/licenses/LICENSE-2.0",
        },
        contact={
            "name": "Protocol Wealth, LLC",
            "url": "https://github.com/Protocol-Wealth/nexus-core",
        },
        lifespan=lifespan,
    )

    cors_origins = [
        origin.strip()
        for origin in os.environ.get("NEXUS_CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ]

    # Added last → outermost: CORS wraps rate-limit responses too, and handles
    # preflight before the limiter sees the request.
    app.add_middleware(
        RateLimitMiddleware,
        limit_per_min=_int_env("NEXUS_RATE_LIMIT_PER_MIN", 60),
        exempt_prefixes=("/health", "/mcp"),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    app.include_router(build_router(engine=engine, market=market, macro=macro))
    app.include_router(build_options_router(market=market))
    app.include_router(build_score_router(market=market, regime_engine=engine))

    mcp_enabled = mcp_app is not None

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def landing() -> str:
        return render_landing(mcp_enabled=mcp_enabled)

    if mcp_app is not None:
        app.mount("/mcp", mcp_app)

    return app


__all__ = ["build_market_provider", "create_app"]
