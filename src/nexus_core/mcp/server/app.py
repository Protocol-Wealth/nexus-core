# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""FastMCP server scaffold for nexus-core.

Wraps the regime and scoring engines as MCP tools so Claude, Cursor, and any
other MCP-compatible client can call them directly.

The minimum to stand up a server:

    from nexus_core.mcp.server import build_server
    from nexus_core.engine.regime import RegimeEngine

    engine = RegimeEngine(market_data=my_market, macro_data=my_macro)
    server = build_server(regime_engine=engine)
    server.run()

This is a reference scaffold — production deployments typically add
authentication (OAuth resource server), rate limiting, audit logging, and
response filtering. The ``filters`` parameter lets you wire those in without
modifying this module.

Requires ``fastmcp>=2.0.0``. Install via::

    pip install nexus-core[mcp]
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import asdict
from typing import Any, Protocol

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore[assignment,misc]

from ...data.derivatives import DeribitClient
from ...data.onchain import DefiLlamaClient
from ...data.providers import MacroDataProvider, MarketDataProvider
from ...engine.pricing import (
    OptionKind,
    bs_price,
    cash_secured_put_overlay,
    collar_overlay,
    covered_call_overlay,
    greeks,
)
from ...engine.regime import RegimeEngine, RegimeResult
from ...engine.scoring import ScoringFramework, format_structured

logger = logging.getLogger(__name__)

#: Upper bound on option tenor (days), mirroring the REST surface's le=1095.
_MAX_OPTION_DAYS = 1095


class ResponseFilter(Protocol):
    """Post-process a tool response before it leaves the server.

    Typical uses: PII redaction, tier-based response scrubbing, audit logging.
    Filters are composable — register multiple and they run in sequence.
    """

    def __call__(
        self,
        tool_name: str,
        response: dict[str, Any],
        *,
        auth_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


def build_server(
    *,
    name: str = "nexus-core",
    regime_engine: RegimeEngine | None = None,
    scoring_framework: ScoringFramework | None = None,
    score_context_factory: Callable[[str], Any] | None = None,
    market: MarketDataProvider | None = None,
    macro: MacroDataProvider | None = None,
    deribit: DeribitClient | None = None,
    defillama: DefiLlamaClient | None = None,
    filters: list[ResponseFilter] | None = None,
    disclaimer: str | None = None,
    extra_tools: Sequence[tuple[str, str, Callable[..., str]]] | None = None,
) -> Any:
    """Build a FastMCP server with regime + scoring tools.

    Args:
        name: MCP server name.
        regime_engine: Pre-configured ``RegimeEngine``. If None, regime tools
            are not registered.
        scoring_framework: Pre-configured ``ScoringFramework``. If None,
            scoring tools are not registered.
        score_context_factory: Callable mapping a ticker to a scoring context.
            Required if ``scoring_framework`` is passed.
        filters: Response post-processors applied before return.
        disclaimer: Appended to every financial-content tool response. Keep
            this aligned with your regulator's disclosure requirements.
        extra_tools: Additional tools to register, as ``(name, description,
            fn)`` triples where ``fn`` is a JSON-string-returning callable.
            Kept generic so the library scaffold stays decoupled from any
            specific tool layer — the deployment wires its own tools (e.g. the
            planning gateway) in through here.

    Returns:
        A configured ``FastMCP`` instance. Call ``.run()`` to start.
    """
    if FastMCP is None:
        raise ImportError("fastmcp is required. Install with: pip install nexus-core[mcp]")

    # mask_error_details=True: if any tool body ever raises an unexpected
    # exception, FastMCP returns a generic ToolError instead of leaking str(e)
    # (which could carry an upstream URL, key, or internal path) to the client.
    mcp = FastMCP(name, mask_error_details=True)
    filters = filters or []
    disclaimer = disclaimer or (
        "For educational and research purposes only. Not investment advice. "
        "Past performance is not indicative of future results. Consult a "
        "qualified advisor before making investment decisions."
    )

    # --------------------------- Regime tools ---------------------------

    if regime_engine is not None:

        @mcp.tool()
        def current_regime() -> str:
            """Get the current macro regime classification.

            Returns the regime code, confidence, days in regime, and the
            rationale supporting the classification.
            """
            result = regime_engine.classify()
            response = _serialize_regime(result, disclaimer)
            response = _apply_filters("current_regime", response, filters, {})
            return json.dumps(response, indent=2)

        @mcp.tool()
        def regime_signals() -> str:
            """Get the raw signal readings used for regime classification."""
            signals = regime_engine.fetch_signals()
            response = {"signals": signals.to_dict(), "disclaimer": disclaimer}
            response = _apply_filters("regime_signals", response, filters, {})
            return json.dumps(response, indent=2)

    # --------------------------- Scoring tools ---------------------------

    if scoring_framework is not None and score_context_factory is not None:

        @mcp.tool()
        def score_asset(ticker: str) -> str:
            """Score an asset using the configured N-check framework.

            Args:
                ticker: Asset identifier (e.g. "AAPL", "BTC-USD").

            Returns tier, passed count, per-check results, and any enhancements.
            """
            ctx = score_context_factory(ticker)
            result = scoring_framework.score(ctx, subject=ticker)
            response = format_structured(result)
            response["disclaimer"] = disclaimer
            response = _apply_filters("score_asset", response, filters, {})
            return json.dumps(response, indent=2)

    # ---------------------- Market / macro / DeFi / options ----------------------

    if market is not None:
        _register_market_tools(mcp, market, disclaimer, filters)
        _register_equity_options_tools(mcp, market, disclaimer, filters)
    if macro is not None:
        _register_economic_tools(mcp, macro, disclaimer, filters)
    if deribit is not None:
        _register_crypto_options_tools(mcp, deribit, disclaimer, filters)
    if defillama is not None:
        _register_defi_tools(mcp, defillama, disclaimer, filters)

    # Caller-supplied tools (e.g. the planning gateway). Registered generically
    # so this scaffold never imports a specific deployment's tool layer.
    for tool_name, tool_description, tool_fn in extra_tools or ():
        mcp.tool(tool_fn, name=tool_name, description=tool_description)

    return mcp


# ----------------------------------------------------------------------
# Tool-group registration (market / macro / DeFi / options) — all read-only,
# educational, and composed over the engines/providers. Every response carries
# the disclaimer and runs through the configured ResponseFilters.
# ----------------------------------------------------------------------


def _ok(tool: str, payload: dict[str, Any], filters: list[ResponseFilter], disclaimer: str) -> str:
    return json.dumps(
        _apply_filters(tool, {**payload, "disclaimer": disclaimer}, filters, {}), indent=2
    )


def _err(tool: str, message: str, filters: list[ResponseFilter], disclaimer: str) -> str:
    return json.dumps(
        _apply_filters(tool, {"error": message, "disclaimer": disclaimer}, filters, {}), indent=2
    )


def _validate_option_inputs(
    *,
    spot: float | None = None,
    strike: float | None = None,
    days: int | None = None,
    volatility: float | None = None,
    min_days: int = 0,
) -> str | None:
    """Return an error message if any option input is out of range, else ``None``.

    Preserves the valid Black-Scholes limits: ``days == 0`` (expiry-day intrinsic)
    and ``volatility == 0`` (zero-vol forward intrinsic) stay allowed; only
    negative / non-positive / oversized values are rejected. ``min_days=1`` is
    used for the overlay tools, whose annualized figures divide by the tenor.
    """
    if spot is not None and spot <= 0.0:
        return f"spot must be > 0 (got {spot})"
    if strike is not None and strike <= 0.0:
        return f"strike must be > 0 (got {strike})"
    if days is not None and (days < min_days or days > _MAX_OPTION_DAYS):
        return f"days must be in [{min_days}, {_MAX_OPTION_DAYS}] (got {days})"
    if volatility is not None and volatility < 0.0:
        return f"volatility must be >= 0 (got {volatility})"
    return None


def _annualized_vol(market: MarketDataProvider, symbol: str) -> float:
    """Annualized volatility from ~90d of daily closes; 0.30 fallback."""
    import math
    import statistics

    try:
        bars = market.get_price_history(symbol, days=90, interval="1d")
    except Exception:  # pragma: no cover — provider best-effort
        return 0.30
    closes = [float(b.close) for b in bars if getattr(b, "close", None)]
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 10:
        return 0.30
    return statistics.pstdev(rets) * math.sqrt(252.0)


def _register_market_tools(
    mcp: FastMCP, market: MarketDataProvider, disclaimer: str, filters: list[ResponseFilter]
) -> None:
    @mcp.tool()
    def get_quote(symbol: str) -> str:
        """Latest quote for a stock, ETF, index, or crypto coin id (e.g. AAPL, SPY, bitcoin)."""
        quote = market.get_quote(symbol)
        if quote is None:
            return _err("get_quote", f"No quote for '{symbol}'", filters, disclaimer)
        return _ok("get_quote", {"quote": asdict(quote)}, filters, disclaimer)

    @mcp.tool()
    def get_price_history(symbol: str, days: int = 365) -> str:
        """OHLCV price history covering roughly ``days`` days for a symbol."""
        bars = market.get_price_history(symbol, days=days, interval="1d")
        if not bars:
            return _err("get_price_history", f"No history for '{symbol}'", filters, disclaimer)
        return _ok(
            "get_price_history",
            {"symbol": symbol, "days": days, "bars": [asdict(b) for b in bars]},
            filters,
            disclaimer,
        )


def _register_economic_tools(
    mcp: FastMCP, macro: MacroDataProvider, disclaimer: str, filters: list[ResponseFilter]
) -> None:
    @mcp.tool()
    def get_economic_series(series_id: str) -> str:
        """Latest value for a FRED economic series (e.g. DGS10, DFII10, DTWEXBGS)."""
        if not macro.is_configured():
            return _err("get_economic_series", "FRED API key not configured", filters, disclaimer)
        value = macro.get_series(series_id)
        if value is None:
            return _err("get_economic_series", f"No data for '{series_id}'", filters, disclaimer)
        return _ok(
            "get_economic_series", {"series_id": series_id, "value": value}, filters, disclaimer
        )


def _register_equity_options_tools(
    mcp: FastMCP, market: MarketDataProvider, disclaimer: str, filters: list[ResponseFilter]
) -> None:
    @mcp.tool()
    def option_price(
        spot: float, strike: float, days: int, volatility: float, kind: str = "call"
    ) -> str:
        """Educational Black-Scholes price + Greeks. ``kind``: 'call' or 'put'. Not advice."""
        bad = _validate_option_inputs(spot=spot, strike=strike, days=days, volatility=volatility)
        if bad is not None:
            return _err("option_price", bad, filters, disclaimer)
        k: OptionKind = "call"
        if str(kind).lower().startswith("p"):
            k = "put"
        t = days / 365.0
        return _ok(
            "option_price",
            {
                "spot": spot,
                "strike": strike,
                "days": days,
                "kind": k,
                "price": round(bs_price(spot, strike, t, 0.04, volatility, k), 4),
                "greeks": asdict(greeks(spot, strike, t, 0.04, volatility, k)),
            },
            filters,
            disclaimer,
        )

    @mcp.tool()
    def covered_call(symbol: str, strike: float, days: int) -> str:
        """Educational covered-call overlay illustration on a public ticker (live spot). Not advice."""
        bad = _validate_option_inputs(strike=strike, days=days, min_days=1)
        if bad is not None:
            return _err("covered_call", bad, filters, disclaimer)
        quote = market.get_quote(symbol)
        if quote is None:
            return _err("covered_call", f"No quote for '{symbol}'", filters, disclaimer)
        result = covered_call_overlay(
            quote.price, strike, days, None, sigma=_annualized_vol(market, symbol)
        )
        return _ok(
            "covered_call", {"symbol": symbol, "spot": quote.price, **asdict(result)}, filters, disclaimer
        )

    @mcp.tool()
    def cash_secured_put(symbol: str, strike: float, days: int) -> str:
        """Educational cash-secured-put overlay illustration on a public ticker. Not advice."""
        bad = _validate_option_inputs(strike=strike, days=days, min_days=1)
        if bad is not None:
            return _err("cash_secured_put", bad, filters, disclaimer)
        quote = market.get_quote(symbol)
        if quote is None:
            return _err("cash_secured_put", f"No quote for '{symbol}'", filters, disclaimer)
        result = cash_secured_put_overlay(
            quote.price, strike, days, None, sigma=_annualized_vol(market, symbol)
        )
        return _ok(
            "cash_secured_put",
            {"symbol": symbol, "spot": quote.price, **asdict(result)},
            filters,
            disclaimer,
        )

    @mcp.tool()
    def collar(symbol: str, put_strike: float, call_strike: float, days: int) -> str:
        """Educational protective-collar overlay illustration on a public ticker. Not advice."""
        bad = _validate_option_inputs(strike=put_strike, days=days, min_days=1) or _validate_option_inputs(
            strike=call_strike, days=days, min_days=1
        )
        if bad is not None:
            return _err("collar", bad, filters, disclaimer)
        quote = market.get_quote(symbol)
        if quote is None:
            return _err("collar", f"No quote for '{symbol}'", filters, disclaimer)
        result = collar_overlay(
            quote.price, put_strike, call_strike, days, None, None, sigma=_annualized_vol(market, symbol)
        )
        return _ok(
            "collar", {"symbol": symbol, "spot": quote.price, **asdict(result)}, filters, disclaimer
        )


def _register_crypto_options_tools(
    mcp: FastMCP, deribit: DeribitClient, disclaimer: str, filters: list[ResponseFilter]
) -> None:
    @mcp.tool()
    def crypto_option_instruments(currency: str) -> str:
        """Listed crypto option instruments — BTC/ETH/SOL/XRP/TRX/AVAX (Deribit)."""
        cur = currency.upper()
        supported = deribit.supported_currencies()
        if cur not in supported:
            return _err(
                "crypto_option_instruments",
                f"Unsupported '{currency}' ({'/'.join(supported)})",
                filters,
                disclaimer,
            )
        try:
            instruments = deribit.list_option_instruments(cur)
        except Exception:
            logger.exception("crypto_option_instruments failed for %s", cur)
            return _err("crypto_option_instruments", "upstream options data unavailable", filters, disclaimer)
        return _ok(
            "crypto_option_instruments",
            {"currency": cur, "count": len(instruments), "instruments": [asdict(i) for i in instruments]},
            filters,
            disclaimer,
        )

    @mcp.tool()
    def crypto_option_ticker(instrument_name: str) -> str:
        """Mark price, implied vol + Greeks for a Deribit option instrument."""
        try:
            ticker = deribit.get_option_ticker(instrument_name)
        except Exception:
            logger.exception("crypto_option_ticker failed for %s", instrument_name)
            return _err("crypto_option_ticker", "upstream options data unavailable", filters, disclaimer)
        if ticker is None:
            return _err("crypto_option_ticker", f"No ticker for '{instrument_name}'", filters, disclaimer)
        return _ok("crypto_option_ticker", asdict(ticker), filters, disclaimer)


def _register_defi_tools(
    mcp: FastMCP, defillama: DefiLlamaClient, disclaimer: str, filters: list[ResponseFilter]
) -> None:
    @mcp.tool()
    def defi_protocols(limit: int = 20) -> str:
        """Top DeFi protocols by Total Value Locked (DefiLlama)."""
        protocols = defillama.get_protocols(limit=limit)
        return _ok(
            "defi_protocols",
            {"count": len(protocols), "protocols": [asdict(p) for p in protocols]},
            filters,
            disclaimer,
        )

    @mcp.tool()
    def defi_protocol(slug: str) -> str:
        """TVL detail for one DeFi protocol by DefiLlama slug (e.g. aave, lido)."""
        detail = defillama.get_protocol(slug)
        if detail is None:
            return _err("defi_protocol", f"No protocol '{slug}'", filters, disclaimer)
        return _ok("defi_protocol", detail, filters, disclaimer)

    @mcp.tool()
    def defi_chains() -> str:
        """Aggregate DeFi TVL per blockchain (DefiLlama)."""
        return _ok("defi_chains", {"chains": defillama.get_chains()}, filters, disclaimer)


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


def _apply_filters(
    tool_name: str,
    response: dict[str, Any],
    filters: list[ResponseFilter],
    auth_context: dict[str, Any],
) -> dict[str, Any]:
    for f in filters:
        response = f(tool_name, response, auth_context=auth_context)
    return response


def _serialize_regime(result: RegimeResult, disclaimer: str) -> dict[str, Any]:
    out = result.to_dict()
    out["disclaimer"] = disclaimer
    return out


__all__ = ["ResponseFilter", "build_server"]
