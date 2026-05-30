# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Educational options-overlay REST surface.

Exposes the :mod:`nexus_core.engine.pricing` engine + the Deribit crypto-options
client as a public, read-only API:

* ``GET /api/options/price`` — Black-Scholes price + Greeks for given parameters.
* ``GET /api/options/overlay/{covered-call,cash-secured-put,collar}`` — payoff
  illustration of an equity/ETF overlay; spot is fetched live and volatility is
  estimated from recent history when neither a premium nor a sigma is supplied.
* ``GET /api/options/crypto/currencies`` — supported crypto underliers +
  settlement model (Deribit).
* ``GET /api/options/crypto/{currency}/instruments`` — listed option instruments
  for BTC/ETH/SOL/XRP/TRX/AVAX (Deribit).
* ``GET /api/options/crypto/instrument/{name}`` — per-instrument mark price,
  implied vol, and Greeks (Deribit).

Every response is an **educational illustration** over public market data — not
investment advice, a recommendation, or a suitability determination.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Response

from ..data.derivatives import DeribitClient
from ..data.providers import MarketDataProvider
from ..engine.pricing import (
    bs_price,
    cash_secured_put_overlay,
    collar_overlay,
    covered_call_overlay,
    greeks,
)
from ..engine.pricing.black_scholes import OptionKind

_OVERLAY_TTL = 300
_CRYPTO_TTL = 60
_PRICE_TTL = 300
_DEFAULT_RATE = 0.04
_DEFAULT_SIGMA = 0.30
_TRADING_DAYS = 252.0
_DISCLAIMER = "Educational illustration only — not investment advice."


def _spot(market: MarketDataProvider, symbol: str) -> float:
    quote = market.get_quote(symbol)
    if quote is None:
        raise HTTPException(status_code=404, detail=f"No quote available for '{symbol}'")
    return float(quote.price)


def _estimate_sigma(market: MarketDataProvider, symbol: str) -> float:
    """Annualized volatility from ~90d of daily closes; ``_DEFAULT_SIGMA`` fallback."""
    try:
        bars = market.get_price_history(symbol, days=90, interval="1d")
    except Exception:  # pragma: no cover — provider best-effort
        return _DEFAULT_SIGMA
    closes = [float(b.close) for b in bars if getattr(b, "close", None)]
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] > 0
    ]
    if len(rets) < 10:
        return _DEFAULT_SIGMA
    return statistics.pstdev(rets) * math.sqrt(_TRADING_DAYS)


def _sigma_for(
    market: MarketDataProvider, symbol: str, premium: float | None, sigma: float | None
) -> float | None:
    """Resolve the volatility an overlay should use when no premium is given."""
    if premium is not None:
        return sigma  # premium supplied → sigma only used if also given
    if sigma is not None:
        return sigma
    return _estimate_sigma(market, symbol)


def build_options_router(
    *, market: MarketDataProvider, deribit: DeribitClient | None = None
) -> APIRouter:
    """Build the educational options router around the market provider.

    Args:
        market: Market data provider (spot + history for the equity overlays).
        deribit: Deribit client for crypto options. Defaults to a keyless live
            client; inject one wired to a mock transport for hermetic tests.
    """
    router = APIRouter(prefix="/api/options", tags=["options"])
    deribit = deribit or DeribitClient()

    @router.get("/price", summary="Black-Scholes price + Greeks (educational)")
    def price(
        response: Response,
        spot: float = Query(gt=0, description="Underlying price"),
        strike: float = Query(gt=0, description="Strike price"),
        days: int = Query(ge=0, le=1095, description="Calendar days to expiry"),
        vol: float = Query(gt=0, description="Annualized volatility (decimal, e.g. 0.25)"),
        kind: Annotated[OptionKind, Query(description="call or put")] = "call",
        rate: float = Query(_DEFAULT_RATE, description="Risk-free rate (decimal)"),
    ) -> dict[str, Any]:
        """Return the theoretical price and Greeks for a European option."""
        t = days / 365.0
        response.headers["Cache-Control"] = f"public, max-age={_PRICE_TTL}"
        return {
            "spot": spot,
            "strike": strike,
            "days": days,
            "kind": kind,
            "price": round(bs_price(spot, strike, t, rate, vol, kind), 4),
            "greeks": asdict(greeks(spot, strike, t, rate, vol, kind)),
            "disclaimer": _DISCLAIMER,
        }

    @router.get("/overlay/covered-call", summary="Covered-call overlay illustration")
    def covered_call(
        response: Response,
        symbol: str = Query(description="Stock/ETF ticker (spot fetched live)"),
        strike: float = Query(gt=0, description="Short-call strike"),
        days: int = Query(ge=1, le=1095, description="Days to expiry"),
        premium: float | None = Query(None, description="Call premium; theoretical if omitted"),
        sigma: float | None = Query(None, description="Volatility; estimated if omitted"),
        rate: float = Query(_DEFAULT_RATE),
    ) -> dict[str, Any]:
        spot = _spot(market, symbol)
        result = covered_call_overlay(
            spot, strike, days, premium, rate=rate, sigma=_sigma_for(market, symbol, premium, sigma)
        )
        response.headers["Cache-Control"] = f"public, max-age={_OVERLAY_TTL}"
        return {"symbol": symbol, "spot": spot, **asdict(result)}

    @router.get("/overlay/cash-secured-put", summary="Cash-secured-put overlay illustration")
    def cash_secured_put(
        response: Response,
        symbol: str = Query(description="Stock/ETF ticker (spot fetched live)"),
        strike: float = Query(gt=0, description="Short-put strike"),
        days: int = Query(ge=1, le=1095, description="Days to expiry"),
        premium: float | None = Query(None, description="Put premium; theoretical if omitted"),
        sigma: float | None = Query(None, description="Volatility; estimated if omitted"),
        rate: float = Query(_DEFAULT_RATE),
    ) -> dict[str, Any]:
        spot = _spot(market, symbol)
        result = cash_secured_put_overlay(
            spot, strike, days, premium, rate=rate, sigma=_sigma_for(market, symbol, premium, sigma)
        )
        response.headers["Cache-Control"] = f"public, max-age={_OVERLAY_TTL}"
        return {"symbol": symbol, "spot": spot, **asdict(result)}

    @router.get("/overlay/collar", summary="Protective-collar overlay illustration")
    def collar(
        response: Response,
        symbol: str = Query(description="Stock/ETF ticker (spot fetched live)"),
        put_strike: float = Query(gt=0, description="Protective-put strike"),
        call_strike: float = Query(gt=0, description="Covered-call strike"),
        days: int = Query(ge=1, le=1095, description="Days to expiry"),
        put_premium: float | None = Query(None, description="Put premium; theoretical if omitted"),
        call_premium: float | None = Query(None, description="Call premium; theoretical if omitted"),
        sigma: float | None = Query(None, description="Volatility; estimated if omitted"),
        rate: float = Query(_DEFAULT_RATE),
    ) -> dict[str, Any]:
        spot = _spot(market, symbol)
        vol = sigma if sigma is not None else _estimate_sigma(market, symbol)
        result = collar_overlay(
            spot, put_strike, call_strike, days, put_premium, call_premium, rate=rate, sigma=vol
        )
        response.headers["Cache-Control"] = f"public, max-age={_OVERLAY_TTL}"
        return {"symbol": symbol, "spot": spot, **asdict(result)}

    @router.get("/crypto/currencies", summary="Crypto option underliers (Deribit)")
    def crypto_currencies(response: Response) -> dict[str, Any]:
        """Supported crypto option underliers and their settlement model."""
        currencies = deribit.supported_currencies()
        response.headers["Cache-Control"] = f"public, max-age={_CRYPTO_TTL}"
        return {
            "currencies": currencies,
            "settlement": {c: deribit.settlement_model(c) for c in currencies},
            "disclaimer": _DISCLAIMER,
        }

    @router.get(
        "/crypto/{currency}/instruments",
        summary="Listed crypto option instruments (Deribit)",
    )
    def crypto_instruments(
        response: Response,
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
    ) -> dict[str, Any]:
        cur = currency.upper()
        supported = deribit.supported_currencies()
        if cur not in supported:
            raise HTTPException(
                status_code=404,
                detail=f"Unsupported currency '{currency}'. Use {'/'.join(supported)}.",
            )
        instruments = deribit.list_option_instruments(cur)
        response.headers["Cache-Control"] = f"public, max-age={_CRYPTO_TTL}"
        return {
            "currency": cur,
            "count": len(instruments),
            "instruments": [asdict(i) for i in instruments],
            "disclaimer": _DISCLAIMER,
        }

    @router.get(
        "/crypto/instrument/{instrument_name}",
        summary="Crypto option mark price, IV + Greeks (Deribit)",
    )
    def crypto_ticker(
        response: Response,
        instrument_name: str = Path(description="e.g. BTC-27JUN26-100000-C"),
    ) -> dict[str, Any]:
        ticker = deribit.get_option_ticker(instrument_name)
        if ticker is None:
            raise HTTPException(
                status_code=404, detail=f"No ticker for instrument '{instrument_name}'"
            )
        response.headers["Cache-Control"] = f"public, max-age={_CRYPTO_TTL}"
        return {**asdict(ticker), "disclaimer": _DISCLAIMER}

    return router


__all__ = ["build_options_router"]
