# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Overwriting-program analytics — calendar ladder + roll economics.

Two operational helpers a systematic covered-call *program* needs beyond a
single illustration:

* :func:`covered_call_ladder` — an *ensemble* of short calls written across
  several expirations (calendar laddering) and/or strikes against one coin
  treasury. Reports coverage, blended yield, and the per-leg breakdown so the
  whole overwrite can be seen at once.
* :func:`roll_analysis` — the economics of *rolling* an existing short call:
  buy-to-close the current leg, sell-to-open a new strike/expiry, and read off
  the net credit, the realized P&L on the closed leg, and how the cap/cushion
  move (roll up / down / out).

Both delegate per-leg yield math to
:func:`nexus_core.engine.pricing.crypto_overlays.crypto_covered_call`, so they
stay consistent with the single-name overlay and the chain ranking. Pure and
clock-free; educational illustration over public parameters, not advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nexus_core.engine.pricing.crypto_overlays import (
    DISCLAIMER,
    CryptoCoveredCallIllustration,
    Settlement,
    crypto_covered_call,
)

_DAYS_PER_YEAR = 365.0


def _premium_usd(premium: float, spot: float, settlement: Settlement) -> float:
    """Bridge a native-unit premium to USD per coin (inverse: coin × spot)."""
    return premium * spot if settlement == "inverse" else premium


def _premium_coin(premium_usd: float, spot: float, settlement: Settlement) -> float | None:
    """Coin-denominated premium for the inverse case, else ``None``."""
    if settlement != "inverse" or spot <= 0.0:
        return None
    return premium_usd / spot


# ───────────────────────────── Ladder ─────────────────────────────


@dataclass(frozen=True)
class LadderLeg:
    """One leg of a covered-call ladder.

    Attributes:
        expiry_days: Calendar days to this leg's expiry.
        strike: Strike of the short call.
        coins: Coins overwritten by this leg.
        premium: Observed premium in the settlement's native unit (coin/USD).
            When ``None`` the leg is priced theoretically from ``iv``.
        iv: Annualized IV (decimal) for the theoretical path.
        delta: Observed call delta, if available.
    """

    expiry_days: int
    strike: float
    coins: float
    premium: float | None = None
    iv: float | None = None
    delta: float | None = None


@dataclass
class CoveredCallLadder:
    """Aggregate + per-leg view of a multi-expiry covered-call overwrite."""

    settlement: Settlement
    spot: float
    total_coins: float
    overwritten_coins: float
    coverage_pct: float  # overwritten / total_coins
    total_premium_usd: float
    total_coin_income: float | None  # inverse only
    blended_annualized_yield_pct: float  # coins-weighted over the overwrite
    weighted_distance_to_strike_pct: float  # coins-weighted
    nearest_expiry_days: int | None
    farthest_expiry_days: int | None
    legs: list[dict[str, Any]] = field(default_factory=list)
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def covered_call_ladder(
    *,
    spot: float,
    settlement: Settlement,
    total_coins: float,
    legs: list[LadderLeg],
    rate: float = 0.0,
) -> CoveredCallLadder:
    """Aggregate a calendar/strike ladder of covered calls on one treasury.

    Args:
        spot: Coin price in USD.
        settlement: ``"inverse"`` or ``"linear"``.
        total_coins: Total coins held (the denominator for coverage).
        legs: The short-call legs of the ladder.
        rate: Continuously-compounded annual USD rate for theoretical legs.

    Returns:
        A :class:`CoveredCallLadder` with coverage, blended annualized yield
        (coins-weighted), coins-weighted distance-to-strike, and per-leg rows.
    """
    if settlement not in ("inverse", "linear"):
        raise ValueError("settlement must be 'inverse' or 'linear'")
    if total_coins <= 0.0:
        raise ValueError("total_coins must be positive")
    if not legs:
        raise ValueError("at least one ladder leg is required")

    rows: list[dict[str, Any]] = []
    overwritten = 0.0
    total_premium_usd = 0.0
    total_coin_income = 0.0
    yield_weighted = 0.0  # Σ coins·annualized_yield
    dist_weighted = 0.0  # Σ coins·distance_to_strike
    expiries: list[int] = []

    for leg in legs:
        cc = crypto_covered_call(
            spot=spot,
            strike=leg.strike,
            expiry_days=leg.expiry_days,
            settlement=settlement,
            coins=leg.coins,
            premium=leg.premium,
            iv=leg.iv,
            rate=rate,
            delta=leg.delta,
        )
        overwritten += leg.coins
        total_premium_usd += cc.usd_income
        if cc.coin_income is not None:
            total_coin_income += cc.coin_income
        yield_weighted += leg.coins * cc.annualized_yield_pct
        dist_weighted += leg.coins * cc.distance_to_strike_pct
        expiries.append(leg.expiry_days)
        rows.append(
            {
                "expiry_days": leg.expiry_days,
                "strike": leg.strike,
                "coins": leg.coins,
                "premium_usd": round(cc.premium_usd, 2),
                "premium_coin": cc.premium_coin,
                "usd_income": round(cc.usd_income, 2),
                "annualized_yield_pct": round(cc.annualized_yield_pct, 2),
                "distance_to_strike_pct": round(cc.distance_to_strike_pct, 2),
                "delta": cc.delta,
                "prob_otm_approx": cc.prob_otm_approx,
            }
        )

    coverage_pct = overwritten / total_coins * 100.0
    blended_yield = yield_weighted / overwritten if overwritten > 0 else 0.0
    weighted_dist = dist_weighted / overwritten if overwritten > 0 else 0.0

    notes: list[str] = []
    if overwritten > total_coins + 1e-9:
        notes.append(
            f"Overwritten coins ({overwritten:g}) exceed the treasury "
            f"({total_coins:g}) — the ladder is over-written (uncovered short calls)."
        )
    if settlement == "inverse":
        notes.append(
            "Inverse (coin-settled): premium accrues in coin; blended yield grows "
            "the treasury when calls expire OTM."
        )

    return CoveredCallLadder(
        settlement=settlement,
        spot=spot,
        total_coins=total_coins,
        overwritten_coins=overwritten,
        coverage_pct=coverage_pct,
        total_premium_usd=total_premium_usd,
        total_coin_income=total_coin_income if settlement == "inverse" else None,
        blended_annualized_yield_pct=blended_yield,
        weighted_distance_to_strike_pct=weighted_dist,
        nearest_expiry_days=min(expiries) if expiries else None,
        farthest_expiry_days=max(expiries) if expiries else None,
        legs=rows,
        notes=notes,
    )


# ───────────────────────────── Roll ─────────────────────────────


@dataclass
class RollAnalysis:
    """Economics of rolling one short call to a new strike/expiry."""

    settlement: Settlement
    spot: float
    coins: float
    roll_type: str  # e.g. "roll up and out", "roll out", "roll down"
    close_cost_usd: float  # buy-to-close the current leg
    realized_pnl_usd: float  # entry credit minus close cost, on the closed leg
    open_credit_usd: float  # sell-to-open the new leg
    net_credit_usd: float  # open credit minus close cost (>0 = net credit)
    net_credit_coin: float | None  # inverse only
    new_call: CryptoCoveredCallIllustration
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def roll_analysis(
    *,
    spot: float,
    settlement: Settlement,
    coins: float,
    current_strike: float,
    current_expiry_days: int,
    current_entry_premium: float,
    current_close_premium: float,
    new_strike: float,
    new_expiry_days: int,
    new_open_premium: float,
    rate: float = 0.0,
    new_delta: float | None = None,
) -> RollAnalysis:
    """Roll a short call: buy-to-close the current leg, sell-to-open a new one.

    Premiums are in the settlement's native unit (coin for inverse, USD for
    linear). ``current_entry_premium`` is what was originally collected;
    ``current_close_premium`` is the cost to buy it back now.

    Returns:
        A :class:`RollAnalysis` with the net credit (USD + coin), realized P&L on
        the closed leg, a ``roll_type`` label, and the new short call illustrated
        via :func:`crypto_covered_call`.
    """
    if settlement not in ("inverse", "linear"):
        raise ValueError("settlement must be 'inverse' or 'linear'")
    if spot <= 0.0 or coins <= 0.0:
        raise ValueError("spot and coins must be positive")

    close_cost = _premium_usd(max(current_close_premium, 0.0), spot, settlement) * coins
    entry_credit = _premium_usd(max(current_entry_premium, 0.0), spot, settlement) * coins
    open_credit = _premium_usd(max(new_open_premium, 0.0), spot, settlement) * coins
    realized_pnl = entry_credit - close_cost
    net_credit = open_credit - close_cost
    net_credit_coin = _premium_coin(net_credit / coins, spot, settlement) if coins > 0 else None

    # Classify the roll. Strike: up/down/same; expiry: out/in/same.
    if new_strike > current_strike:
        strike_word = "up"
    elif new_strike < current_strike:
        strike_word = "down"
    else:
        strike_word = ""
    if new_expiry_days > current_expiry_days:
        time_word = "out"
    elif new_expiry_days < current_expiry_days:
        time_word = "in"
    else:
        time_word = ""
    parts = [w for w in (strike_word, time_word) if w]
    roll_type = "roll " + " and ".join(parts) if parts else "roll (same strike & expiry)"

    new_call = crypto_covered_call(
        spot=spot,
        strike=new_strike,
        expiry_days=new_expiry_days,
        settlement=settlement,
        coins=coins,
        premium=new_open_premium,
        rate=rate,
        delta=new_delta,
    )

    notes: list[str] = []
    if net_credit < 0:
        notes.append("Net debit roll — the new credit does not cover the buy-to-close cost.")
    if settlement == "inverse":
        notes.append(
            "Inverse (coin-settled): credits/costs are coin amounts, shown in USD at spot."
        )

    return RollAnalysis(
        settlement=settlement,
        spot=spot,
        coins=coins,
        roll_type=roll_type,
        close_cost_usd=close_cost,
        realized_pnl_usd=realized_pnl,
        open_credit_usd=open_credit,
        net_credit_usd=net_credit,
        net_credit_coin=net_credit_coin,
        new_call=new_call,
        notes=notes,
    )


__all__ = [
    "CoveredCallLadder",
    "LadderLeg",
    "RollAnalysis",
    "covered_call_ladder",
    "roll_analysis",
]
