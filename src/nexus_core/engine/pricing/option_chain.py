# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Option-chain analytics — covered-call yield ranking + strike-by-delta.

Pure helpers that turn a set of listed option quotes into the two things an
overwriting program asks of a chain:

* **rank the OTM calls by annualized covered-call yield** (which strike/expiry
  pays best for the cushion it gives up), and
* **select a strike by target delta** (e.g. "write the 25-delta call").

The functions take plain quote records and a settlement model; the calling tool
is responsible for fetching the chain from Deribit and converting each
instrument's expiry timestamp into ``expiry_days`` (the engine stays pure and
clock-free). Yield math is delegated to
:func:`nexus_core.engine.pricing.crypto_overlays.crypto_covered_call`, so a chain
ranking and a single-name illustration can never disagree.

Educational illustration over public market data — not advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nexus_core.engine.pricing.crypto_overlays import Settlement, crypto_covered_call


@dataclass(frozen=True)
class ChainQuote:
    """One listed option quote, normalized for the chain helpers.

    Attributes:
        instrument_name: Exchange instrument name (e.g. ``BTC-27JUN26-120000-C``).
        kind: ``"call"`` or ``"put"``.
        strike: Strike price in USD.
        expiry_days: Calendar days to expiry (the tool derives this from the
            instrument's expiration timestamp).
        premium: Observed premium in the settlement's native unit — coin for
            inverse, USD for linear. ``None`` when not quoted.
        delta: Observed option delta, if available.
        mark_iv: Mark implied volatility in percent (Deribit convention), if any.
    """

    instrument_name: str
    kind: str
    strike: float
    expiry_days: int
    premium: float | None = None
    delta: float | None = None
    mark_iv: float | None = None


def rank_covered_calls(
    *,
    spot: float,
    settlement: Settlement,
    quotes: list[ChainQuote],
    coins: float = 1.0,
    otm_only: bool = True,
    top: int | None = None,
) -> list[dict[str, Any]]:
    """Rank OTM calls by annualized covered-call yield (richest first).

    Args:
        spot: Coin price in USD.
        settlement: ``"inverse"`` or ``"linear"`` (units of each quote's premium).
        quotes: Listed quotes; only calls with a positive premium are ranked.
        coins: Covered quantity (for the per-row income figures).
        otm_only: When ``True`` (default) only calls with ``strike > spot`` are
            ranked — covered-call writing is an OTM overwrite by construction.
        top: Optionally cap the result to the top-N by yield.

    Returns:
        A list of dicts (highest annualized yield first), each with the
        instrument, strike, expiry, premium (coin + USD), static + annualized
        yield, distance-to-strike, delta and approx P(OTM).
    """
    rows: list[dict[str, Any]] = []
    for q in quotes:
        if q.kind != "call" or q.premium is None or q.premium <= 0.0:
            continue
        if otm_only and q.strike <= spot:
            continue
        cc = crypto_covered_call(
            spot=spot,
            strike=q.strike,
            expiry_days=q.expiry_days,
            settlement=settlement,
            coins=coins,
            premium=q.premium,
            delta=q.delta,
        )
        rows.append(
            {
                "instrument_name": q.instrument_name,
                "strike": q.strike,
                "expiry_days": q.expiry_days,
                "premium_coin": cc.premium_coin,
                "premium_usd": round(cc.premium_usd, 2),
                "static_yield_pct": round(cc.static_yield_pct, 3),
                "annualized_yield_pct": round(cc.annualized_yield_pct, 2),
                "distance_to_strike_pct": round(cc.distance_to_strike_pct, 2),
                "delta": q.delta,
                "mark_iv": q.mark_iv,
                "prob_otm_approx": cc.prob_otm_approx,
            }
        )
    rows.sort(key=lambda r: r["annualized_yield_pct"], reverse=True)
    return rows[:top] if top is not None and top > 0 else rows


def select_by_delta(
    *,
    quotes: list[ChainQuote],
    target_delta: float,
    kind: str = "call",
) -> ChainQuote | None:
    """Return the quote whose ``|delta|`` is closest to ``target_delta``.

    Args:
        quotes: Listed quotes (those without a delta are ignored).
        target_delta: Target absolute delta, e.g. ``0.25`` for a 25-delta call.
        kind: ``"call"`` or ``"put"``.

    Returns:
        The nearest-delta :class:`ChainQuote`, or ``None`` when no quote of that
        kind carries a delta.
    """
    target = abs(target_delta)
    candidates = [q for q in quotes if q.kind == kind and q.delta is not None]
    if not candidates:
        return None
    return min(candidates, key=lambda q: abs(abs(q.delta) - target))  # type: ignore[arg-type]


__all__ = ["ChainQuote", "rank_covered_calls", "select_by_delta"]
