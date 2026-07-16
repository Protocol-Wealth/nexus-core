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
``NEXUS_PUBLIC_MCP_PROFILE``      ``full`` (default) or ``demo``.
``NEXUS_ACCESS_MODE``             ``public`` (default) or ``restricted``.
``NEXUS_API_KEYS``                Comma-separated API keys or sha256:<hex> digests.
``NEXUS_RATE_LIMIT_PER_MIN``      Per-IP request budget (default ``60``).
``NEXUS_CORS_ORIGINS``            Comma-separated allow-list (default ``*``).
================================  ===========================================
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from .. import __version__
from ..data import db
from ..data.derivatives import MboumOptionsClient
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
from ..disclaimers import FULL as _FULL_DISCLAIMER
from ..engine.accounting import PriceHistorian, build_default_historian
from ..engine.regime import RegimeEngine
from .access_gate import NexusAccessGate
from .accounting import build_accounting_router
from .agent_discovery import (
    api_catalog_link_header,
    render_api_catalog,
    render_mcp_server_card,
    render_robots_txt,
    render_sitemap_xml,
)
from .benchmarks import build_benchmarks_router
from .chain import build_chain_router
from .disclosure import render_disclosure_card
from .landing import accept_prefers_markdown, render_landing, render_landing_markdown
from .layers import build_layer_router
from .llms_txt import render_llms_txt
from .lp import build_lp_router
from .mcp_guide import render_mcp_guide
from .mcp_mount import build_mcp_app
from .mcp_oauth import MCPAuthGate, build_oauth_router
from .options import build_options_router
from .planning import build_planning_router
from .ratelimit import RateLimitMiddleware
from .routes import build_router
from .scoring import build_score_router
from .security_headers import SecurityHeadersMiddleware
from .snapshots import build_snapshots_router
from .solana import build_solana_router
from .vaults import build_vaults_router
from .wallet import build_wallet_router
from .well_known import render_security_txt

logger = logging.getLogger(__name__)

_DESCRIPTION = f"""\
Open, regime-adaptive financial analysis — market data, macro signals, options,
DeFi analytics, and PII-free planning math. Read-only by design: native MCP can
run as a public demo endpoint, while REST/JSON calculation surfaces can require
a Nexus API key in restricted mode. Remote MCP clients may complete transparent
OAuth with no login.

This is the analytical substrate of the [Protocol Wealth](https://protocolwealthllc.com)
research engine, extracted under Apache-2.0. It carries no client data, no PII,
and no client/advisor workflow state. The planning surface is de-identified
educational math, not an advisory workflow.

*{_FULL_DISCLAIMER}*
"""

#: OpenAPI servers block so /docs "Try it out" + generated clients know the
#: hosted base URL (not just same-origin).
_SERVERS = [
    {"url": "https://nexusmcp.site", "description": "Hosted public deployment"},
    {"url": "/", "description": "This server"},
]

#: Tag descriptions so /docs groups are self-documenting.
_OPENAPI_TAGS = [
    {"name": "regime", "description": "Current macro regime classification + raw signals."},
    {
        "name": "scoring",
        "description": "EMF 8-check durability score over SEC EDGAR fundamentals (educational).",
    },
    {"name": "market", "description": "Quotes + OHLCV history (stocks, ETFs, indices, crypto)."},
    {"name": "economic", "description": "FRED economic series."},
    {
        "name": "options",
        "description": "Black-Scholes pricing + covered-call / CSP / collar overlays + Deribit crypto options (educational).",
    },
    {
        "name": "planning",
        "description": "PII-free retirement-planning tools (pwplan-core contract). Public, browser-callable.",
    },
    {
        "name": "accounting",
        "description": "PII-free onchain-accounting tools (cost basis / decoding / price history / PnL) over a de-identified event ledger.",
    },
    {"name": "lp", "description": "Uniswap V3 / Aerodrome Slipstream LP analytics."},
    {"name": "wallet", "description": "Anonymous EVM wallet balances (DeBank)."},
    {"name": "chain", "description": "Multi-chain native balances (Tatum)."},
    {"name": "vaults", "description": "DeFi vault discovery (vaults.fyi)."},
    {"name": "solana", "description": "Solana SPL token USD prices (Jupiter, keyless)."},
    {"name": "benchmarks", "description": "Base-100 buy-and-hold benchmark returns."},
    {"name": "meta", "description": "Liveness + provider usage stats."},
]


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
    engine: RegimeEngine,
    market: MarketDataProvider,
    macro: MacroDataProvider,
    price_historian: PriceHistorian,
) -> Any:
    """Build the MCP-over-HTTP sub-app, or return ``None`` if unavailable."""
    try:
        return build_mcp_app(
            engine,
            market,
            macro,
            price_historian=price_historian,
        )
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
    price_historian: PriceHistorian | None = None,
    enable_mcp: bool = True,
) -> FastAPI:
    """Build and return the nexus-core FastAPI application.

    Args:
        market: Market data provider. Defaults to the composite of all
            configured sources. Inject a fake for hermetic tests.
        macro: Macro data provider. Defaults to a FRED provider.
        engine: Regime engine. Defaults to one wired from ``market`` + ``macro``.
        price_historian: Onchain accounting price resolver. One instance is
            shared by the restricted REST gateway and native MCP full profile.
        enable_mcp: Whether to mount the MCP-over-HTTP transport. Set ``False``
            in tests that only exercise the REST API.
    """
    if market is None:
        market = build_market_provider()
    if macro is None:
        macro = FredMacroData()
    if engine is None:
        engine = RegimeEngine(market_data=market, macro_data=macro)
    if price_historian is None:
        price_historian = build_default_historian()

    # The MCP sub-app must be built before the FastAPI app so its lifespan can
    # be adopted at construction time.
    mcp_app = _try_build_mcp_app(engine, market, macro, price_historian) if enable_mcp else None
    lifespan = mcp_app.lifespan if mcp_app is not None else None

    app = FastAPI(
        title="Nexus Core",
        description=_DESCRIPTION,
        version=__version__,
        servers=_SERVERS,
        openapi_tags=_OPENAPI_TAGS,
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

    # Optional production gate for REST/JSON calculation surfaces. In
    # NEXUS_ACCESS_MODE=restricted it protects /api/* and the planning JSON
    # gateway (/api/planning/tools/* plus legacy /mcp/tools/*), while leaving the
    # native /mcp demo transport and public docs open.
    app.add_middleware(NexusAccessGate)

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
    # Added last → outermost: baseline security headers land on every response,
    # including the 401s from MCPAuthGate and 429s from the limiter. CSP is
    # scoped to HTML only so JSON/SSE responses are unaffected.
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(build_router(engine=engine, market=market, macro=macro))
    app.include_router(
        build_options_router(
            market=market, regime_engine=engine, mboum_options=MboumOptionsClient()
        )
    )
    app.include_router(build_score_router(market=market, regime_engine=engine))
    app.include_router(build_layer_router())
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
    # Onchain-accounting tool gateway (epic #248). PII-free; the price historian
    # (DefiLlama coins + Jupiter) backs the price_history tool. Mounted before
    # the /mcp transport like the planning gateway.
    app.include_router(build_accounting_router(price_historian=price_historian))
    # Transparent OAuth for the MCP transport (claude.ai connector handshake).
    # These endpoints are public; the gate above protects only the /mcp transport.
    app.include_router(build_oauth_router())

    mcp_enabled = mcp_app is not None

    @app.get("/", include_in_schema=False)
    def landing(request: Request) -> Response:
        # Advertise the agent-discovery resources via an RFC 8288 Link header.
        # Content-negotiated: agents that send `Accept: text/markdown` get a
        # Markdown rendering; browsers (and anything else) get HTML. `Vary:
        # Accept` keeps the Cloudflare edge from serving one to the other.
        headers = {"Link": api_catalog_link_header(), "Vary": "Accept"}
        if accept_prefers_markdown(request.headers.get("accept", "")):
            return PlainTextResponse(
                render_landing_markdown(mcp_enabled=mcp_enabled),
                media_type="text/markdown; charset=utf-8",
                headers=headers,
            )
        return HTMLResponse(
            render_landing(mcp_enabled=mcp_enabled),
            headers=headers,
        )

    @app.get("/mcp-guide", response_class=HTMLResponse, include_in_schema=False)
    def mcp_guide() -> str:
        """How to connect an MCP client (hosted or local) to the server."""
        return render_mcp_guide()

    @app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
    def llms_txt() -> PlainTextResponse:
        """Agent-oriented site map (llmstxt.org): how to USE the server."""
        return PlainTextResponse(
            render_llms_txt(),
            media_type="text/markdown; charset=utf-8",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/.well-known/security.txt", response_class=PlainTextResponse, include_in_schema=False)
    def security_txt() -> PlainTextResponse:
        """RFC 9116 security-contact + disclosure-policy pointer."""
        return PlainTextResponse(
            render_security_txt(),
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/.well-known/ai-disclosure.json", include_in_schema=False)
    def ai_disclosure() -> JSONResponse:
        """Machine-readable AI-system disclosure (pwos-core disclosure-card schema)."""
        return JSONResponse(
            render_disclosure_card(),
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
    def robots_txt() -> PlainTextResponse:
        """robots.txt — AI-crawler rules + Content-Signal + sitemap pointer."""
        return PlainTextResponse(
            render_robots_txt(),
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap_xml() -> Response:
        """Minimal sitemap of the public HTML/text surfaces."""
        return Response(
            render_sitemap_xml(),
            media_type="application/xml",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/.well-known/api-catalog", include_in_schema=False)
    def api_catalog() -> JSONResponse:
        """RFC 9727 API catalogue (application/linkset+json)."""
        return JSONResponse(
            render_api_catalog(),
            media_type="application/linkset+json",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/.well-known/mcp/server-card.json", include_in_schema=False)
    def mcp_server_card() -> JSONResponse:
        """SEP-format MCP Server Card for this deployment's /mcp transport."""
        return JSONResponse(
            render_mcp_server_card(),
            headers={"Cache-Control": "public, max-age=86400"},
        )

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
