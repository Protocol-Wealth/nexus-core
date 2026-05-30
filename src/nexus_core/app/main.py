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
from ..data import db
from ..data.macro import FredMacroData
from ..data.market import (
    CachedMarketData,
    CoinGeckoMarketData,
    CompositeMarketData,
    MarketStackMarketData,
    MboumMarketData,
    UsageTrackingMarketData,
    YFinanceMarketData,
)
from ..data.onchain import (
    DeBankClient,
    JupiterClient,
    MerklClient,
    SlipstreamClient,
    TatumClient,
    TheGraphClient,
    VaultsFyiClient,
)
from ..data.providers import MacroDataProvider, MarketDataProvider
from ..engine.regime import RegimeEngine
from .benchmarks import build_benchmarks_router
from .chain import build_chain_router
from .landing import render_landing
from .lp import build_lp_router
from .mcp_guide import render_mcp_guide
from .mcp_mount import build_mcp_app
from .mcp_oauth import MCPAuthGate, build_oauth_router
from .options import build_options_router
from .planning import build_planning_router
from .ratelimit import RateLimitMiddleware
from .routes import build_router
from .scoring import build_score_router
from .snapshots import build_snapshots_router
from .solana import build_solana_router
from .vaults import build_vaults_router
from .wallet import build_wallet_router

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


def build_market_provider() -> CachedMarketData:
    """Assemble the cached, composite market data provider.

    yfinance is the keyless default; MBOUM and MarketStack (keyed, quota-limited)
    and CoinGecko follow in turn. The MBOUM / MarketStack adapters are wrapped in
    usage trackers so the deployment can monitor their quota consumption, and the
    whole composite is wrapped in a TTL cache so repeated requests don't re-hit
    upstream (a keyed provider with no configured key short-circuits to a miss
    without issuing a request).
    """
    providers: list[MarketDataProvider] = []
    try:
        providers.append(YFinanceMarketData())
    except ImportError:
        logger.warning("yfinance not installed; the keyless market provider is unavailable")
    mboum = UsageTrackingMarketData(MboumMarketData(), "mboum")
    marketstack = UsageTrackingMarketData(MarketStackMarketData(), "marketstack")
    providers.append(mboum)
    providers.append(marketstack)
    providers.append(CoinGeckoMarketData())
    return CachedMarketData(CompositeMarketData(providers), tracked=[mboum, marketstack])


def _try_build_mcp_app(
    engine: RegimeEngine, market: MarketDataProvider, macro: MacroDataProvider
) -> Any:
    """Build the MCP-over-HTTP sub-app, or return ``None`` if unavailable."""
    try:
        return build_mcp_app(engine, market, macro)
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
    mcp_app = _try_build_mcp_app(engine, market, macro) if enable_mcp else None
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

    # Innermost: the MCP transport's transparent-OAuth gate. 401s unauthenticated
    # /mcp transport requests when a signing key is configured; a no-op otherwise.
    # Never touches /mcp/tools (planning), /api/*, or /mcp-guide.
    app.add_middleware(MCPAuthGate)

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
    app.include_router(build_wallet_router(debank=DeBankClient()))
    app.include_router(build_chain_router(tatum=TatumClient()))
    app.include_router(build_vaults_router(vaultsfyi=VaultsFyiClient()))
    app.include_router(build_solana_router(jupiter=JupiterClient()))
    app.include_router(
        build_lp_router(
            thegraph=TheGraphClient(),
            tatum=TatumClient(),
            merkl=MerklClient(),
            coingecko=CoinGeckoMarketData(),
            slipstream=SlipstreamClient(TatumClient()),
        )
    )
    app.include_router(build_benchmarks_router(coingecko=CoinGeckoMarketData()))
    app.include_router(build_snapshots_router())
    # Planning tool gateway. Included before the FastMCP `/mcp` mount (below) so
    # the explicit `/mcp/tools/...` routes take precedence over the transport.
    app.include_router(build_planning_router(market=market, regime_engine=engine))
    # Transparent OAuth for the MCP transport (claude.ai connector handshake).
    # These endpoints are public; the gate above protects only the /mcp transport.
    app.include_router(build_oauth_router())

    mcp_enabled = mcp_app is not None

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def landing() -> str:
        return render_landing(mcp_enabled=mcp_enabled)

    @app.get("/mcp-guide", response_class=HTMLResponse, include_in_schema=False)
    def mcp_guide() -> str:
        """How to connect an MCP client (hosted or local) to the server."""
        return render_mcp_guide()

    @app.get("/health/db", include_in_schema=False)
    async def health_db() -> dict[str, str]:
        """DB connectivity probe for the private market-data instance."""
        if not db.is_configured():
            return {"database": "unconfigured"}
        return {"database": "ok" if await db.ping() else "unreachable"}

    if mcp_app is not None:
        app.mount("/mcp", mcp_app)

    return app


__all__ = ["build_market_provider", "create_app"]
