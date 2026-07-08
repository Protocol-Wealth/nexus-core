# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Educational options-overlay REST surface.

Exposes the :mod:`nexus_core.engine.pricing` engine + the Deribit crypto-options
client as a public, read-only API:

* ``GET /api/options/price`` — Black-Scholes price + Greeks for given parameters.
* ``GET /api/options/overlay/{covered-call,cash-secured-put,collar}`` — payoff
  illustration of an equity/ETF overlay; spot is fetched live and volatility is
  estimated from recent history when neither a premium nor a sigma is supplied.
* ``POST /api/options/overlay/collar-screen`` — batch (≤25 positions) equity
  collar screen with dividend-aware THEORETICAL Black-Scholes premiums; spot /
  sigma are fetched/estimated per position when omitted.
* ``POST /api/options/overlay/collar-book`` — multi-name collar BOOK assembly
  (≤50 pre-screened candidates): whole-contract sizing against a notional
  target with per-position/per-sector caps plus optional executable fill
  modeling (short-call bid minus long-put ask). An advisor research WORKSHEET —
  no orders, no execution instructions.
* ``GET /api/options/equity/{symbol}/expirations`` — listed equity option
  expiration dates by bucket (weekly/monthly) via MBOUM.
* ``GET /api/options/equity/{symbol}/chain`` — normalized single-expiration
  equity option chain (calls + puts) via MBOUM; ``expiration`` is required so
  a request never dumps the full multi-expiry board.
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
import re
import statistics
import time
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any, cast

from fastapi import APIRouter, Body, HTTPException, Path, Query, Response

from ..data.derivatives import DeribitClient, MboumOptionsClient
from ..data.providers import MarketDataProvider
from ..disclaimers import TERSE
from ..engine.planning.regime import to_generic_regime
from ..engine.pricing import (
    BookPosition,
    ChainQuote,
    CollarBookPosition,
    CollarScreenPosition,
    LadderLeg,
    assemble_collar_book,
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
    iv_term_structure,
    rank_covered_calls,
    regime_conditioned_overwrite,
    roll_analysis,
    scenario_stress,
    screen_collars,
    select_by_delta,
    vol_skew,
)
from ..engine.pricing.black_scholes import OptionKind
from ..engine.pricing.crypto_overlays import Settlement
from ..engine.regime import RegimeEngine

_OVERLAY_TTL = 300
_CRYPTO_TTL = 60
_PRICE_TTL = 300
#: Expiration lists move rarely (new weeklies appear weekly) — cache long-ish.
_EQUITY_EXPIRATIONS_TTL = 3600
#: A live chain is quote data — cache briefly, like the crypto surface.
_EQUITY_CHAIN_TTL = 60
_DEFAULT_RATE = 0.04
_DEFAULT_SIGMA = 0.30
_TRADING_DAYS = 252.0
_DISCLAIMER = TERSE
_MAX_EXPIRY_DAYS = 1095
_COLLAR_SCREEN_MAX_POSITIONS = 25
_COLLAR_BOOK_MAX_POSITIONS = 50
_COLLAR_BOOK_NOTIONAL_MIN = 10_000.0
_COLLAR_BOOK_NOTIONAL_MAX = 1e9
_COLLAR_BOOK_N_MIN = 1
_COLLAR_BOOK_N_MAX = 50
_COLLAR_BOOK_WEIGHT_MIN = 1.0
_COLLAR_BOOK_WEIGHT_MAX = 100.0


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

#: Ticker shape accepted by the equity option chain routes (Yahoo-style
#: symbols: AAPL, BRK.B, BF-B). Anything else 404s before touching the vendor.
_EQUITY_SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-]{1,10}$")


def _equity_option_symbol(symbol: str) -> str:
    """Validate + upper-case an equity option symbol; 404 on a bad shape."""
    if not _EQUITY_SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(status_code=404, detail=f"Unknown symbol '{symbol}'")
    return symbol.upper()


def _equity_option_expiration(expiration: str) -> str:
    """Validate an ``expiration`` query value as a real ISO date; 422 otherwise.

    FastAPI's pattern check already rejects non-``YYYY-MM-DD`` shapes with a
    422; this catches shape-valid non-dates (e.g. ``2026-13-45``) at the same
    status so the client sees one consistent validation contract.
    """
    try:
        return datetime.strptime(expiration, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="'expiration' must be a calendar date in YYYY-MM-DD format",
        ) from exc


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


def _collar_screen_params(body: dict[str, Any]) -> tuple[float, float, float, float]:
    """Validated ``(put_otm_pct, call_min_otm_pct, target_call_delta, risk_free_rate)``."""
    put_otm = _body_opt_num(body, "put_otm_pct")
    put_otm = 15.0 if put_otm is None else put_otm
    if not 0.0 < put_otm < 100.0:
        raise HTTPException(status_code=400, detail="'put_otm_pct' must be in (0, 100)")
    call_min_otm = _body_opt_num(body, "call_min_otm_pct")
    call_min_otm = 1.0 if call_min_otm is None else call_min_otm
    if not 0.0 <= call_min_otm < 100.0:
        raise HTTPException(status_code=400, detail="'call_min_otm_pct' must be in [0, 100)")
    target_delta = _body_opt_num(body, "target_call_delta")
    target_delta = 0.30 if target_delta is None else target_delta
    if not 0.0 < target_delta < 1.0:
        raise HTTPException(status_code=400, detail="'target_call_delta' must be in (0, 1)")
    rate = _body_opt_num(body, "risk_free_rate")
    return put_otm, call_min_otm, target_delta, _DEFAULT_RATE if rate is None else rate


def _collar_screen_positions(
    market: MarketDataProvider, body: dict[str, Any]
) -> list[CollarScreenPosition]:
    """Parse + validate the collar-screen ``positions`` body list.

    Spot is fetched via :func:`_spot` and sigma estimated via
    :func:`_estimate_sigma` when a position omits them.
    """
    raw = body.get("positions")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail="'positions' must be a non-empty list")
    if len(raw) > _COLLAR_SCREEN_MAX_POSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"'positions' accepts at most {_COLLAR_SCREEN_MAX_POSITIONS} entries",
        )
    positions: list[CollarScreenPosition] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail="each position must be an object")
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise HTTPException(
                status_code=400, detail="position 'symbol' must be a non-empty string"
            )
        expiry_days = _body_int(entry, "expiry_days", ge=1)
        if expiry_days > _MAX_EXPIRY_DAYS:
            raise HTTPException(
                status_code=400, detail=f"'expiry_days' must be <= {_MAX_EXPIRY_DAYS}"
            )
        spot = _body_opt_num(entry, "spot")
        if spot is not None and spot <= 0.0:
            raise HTTPException(status_code=400, detail="'spot' must be > 0 when supplied")
        sigma = _body_opt_num(entry, "sigma")
        if sigma is not None and sigma <= 0.0:
            raise HTTPException(status_code=400, detail="'sigma' must be > 0 when supplied")
        dividend_yield = _body_opt_num(entry, "dividend_yield")
        if dividend_yield is not None and not 0.0 <= dividend_yield < 1.0:
            raise HTTPException(
                status_code=400,
                detail="'dividend_yield' must be a decimal fraction in [0, 1) when supplied",
            )
        positions.append(
            CollarScreenPosition(
                symbol=symbol,
                spot=spot if spot is not None else _spot(market, symbol),
                sigma=sigma if sigma is not None else _estimate_sigma(market, symbol),
                expiry_days=expiry_days,
                dividend_yield=dividend_yield if dividend_yield is not None else 0.0,
            )
        )
    return positions


def _body_opt_int(body: dict[str, Any], key: str, *, default: int) -> int:
    value = body.get(key)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise HTTPException(status_code=400, detail=f"'{key}' must be a whole number or omitted")
    return cast(int, value)


def _body_opt_str(body: dict[str, Any], key: str) -> str | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"'{key}' must be a string or omitted")
    return value


def _collar_book_params(body: dict[str, Any]) -> dict[str, float | int]:
    """Validated keyword arguments for :func:`assemble_collar_book`.

    Bounds: ``notional_target`` in [10,000, 1e9]; the three ``n_positions_*``
    counts in [1, 50] with ``min <= max``; the two weight caps in [1, 100].
    """
    notional = _body_opt_num(body, "notional_target")
    notional = 1_000_000.0 if notional is None else notional
    if not _COLLAR_BOOK_NOTIONAL_MIN <= notional <= _COLLAR_BOOK_NOTIONAL_MAX:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'notional_target' must be in [{_COLLAR_BOOK_NOTIONAL_MIN:.0f}, "
                f"{_COLLAR_BOOK_NOTIONAL_MAX:.0f}]"
            ),
        )
    n_min = _body_opt_int(body, "n_positions_min", default=12)
    n_max = _body_opt_int(body, "n_positions_max", default=25)
    n_target = _body_opt_int(body, "n_positions_target", default=15)
    for key, value in (
        ("n_positions_min", n_min),
        ("n_positions_max", n_max),
        ("n_positions_target", n_target),
    ):
        if not _COLLAR_BOOK_N_MIN <= value <= _COLLAR_BOOK_N_MAX:
            raise HTTPException(
                status_code=400,
                detail=f"'{key}' must be in [{_COLLAR_BOOK_N_MIN}, {_COLLAR_BOOK_N_MAX}]",
            )
    if n_min > n_max:
        raise HTTPException(
            status_code=400, detail="'n_positions_min' must be <= 'n_positions_max'"
        )
    weights: dict[str, float] = {}
    for key, default in (("max_position_weight_pct", 12.0), ("max_sector_weight_pct", 25.0)):
        weight = _body_opt_num(body, key)
        weight = default if weight is None else weight
        if not _COLLAR_BOOK_WEIGHT_MIN <= weight <= _COLLAR_BOOK_WEIGHT_MAX:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{key}' must be in [{_COLLAR_BOOK_WEIGHT_MIN:.0f}, "
                    f"{_COLLAR_BOOK_WEIGHT_MAX:.0f}]"
                ),
            )
        weights[key] = weight
    return {
        "notional_target": notional,
        "n_positions_min": n_min,
        "n_positions_max": n_max,
        "n_positions_target": n_target,
        "max_position_weight_pct": weights["max_position_weight_pct"],
        "max_sector_weight_pct": weights["max_sector_weight_pct"],
    }


def _collar_book_positions(body: dict[str, Any]) -> list[CollarBookPosition]:
    """Parse + validate the collar-book ``positions`` body list (1..50 entries).

    ``symbol``, ``spot``, ``dte``, and ``net_credit`` are required per entry;
    type errors 400. Degenerate VALUES (``spot <= 0``, ``dte <= 0``) pass
    through — the engine excludes them with a structured reason. Optional
    ``call_bid`` + ``put_ask`` or ``executable_net_credit`` let callers report a
    conservative executable-yield haircut versus midpoint credit.
    """
    raw = body.get("positions")
    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail="'positions' must be a non-empty list")
    if len(raw) > _COLLAR_BOOK_MAX_POSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"'positions' accepts at most {_COLLAR_BOOK_MAX_POSITIONS} entries",
        )
    positions: list[CollarBookPosition] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail="each position must be an object")
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not symbol.strip():
            raise HTTPException(
                status_code=400, detail="position 'symbol' must be a non-empty string"
            )
        dividend = _body_opt_num(entry, "dividend_income_window")
        positions.append(
            CollarBookPosition(
                symbol=symbol,
                spot=_body_num(entry, "spot"),
                dte=_body_int(entry, "dte"),
                net_credit=_body_num(entry, "net_credit"),
                dividend_income_window=0.0 if dividend is None else dividend,
                score=_body_opt_num(entry, "score"),
                sector=_body_opt_str(entry, "sector"),
                expiration=_body_opt_str(entry, "expiration"),
                put_strike=_body_opt_num(entry, "put_strike"),
                call_strike=_body_opt_num(entry, "call_strike"),
                floor_pct=_body_opt_num(entry, "floor_pct"),
                cap_pct=_body_opt_num(entry, "cap_pct"),
                executable_net_credit=_body_opt_num(entry, "executable_net_credit"),
                call_bid=_body_opt_num(entry, "call_bid"),
                put_ask=_body_opt_num(entry, "put_ask"),
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
    candidates.sort(key=lambda c: abs(cast(float, c[0].strike) - spot))
    quotes: list[ChainQuote] = []
    for ins, days in candidates[:limit]:
        ticker = deribit.get_option_ticker(ins.instrument_name)
        quotes.append(
            ChainQuote(
                instrument_name=ins.instrument_name,
                kind="call",
                strike=float(cast(float, ins.strike)),
                expiry_days=days,
                premium=ticker.mark_price if ticker else None,
                delta=ticker.delta if ticker else None,
                mark_iv=ticker.mark_iv if ticker else None,
            )
        )
    return quotes


def _skew_chain(
    deribit: DeribitClient,
    currency: str,
    spot: float,
    *,
    target_days: int,
    limit: int,
) -> tuple[list[ChainQuote], int | None]:
    """Single-expiry call chain (near-ATM through OTM) for the vol skew.

    Unlike the yield chain (OTM-only, multi-expiry), the skew needs a smile at
    *one* tenor: pick the expiry nearest ``target_days``, keep its calls in a
    [0.9, 2.0]×spot band (so the ATM reference is captured), take the ``limit``
    nearest-the-money, and fetch each ticker. Returns ``(quotes, expiry_days)``.
    """
    now_ms = time.time() * 1000.0
    by_expiry: list[tuple[Any, int]] = []
    for ins in deribit.list_option_instruments(currency):
        if (ins.option_type or "").lower() != "call":
            continue
        if ins.strike is None or ins.expiration_timestamp is None:
            continue
        if not (0.9 * spot <= ins.strike <= 2.0 * spot):
            continue
        days = (ins.expiration_timestamp - now_ms) / _MS_PER_DAY
        if days > 0:
            by_expiry.append((ins, int(round(days))))
    if not by_expiry:
        return [], None
    expiry = min({d for _, d in by_expiry}, key=lambda d: abs(d - target_days))
    at_expiry = sorted(
        (ins for ins, d in by_expiry if d == expiry),
        key=lambda i: abs(cast(float, i.strike) - spot),
    )
    quotes: list[ChainQuote] = []
    for ins in at_expiry[:limit]:
        ticker = deribit.get_option_ticker(ins.instrument_name)
        quotes.append(
            ChainQuote(
                instrument_name=ins.instrument_name,
                kind="call",
                strike=float(cast(float, ins.strike)),
                expiry_days=expiry,
                premium=ticker.mark_price if ticker else None,
                delta=ticker.delta if ticker else None,
                mark_iv=ticker.mark_iv if ticker else None,
            )
        )
    return quotes, expiry


def build_options_router(
    *,
    market: MarketDataProvider,
    deribit: DeribitClient | None = None,
    regime_engine: RegimeEngine | None = None,
    mboum_options: MboumOptionsClient | None = None,
) -> APIRouter:
    """Build the educational options router around the market provider.

    Args:
        market: Market data provider (spot + history for the equity overlays).
        deribit: Deribit client for crypto options. Defaults to a keyless live
            client; inject one wired to a mock transport for hermetic tests.
        regime_engine: Live regime classifier. Required for the regime-conditioned
            overwrite endpoint; that route 503s when it is not wired.
        mboum_options: MBOUM equity option chain client. Defaults to one built
            from ``MBOUM_API_KEY``; the equity chain routes 503 when no key is
            configured. Inject one wired to a mock transport for hermetic tests.
    """
    router = APIRouter(prefix="/api/options", tags=["options"])
    deribit = deribit or DeribitClient()
    mboum_options = mboum_options or MboumOptionsClient()

    def _require_equity_options() -> MboumOptionsClient:
        """The configured equity chain client, or a 503 when the key is absent."""
        if not mboum_options.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Equity option chain data unavailable: no MBOUM_API_KEY configured",
            )
        return mboum_options

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

    @router.post(
        "/overlay/collar-screen",
        summary="Batch equity collar screen (dividend-aware, theoretical)",
    )
    def collar_screen(
        response: Response,
        body: dict[str, Any] = Body(
            ...,
            description=(
                "{positions:[{symbol, expiry_days, spot?, sigma?, dividend_yield?}] (max 25), "
                "put_otm_pct?, call_min_otm_pct?, target_call_delta?, risk_free_rate?}"
            ),
        ),
    ) -> dict[str, Any]:
        """Screen up to 25 equity/ETF positions for theoretical protective collars.

        Per position: the put strike sits ``put_otm_pct`` below spot and the call
        strike targets ``target_call_delta`` (floored ``call_min_otm_pct`` above
        spot), both snapped to an approximate strike grid; premiums are
        THEORETICAL Black-Scholes values with each position's ``dividend_yield``
        threaded through. Results are ranked net-credit-first, then by total
        annualized income. Spot is fetched live and sigma estimated from recent
        history when omitted.
        """
        put_otm_pct, call_min_otm_pct, target_call_delta, risk_free_rate = _collar_screen_params(
            body
        )
        positions = _collar_screen_positions(market, body)
        results = screen_collars(
            positions,
            put_otm_pct=put_otm_pct,
            call_min_otm_pct=call_min_otm_pct,
            target_call_delta=target_call_delta,
            risk_free_rate=risk_free_rate,
        )
        response.headers["Cache-Control"] = f"public, max-age={_OVERLAY_TTL}"
        return {
            "screen": [asdict(r) for r in results],
            "count": len(results),
            "disclaimer": _DISCLAIMER,
        }

    @router.post(
        "/overlay/collar-book",
        summary="Multi-name collar book assembly (advisor research worksheet)",
    )
    def collar_book(
        response: Response,
        body: dict[str, Any] = Body(
            ...,
            description=(
                "{positions:[{symbol, spot, dte, net_credit, dividend_income_window?, "
                "score?, sector?, expiration?, put_strike?, call_strike?, floor_pct?, "
                "cap_pct?, executable_net_credit?, call_bid?, put_ask?}] (1..50), "
                "notional_target?, n_positions_target?, "
                "n_positions_min?, n_positions_max?, max_position_weight_pct?, "
                "max_sector_weight_pct?}"
            ),
        ),
    ) -> dict[str, Any]:
        """Assemble a multi-name collar BOOK from up to 50 pre-screened candidates.

        THIS IS AN ADVISOR RESEARCH WORKSHEET (``basis:
        advisor_research_worksheet``): it sizes whole-contract positions
        against a notional target with per-position and per-sector caps and
        reports the resulting arithmetic — deployed notional, cash residual,
        income, capital-weighted floor/cap geometry, and every price-tier /
        sector-cap / degenerate exclusion. It places NO orders and produces NO
        execution instructions; the portfolio yield is reported without any
        yield-band policing. Dollar inputs are per share; candidates with
        ``spot <= 0`` or ``dte <= 0`` are excluded with a structured reason
        rather than rejected. If ``call_bid`` + ``put_ask`` or
        ``executable_net_credit`` are supplied, the output includes conservative
        executable income/yield and the fill haircut versus midpoint credit.
        """
        params = _collar_book_params(body)
        positions = _collar_book_positions(body)
        result = assemble_collar_book(
            positions,
            notional_target=float(params["notional_target"]),
            n_positions_min=int(params["n_positions_min"]),
            n_positions_max=int(params["n_positions_max"]),
            n_positions_target=int(params["n_positions_target"]),
            max_position_weight_pct=float(params["max_position_weight_pct"]),
            max_sector_weight_pct=float(params["max_sector_weight_pct"]),
        )
        response.headers["Cache-Control"] = f"public, max-age={_OVERLAY_TTL}"
        return {
            "basis": "advisor_research_worksheet",
            "book": asdict(result),
            "count": len(positions),
            "disclaimer": _DISCLAIMER,
        }

    @router.get(
        "/equity/{symbol}/expirations",
        summary="Listed equity option expirations (MBOUM)",
    )
    def equity_option_expirations(
        response: Response,
        symbol: str = Path(description="Stock/ETF ticker, e.g. AAPL"),
    ) -> dict[str, Any]:
        """Expiration dates with listed options for one equity/ETF, by bucket.

        Public read-only vendor (MBOUM) data behind the service's per-IP rate
        limiter. Returns ``{"weekly": [...], "monthly": [...]}`` ISO dates —
        feed one into ``/equity/{symbol}/chain?expiration=`` for the board.
        503 when the server has no MBOUM key configured.
        """
        sym = _equity_option_symbol(symbol)
        provider = _require_equity_options()
        expirations = provider.list_expirations(sym)
        if expirations is None:
            raise HTTPException(
                status_code=502, detail=f"No expiration data available for '{sym}'"
            )
        if not any(expirations.values()):
            raise HTTPException(
                status_code=404, detail=f"No listed option expirations for '{sym}'"
            )
        response.headers["Cache-Control"] = f"public, max-age={_EQUITY_EXPIRATIONS_TTL}"
        return {"symbol": sym, "expirations": expirations, "disclaimer": _DISCLAIMER}

    @router.get(
        "/equity/{symbol}/chain",
        summary="Equity option chain for ONE expiration (MBOUM)",
    )
    def equity_option_chain(
        response: Response,
        symbol: str = Path(description="Stock/ETF ticker, e.g. AAPL"),
        expiration: str = Query(
            pattern=r"^\d{4}-\d{2}-\d{2}$",
            description="Expiration date (YYYY-MM-DD) from /equity/{symbol}/expirations",
        ),
    ) -> dict[str, Any]:
        """Normalized calls/puts board for one equity/ETF at one expiration.

        Public read-only vendor (MBOUM) data behind the service's per-IP rate
        limiter; ``expiration`` is REQUIRED — a request is always bounded to a
        single expiration (never the full board), which caps both the payload
        and vendor usage. Rows carry parsed floats/ints/ISO dates only (strike,
        bid/ask/mid/last, volume, open interest, iv as a decimal fraction,
        delta, expiration + type, next earnings, ex-dividend date), sorted by
        strike. 503 when the server has no MBOUM key configured.
        """
        sym = _equity_option_symbol(symbol)
        exp = _equity_option_expiration(expiration)
        provider = _require_equity_options()
        chain = provider.get_chain(sym, exp)
        if chain is None:
            raise HTTPException(
                status_code=502, detail=f"No option chain data available for '{sym}'"
            )
        if not chain.calls and not chain.puts:
            raise HTTPException(
                status_code=404,
                detail=f"No option chain for '{sym}' at expiration {exp}",
            )
        response.headers["Cache-Control"] = f"public, max-age={_EQUITY_CHAIN_TTL}"
        return {
            "symbol": sym,
            "expiration": exp,
            "count": {"calls": len(chain.calls), "puts": len(chain.puts)},
            "calls": [asdict(q) for q in chain.calls],
            "puts": [asdict(q) for q in chain.puts],
            "disclaimer": _DISCLAIMER,
        }

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
        "/crypto/{currency}/iv-term-structure",
        summary="Near-ATM IV term structure (which tenor pays richest)",
    )
    def crypto_iv_term_structure(
        response: Response,
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        max_days: int = Query(120, ge=1, le=1095, description="Tenor window"),
    ) -> dict[str, Any]:
        """Near-ATM implied-vol curve across expiries from the live Deribit chain."""
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        # Wider fetch than the yield chain so multiple tenors are represented.
        quotes = _chain_quotes(deribit, cur, spot, max_days=max_days, limit=60)
        result = iv_term_structure(spot=spot, quotes=quotes)
        response.headers["Cache-Control"] = f"public, max-age={_CRYPTO_TTL}"
        return {
            "currency": cur,
            "settlement": settlement,
            **asdict(result),
            "disclaimer": _DISCLAIMER,
        }

    @router.get(
        "/crypto/{currency}/vol-skew",
        summary="Call-side vol skew (IV + vega by strike) for writing",
    )
    def crypto_vol_skew(
        response: Response,
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        target_days: int = Query(
            30, ge=1, le=1095, description="Target tenor (nearest expiry used)"
        ),
    ) -> dict[str, Any]:
        """Call-side IV + vega across strikes at the expiry nearest ``target_days``."""
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        quotes, expiry = _skew_chain(deribit, cur, spot, target_days=target_days, limit=40)
        if not quotes or expiry is None:
            raise HTTPException(status_code=502, detail=f"No call chain available for '{cur}'")
        result = vol_skew(spot=spot, expiry_days=expiry, settlement=settlement, quotes=quotes)
        response.headers["Cache-Control"] = f"public, max-age={_CRYPTO_TTL}"
        return {"currency": cur, **asdict(result), "disclaimer": _DISCLAIMER}

    @router.get(
        "/crypto/{currency}/regime-overwrite",
        summary="Regime-conditioned covered-call strike (EMF live regime)",
    )
    def crypto_regime_overwrite(
        response: Response,
        currency: str = Path(description="BTC, ETH, SOL, XRP, TRX, or AVAX"),
        max_days: int = Query(60, ge=1, le=1095, description="Chain window"),
        base_target_delta: float = Query(0.25, gt=0, lt=1, description="Neutral target delta"),
        defensiveness: float = Query(
            1.0,
            ge=0,
            le=5,
            description="Risk knob: scales the regime tilt (0=neutral, 1=default, >1=amplified)",
        ),
        coins: float = Query(1.0, gt=0, description="Coins overwritten"),
    ) -> dict[str, Any]:
        """Pick a covered-call strike whose delta is tilted by the LIVE EMF regime."""
        if regime_engine is None:
            raise HTTPException(status_code=503, detail="Regime engine not configured")
        cur, spot, settlement = _crypto_spot_settlement(deribit, currency)
        regime = to_generic_regime(regime_engine.classify().regime)
        quotes = _chain_quotes(deribit, cur, spot, max_days=max_days, limit=_CHAIN_LIMIT)
        result = regime_conditioned_overwrite(
            regime=regime,
            spot=spot,
            settlement=settlement,
            quotes=quotes,
            base_target_delta=base_target_delta,
            defensiveness=defensiveness,
            coins=coins,
        )
        response.headers["Cache-Control"] = f"public, max-age={_CRYPTO_TTL}"
        return {"currency": cur, "settlement": settlement, "spot": spot, **asdict(result)}

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
