# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""REST API routes for the nexus-core public deployment.

Routes are registered against an :class:`~fastapi.APIRouter` built around
pre-wired engine and provider instances. Handlers are synchronous ``def`` —
FastAPI runs them in a threadpool, which is correct here because the underlying
providers (yfinance, ``httpx``) are blocking.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, Response

from .. import __version__
from ..data.providers import MacroDataProvider, MarketDataProvider
from ..disclaimers import TERSE, with_disclaimer
from ..engine.regime import RegimeEngine

# Edge/browser cache lifetimes (seconds) per endpoint. The deployment fronts
# these with a Cloudflare cache rule set to "respect origin", so these headers
# are the single source of truth for cache duration. Regime signals are already
# cached ~15 min server-side; market history + FRED series change slowly.
_REGIME_TTL = 900
_QUOTE_TTL = 300
_HISTORY_TTL = 3600
_ECONOMIC_TTL = 3600


def build_router(
    *,
    engine: RegimeEngine,
    market: MarketDataProvider,
    macro: MacroDataProvider,
) -> APIRouter:
    """Build the public REST router around pre-wired dependencies.

    Args:
        engine: Configured regime engine.
        market: Market data provider (typically the composite fallback).
        macro: Macro data provider.
    """
    router = APIRouter()

    @router.get("/health", tags=["meta"], summary="Liveness probe")
    def health(response: Response) -> dict[str, Any]:
        """Return a static liveness payload. Excluded from rate limiting."""
        response.headers["Cache-Control"] = "no-store"
        return {"status": "ok", "service": "nexus-core", "version": __version__}

    @router.get("/api/regime", tags=["regime"], summary="Current macro regime classification")
    def get_regime(response: Response) -> dict[str, Any]:
        """Classify the current macro regime.

        Returns the regime code, confidence score, per-signal breakdown, and a
        natural-language rationale. Signals are cached for 15 minutes.
        """
        response.headers["Cache-Control"] = f"public, max-age={_REGIME_TTL}"
        return with_disclaimer(engine.classify().to_dict())

    @router.get("/api/regime/signals", tags=["regime"], summary="Raw regime signal readings")
    def get_signals(response: Response) -> dict[str, Any]:
        """Return the raw signal readings feeding regime classification."""
        response.headers["Cache-Control"] = f"public, max-age={_REGIME_TTL}"
        return with_disclaimer(engine.fetch_signals().to_dict())

    @router.get(
        "/api/market/quote/{symbol}",
        tags=["market"],
        summary="Latest quote for a symbol",
    )
    def get_quote(
        response: Response,
        symbol: str = Path(description="Ticker (e.g. SPY, AAPL) or crypto coin id (e.g. bitcoin)"),
    ) -> dict[str, Any]:
        """Return the latest quote for a stock, ETF, index, or crypto coin id."""
        quote = market.get_quote(symbol)
        if quote is None:
            raise HTTPException(status_code=404, detail=f"No quote available for '{symbol}'")
        response.headers["Cache-Control"] = f"public, max-age={_QUOTE_TTL}"
        return with_disclaimer(asdict(quote))

    @router.get(
        "/api/market/history/{symbol}",
        tags=["market"],
        summary="OHLCV price history for a symbol",
    )
    def get_history(
        response: Response,
        symbol: str = Path(description="Ticker or crypto coin id"),
        days: int = Query(365, ge=1, le=1000, description="Approximate lookback window in days"),
        interval: str = Query("1d", description="Bar interval (e.g. 1d, 1wk)"),
    ) -> dict[str, Any]:
        """Return OHLCV bars covering approximately ``days`` days."""
        bars = market.get_price_history(symbol, days=days, interval=interval)
        if not bars:
            raise HTTPException(
                status_code=404, detail=f"No price history available for '{symbol}'"
            )
        response.headers["Cache-Control"] = f"public, max-age={_HISTORY_TTL}"
        return {
            "symbol": symbol,
            "interval": interval,
            "days": days,
            "bars": [asdict(bar) for bar in bars],
            "disclaimer": TERSE,
        }

    @router.get(
        "/api/economic/{series_id}",
        tags=["economic"],
        summary="Latest value for a FRED economic series",
    )
    def get_economic(
        response: Response,
        series_id: str = Path(description="FRED series id (e.g. DGS10, DFII10, DTWEXBGS)"),
    ) -> dict[str, Any]:
        """Return the latest observed value for a FRED economic data series."""
        if not macro.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Economic data unavailable: FRED_API_KEY is not configured",
            )
        observation = macro.get_series_observation(series_id)
        if observation is None:
            raise HTTPException(status_code=404, detail=f"No data for series '{series_id}'")
        value, as_of = observation
        response.headers["Cache-Control"] = f"public, max-age={_ECONOMIC_TTL}"
        return {
            "series_id": series_id,
            "value": value,
            "as_of": as_of,
            "source": "FRED",
            "disclaimer": TERSE,
        }

    @router.get("/api/usage", tags=["meta"], summary="Market-data cache + provider usage stats")
    def usage(response: Response) -> dict[str, Any]:
        """In-process cache hit-rate + per-provider (MBOUM/MarketStack) call counts.

        Non-sensitive operational metrics — no keys, no client data. Empty when
        the wired market provider does not expose a ``usage_report``.
        """
        report_fn = getattr(market, "usage_report", None)
        report: dict[str, Any] = report_fn() if callable(report_fn) else {}
        response.headers["Cache-Control"] = "public, max-age=30"
        return report

    return router


__all__ = ["build_router"]
