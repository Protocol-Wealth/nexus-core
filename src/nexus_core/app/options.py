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
import time
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Path, Query, Response

from ..data.derivatives import DeribitClient
from ..data.providers import MarketDataProvider
from ..disclaimers import TERSE
from ..engine.pricing import (
    BookPosition,
    ChainQuote,
    LadderLeg,
    book_mtm,
    bs_price,
    cash_secured_put_overlay,
    collar_overlay,
    covered_call_ladder,
    covered_call_overlay,
    crypto_collar,
    crypto_covered_call,
    crypto_protective_put,
    greeks,
    rank_covered_calls,
    roll_analysis,
    scenario_stress,
    select_by_delta,
)
from ..engine.pricing.black_scholes import OptionKind
from ..engine.pricing.crypto_overlays import Settlement

_OVERLAY_TTL = 300
_CRYPTO_TTL = 60
_PRICE_TTL = 300
_DEFAULT_RATE = 0.04
_DEFAULT_SIGMA = 0.30
_TRADING_DAYS = 252.0
_DISCLAIMER = TERSE


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
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
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


#: Default cap on per-instrument ticker fetches when assembling a chain — keeps
#: a chain request to a bounded number of Deribit round-trips.
_CHAIN_LIMIT = 24
_MS_PER_DAY = 86_400_000.0


def _crypto_spot_settlement(deribit: DeribitClient, currency: str) -> tuple[str, float, Settlement]:
    """Resolve ``(code, live spot, engine settlement)`` for a crypto underlier.

    Raises 404 for an unsupported currency and 502 when no live index price is
    available. Maps Deribit's ``linear_usdc`` to the engine's ``linear``.
    """
    cur = currency.upper()
    model = deribit.settlement_model(cur)
    if model is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unsupported currency '{currency}'. Use {'/'.join(deribit.supported_currencies())}.",
        )
    spot = deribit.get_index_price(cur)
    if spot is None or spot <= 0:
        raise HTTPException(status_code=502, detail=f"No live index price for '{cur}'")
    settlement: Settlement = "inverse" if model == "inverse" else "linear"
    return cur, spot, settlement


def _body_num(body: dict[str, Any], key: str, *, gt: float | None = None) -> float:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=400, detail=f"'{key}' must be a number")
    out = float(value)
    if gt is not None and not out > gt:
        raise HTTPException(status_code=400, detail=f"'{key}' must be > {gt}")
    return out


def _body_opt_num(body: dict[str, Any], key: str) -> float | None:
    value = body.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HTTPException(status_code=400, detail=f"'{key}' must be a number or omitted")
    return float(value)


def _body_int(body: dict[str, Any], key: str, *, ge: int | None = None) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(status_code=400, detail=f"'{key}' must be a whole number")
    if ge is not None and value < ge:
        raise HTTPException(status_code=400, detail=f"'{key}' must be >= {ge}")
    return value


def _ladder_legs(body: dict[str, Any]) -> list[LadderLeg]:
    raw = body.get("legs")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail="'legs' must be a non-empty list")
    legs: list[LadderLeg] = []
    for leg in raw:
        if not isinstance(leg, dict):
            raise HTTPException(status_code=400, detail="each leg must be an object")
        legs.append(
            LadderLeg(
                expiry_days=_body_int(leg, "expiry_days", ge=0),
                strike=_body_num(leg, "strike", gt=0),
                coins=_body_num(leg, "coins", gt=0),
                premium=_body_opt_num(leg, "premium"),
                iv=_body_opt_num(leg, "iv"),
                delta=_body_opt_num(leg, "delta"),
            )
        )
    return legs


def _book_positions(body: dict[str, Any]) -> list[BookPosition]:
    raw = body.get("positions")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail="'positions' must be a non-empty list")
    positions: list[BookPosition] = []
    for pos in raw:
        if not isinstance(pos, dict):
            raise HTTPException(status_code=400, detail="each position must be an object")
        kind = pos.get("kind")
        side = pos.get("side")
        if kind not in ("call", "put"):
            raise HTTPException(status_code=400, detail="position 'kind' must be 'call' or 'put'")
        if side not in ("short", "long"):
            raise HTTPException(status_code=400, detail="position 'side' must be 'short' or 'long'")
        positions.append(
            BookPosition(
                kind=kind,
                side=side,
                strike=_body_num(pos, "strike", gt=0),
                expiry_days=_body_int(pos, "expiry_days", ge=0),
                coins=_body_num(pos, "coins", gt=0),
                entry_premium=_body_num(pos, "entry_premium"),
                iv=_body_opt_num(pos, "iv"),
                mark_premium=_body_opt_num(pos, "mark_premium"),
                label=pos.get("label") if isinstance(pos.get("label"), str) else None,
            )
        )
    return positions


def _num_list(body: dict[str, Any], key: str, *, required: bool) -> list[float]:
    raw = body.get(key)
    if raw is None and not required:
        return []
    if (
        not isinstance(raw, list)
        or not raw
        or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in raw)
    ):
        raise HTTPException(status_code=400, detail=f"'{key}' must be a non-empty list of numbers")
    return [float(x) for x in raw]


def _chain_quotes(
    deribit: DeribitClient,
    currency: str,
    spot: float,
    *,
    max_days: int,
    limit: int,
) -> list[ChainQuote]:
    """Assemble OTM-call :class:`ChainQuote`s for ``currency`` within ``max_days``.

    Lists the instruments, keeps OTM calls (strike > spot) expiring inside the
    window, takes the ``limit`` nearest-the-money strikes (bounding the number of
    ticker round-trips), then fetches each ticker for the mark/IV/delta. The
    expiry timestamp is converted to ``expiry_days`` here so the engine stays
    clock-free.
    """
    now_ms = time.time() * 1000.0
    candidates: list[tuple[Any, int]] = []
    for ins in deribit.list_option_instruments(currency):
        if (ins.option_type or "").lower() != "call":
            continue
        if ins.strike is None or ins.expiration_timestamp is None or ins.strike <= spot:
            continue
        days = (ins.expiration_timestamp - now_ms) / _MS_PER_DAY
        if days <= 0 or days > max_days:
            continue
        candidates.append((ins, int(round(days))))
    candidates.sort(key=lambda c: abs(c[0].strike - spot))
    quotes: list[ChainQuote] = []
    for ins, days in candidates[:limit]:
        ticker = deribit.get_option_ticker(ins.instrument_name)
        quotes.append(
            ChainQuote(
                instrument_name=ins.instrument_name,
                kind="call",
                strike=float(ins.strike),
                expiry_days=days,
                premium=ticker.mark_price if ticker else None,
                delta=ticker.delta if ticker else None,
                mark_iv=ticker.mark_iv if ticker else None,
            )
        )
    return quotes


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
        call_premium: float | None = Query(
            None, description="Call premium; theoretical if omitted"
        ),
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

    # ── Crypto covered-call overwriting suite (settlement-aware) ──

    @router.get(
        "/crypto/{currency}/covered-call",
        summary="Crypto covered-call overwrite illustration (inverse-aware)",
    )
    def crypto_covered_call_route(
        response: Response,
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        strike: float = Query(gt=0, description="Short-call strike (USD)"),
        days: int = Query(ge=1, le=1095, description="Days to expiry"),
        coins: float = Query(1.0, gt=0, description="Coins overwritten"),
        premium: float | None = Query(
            None,
            description="Premium in native unit (coin/inverse, USD/linear); theoretical if omitted",
        ),
        iv: float | None = Query(
            None, description="Implied vol (decimal) for the theoretical path"
        ),
    ) -> dict[str, Any]:
        """Covered-call overwrite on a crypto treasury; live spot + settlement from Deribit."""
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        result = crypto_covered_call(
            spot=spot,
            strike=strike,
            expiry_days=days,
            settlement=settlement,
            coins=coins,
            premium=premium,
            iv=iv,
        )
        response.headers["Cache-Control"] = f"public, max-age={_CRYPTO_TTL}"
        return {"currency": cur, "settlement": settlement, "spot": spot, **asdict(result)}

    @router.get(
        "/crypto/{currency}/covered-call-chain",
        summary="Rank OTM calls by covered-call yield (Deribit)",
    )
    def crypto_covered_call_chain(
        response: Response,
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        max_days: int = Query(
            60, ge=1, le=1095, description="Only calls expiring within this window"
        ),
        coins: float = Query(1.0, gt=0, description="Coins overwritten (per-row income)"),
        target_delta: float | None = Query(
            None, gt=0, lt=1, description="If set, also return the nearest-delta call"
        ),
        top: int = Query(10, ge=1, le=100, description="Cap the ranked rows returned"),
    ) -> dict[str, Any]:
        """Assemble the live OTM-call chain and rank it by annualized covered-call yield."""
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        quotes = _chain_quotes(deribit, cur, spot, max_days=max_days, limit=_CHAIN_LIMIT)
        ranked = rank_covered_calls(
            spot=spot, settlement=settlement, quotes=quotes, coins=coins, top=top
        )
        selected = None
        if target_delta is not None:
            pick = select_by_delta(quotes=quotes, target_delta=target_delta, kind="call")
            if pick is not None:
                selected = {
                    "instrument_name": pick.instrument_name,
                    "strike": pick.strike,
                    "expiry_days": pick.expiry_days,
                    "delta": pick.delta,
                }
        response.headers["Cache-Control"] = f"public, max-age={_CRYPTO_TTL}"
        return {
            "currency": cur,
            "settlement": settlement,
            "spot": spot,
            "considered": len(quotes),
            "ranked": ranked,
            "selected_by_delta": selected,
            "disclaimer": _DISCLAIMER,
        }

    @router.get(
        "/crypto/{currency}/protective-put",
        summary="Crypto protective-put illustration (inverse-aware)",
    )
    def crypto_protective_put_route(
        response: Response,
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        strike: float = Query(gt=0, description="Put-floor strike (USD)"),
        days: int = Query(ge=1, le=1095, description="Days to expiry"),
        coins: float = Query(1.0, gt=0, description="Coins protected"),
        premium: float | None = Query(
            None, description="Premium (native unit); theoretical if omitted"
        ),
        iv: float | None = Query(
            None, description="Implied vol (decimal) for the theoretical path"
        ),
    ) -> dict[str, Any]:
        """Protective put against a crypto holding; live spot + settlement from Deribit."""
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        result = crypto_protective_put(
            spot=spot,
            strike=strike,
            expiry_days=days,
            settlement=settlement,
            coins=coins,
            premium=premium,
            iv=iv,
        )
        response.headers["Cache-Control"] = f"public, max-age={_CRYPTO_TTL}"
        return {"currency": cur, "settlement": settlement, "spot": spot, **asdict(result)}

    @router.get(
        "/crypto/{currency}/collar",
        summary="Crypto protective-collar illustration (inverse-aware)",
    )
    def crypto_collar_route(
        response: Response,
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        put_strike: float = Query(gt=0, description="Protective-put strike (USD)"),
        call_strike: float = Query(gt=0, description="Financing short-call strike (USD)"),
        days: int = Query(ge=1, le=1095, description="Days to expiry"),
        coins: float = Query(1.0, gt=0, description="Coins collared"),
        put_premium: float | None = Query(
            None, description="Put premium (native); theoretical if omitted"
        ),
        call_premium: float | None = Query(
            None, description="Call premium (native); theoretical if omitted"
        ),
        iv: float | None = Query(
            None, description="Implied vol (decimal) for theoretical premiums"
        ),
    ) -> dict[str, Any]:
        """Protective collar (put floor + financing short call) on a crypto holding."""
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        result = crypto_collar(
            spot=spot,
            put_strike=put_strike,
            call_strike=call_strike,
            expiry_days=days,
            settlement=settlement,
            coins=coins,
            put_premium=put_premium,
            call_premium=call_premium,
            iv=iv,
        )
        response.headers["Cache-Control"] = f"public, max-age={_CRYPTO_TTL}"
        return {"currency": cur, "settlement": settlement, "spot": spot, **asdict(result)}

    @router.post("/crypto/{currency}/ladder", summary="Calendar/strike covered-call ladder")
    def crypto_ladder(
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        body: dict[str, Any] = Body(
            ...,
            description="{total_coins, legs:[{expiry_days, strike, coins, premium?, iv?, delta?}]}",
        ),
    ) -> dict[str, Any]:
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        result = covered_call_ladder(
            spot=spot,
            settlement=settlement,
            total_coins=_body_num(body, "total_coins", gt=0),
            legs=_ladder_legs(body),
        )
        return {"currency": cur, "settlement": settlement, **asdict(result)}

    @router.post("/crypto/{currency}/roll", summary="Roll a short call (up/out economics)")
    def crypto_roll(
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        body: dict[str, Any] = Body(..., description="current/new legs + premiums"),
    ) -> dict[str, Any]:
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        result = roll_analysis(
            spot=spot,
            settlement=settlement,
            coins=_body_num(body, "coins", gt=0),
            current_strike=_body_num(body, "current_strike", gt=0),
            current_expiry_days=_body_int(body, "current_expiry_days", ge=0),
            current_entry_premium=_body_num(body, "current_entry_premium"),
            current_close_premium=_body_num(body, "current_close_premium"),
            new_strike=_body_num(body, "new_strike", gt=0),
            new_expiry_days=_body_int(body, "new_expiry_days", ge=0),
            new_open_premium=_body_num(body, "new_open_premium"),
            new_delta=_body_opt_num(body, "new_delta"),
        )
        return {"currency": cur, "settlement": settlement, **asdict(result)}

    @router.post("/crypto/{currency}/book/mtm", summary="Mark an options book + aggregate Greeks")
    def crypto_book_mtm(
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        body: dict[str, Any] = Body(..., description="{coins_held?, positions:[...]}"),
    ) -> dict[str, Any]:
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        result = book_mtm(
            spot=spot,
            settlement=settlement,
            positions=_book_positions(body),
            coins_held=_body_opt_num(body, "coins_held") or 0.0,
        )
        return {"currency": cur, "settlement": settlement, **asdict(result)}

    @router.post("/crypto/{currency}/book/scenario", summary="Spot/IV stress an options book")
    def crypto_book_scenario(
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        body: dict[str, Any] = Body(
            ..., description="{coins_held?, positions:[...], spot_shocks:[...], iv_shocks?:[...]}"
        ),
    ) -> dict[str, Any]:
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        result = scenario_stress(
            spot=spot,
            settlement=settlement,
            positions=_book_positions(body),
            spot_shocks=_num_list(body, "spot_shocks", required=True),
            iv_shocks=_num_list(body, "iv_shocks", required=False) or None,
            coins_held=_body_opt_num(body, "coins_held") or 0.0,
        )
        return {"currency": cur, "settlement": settlement, **asdict(result)}

    return router


__all__ = ["build_options_router"]
