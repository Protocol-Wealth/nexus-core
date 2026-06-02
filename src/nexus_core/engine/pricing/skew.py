# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Call-side volatility skew — vega + IV by strike at one expiry.

Where the term structure answers *which expiry* to write, the skew answers
*which strike*: how implied vol varies across the call wing at a single tenor.
For a covered-call writer the headline is the **25-delta call skew** —
``IV(25Δ call) − IV(ATM)``: positive means the OTM calls a writer sells carry
*richer* vol than ATM (favorable — you harvest extra premium for the upside you
cap), negative means the OTM wing is cheap and writing close to the money pays
more per unit of cap given up. The **richest strike** flags the single OTM call
with the highest IV, and per-strike **vega** shows the vol exposure being shorted.

Pure + clock-free: the caller supplies a set of call quotes at (approximately)
one expiry; vega is Black-Scholes (per vol point, per coin). For **inverse**
(coin-settled) books vega is a USD-space BS approximation — directional, not an
exact coin-settlement sensitivity — flagged in a note. Educational illustration
over public market data, not advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nexus_core.engine.pricing.black_scholes import greeks
from nexus_core.engine.pricing.crypto_overlays import Settlement
from nexus_core.engine.pricing.option_chain import ChainQuote, select_by_delta

_DAYS_PER_YEAR = 365.0


@dataclass(frozen=True)
class SkewPoint:
    """One strike on the call-side vol skew.

    Attributes:
        strike: Strike price in USD.
        moneyness_pct: ``(strike / spot - 1) * 100`` — how far OTM (>0) the call sits.
        delta: Observed call delta, if available.
        mark_iv: Mark implied volatility in percent (Deribit convention), if any.
        vega: Black-Scholes vega, per vol point, per coin (USD-space; ``None`` when
            IV/expiry are unavailable). For a writer this is the vol risk shorted.
    """

    strike: float
    moneyness_pct: float
    delta: float | None
    mark_iv: float | None
    vega: float | None


@dataclass
class VolSkew:
    """Call-side IV + vega across strikes at one expiry, framed for a writer."""

    spot: float
    expiry_days: int
    settlement: Settlement
    atm_strike: float
    atm_iv: float | None
    call_25d_strike: float | None
    call_25d_iv: float | None
    skew_25d_pts: float | None  # IV(25Δ call) − IV(ATM); >0 = OTM calls richer
    richest_strike: float | None  # OTM call with the highest mark IV
    richest_iv: float | None
    points: list[SkewPoint] = field(default_factory=list)  # sorted by strike
    notes: list[str] = field(default_factory=list)


def vol_skew(
    *,
    spot: float,
    expiry_days: int,
    settlement: Settlement,
    quotes: list[ChainQuote],
    rate: float = 0.0,
) -> VolSkew:
    """Build the call-side vol skew (IV + vega by strike) for one expiry.

    Args:
        spot: Coin price in USD.
        expiry_days: Calendar days to the expiry these quotes belong to.
        settlement: ``"inverse"`` or ``"linear"`` (affects the vega note only).
        quotes: Call quotes at this expiry (``mark_iv`` drives IV/vega; ``delta``
            drives the 25Δ pick when present).
        rate: Continuously-compounded annual USD rate for the BS vega.

    Returns:
        A :class:`VolSkew` with per-strike points and the writer-facing summary:
        ATM IV, the 25Δ call IV, the 25Δ call skew (IV points), and the richest
        OTM call strike. Raises ``ValueError`` on a bad settlement / no calls.
    """
    if settlement not in ("inverse", "linear"):
        raise ValueError("settlement must be 'inverse' or 'linear'")
    calls = [q for q in quotes if q.kind == "call"]
    if not calls:
        raise ValueError("at least one call quote is required")

    t = max(expiry_days, 0) / _DAYS_PER_YEAR
    points: list[SkewPoint] = []
    for q in sorted(calls, key=lambda c: c.strike):
        vega: float | None = None
        if q.mark_iv is not None and t > 0 and spot > 0 and q.strike > 0:
            vega = round(greeks(spot, q.strike, t, rate, q.mark_iv / 100.0, "call").vega, 4)
        points.append(
            SkewPoint(
                strike=q.strike,
                moneyness_pct=round((q.strike / spot - 1.0) * 100.0, 2) if spot > 0 else 0.0,
                delta=q.delta,
                mark_iv=q.mark_iv,
                vega=vega,
            )
        )

    atm = min(calls, key=lambda c: abs(c.strike - spot))
    pick_25d = select_by_delta(quotes=calls, target_delta=0.25, kind="call")
    call_25d_iv = pick_25d.mark_iv if pick_25d is not None else None
    skew_25d = (
        round(call_25d_iv - atm.mark_iv, 2)
        if (call_25d_iv is not None and atm.mark_iv is not None)
        else None
    )

    otm_priced = [q for q in calls if q.strike > spot and q.mark_iv is not None]
    richest = max(otm_priced, key=lambda q: q.mark_iv) if otm_priced else None  # type: ignore[arg-type,return-value]

    notes: list[str] = []
    if skew_25d is not None:
        notes.append(
            f"25Δ call skew {skew_25d:+.2f} IV pts — "
            + (
                "OTM calls richer than ATM (favorable for OTM overwriting)."
                if skew_25d > 0
                else "OTM calls cheaper than ATM (near-the-money pays more per cap given up)."
            )
        )
    if settlement == "inverse":
        notes.append("Inverse (coin-settled): vega is a USD-space BS approximation — directional.")

    return VolSkew(
        spot=spot,
        expiry_days=expiry_days,
        settlement=settlement,
        atm_strike=atm.strike,
        atm_iv=atm.mark_iv,
        call_25d_strike=pick_25d.strike if pick_25d is not None else None,
        call_25d_iv=call_25d_iv,
        skew_25d_pts=skew_25d,
        richest_strike=richest.strike if richest is not None else None,
        richest_iv=richest.mark_iv if richest is not None else None,
        points=points,
        notes=notes,
    )


__all__ = ["SkewPoint", "VolSkew", "vol_skew"]
