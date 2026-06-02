# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Options-book mark-to-market + scenario stress.

Risk views over an *open* multi-leg options book (e.g. a ladder of short calls
plus protective long puts) held against a coin treasury:

* :func:`book_mtm` — mark each leg to its current value, aggregate the net
  premium P&L and the net Greeks (delta/gamma/theta/vega), and fold in the
  underlying coin delta so the program can read its net directional exposure.
* :func:`scenario_stress` — reprice the whole book across a grid of spot shocks
  (±%) and IV shocks (vol-point shifts), adding the underlying coin P&L, and
  flag which short calls go in-the-money (assignment risk).

Greeks and repricing use the Black-Scholes engine. For **inverse** (coin-settled)
books these are an educational USD-space approximation — inverse options carry
extra coin-denominated convexity not captured by vanilla BS — so treat the
inverse figures as directional, not exact; a note says so. Pure and clock-free;
illustration over public parameters, not advice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nexus_core.engine.pricing.black_scholes import bs_price, greeks
from nexus_core.engine.pricing.crypto_overlays import DISCLAIMER, Settlement

_DAYS_PER_YEAR = 365.0
_DEFAULT_SIGMA = 0.65


def _premium_usd(premium: float, spot: float, settlement: Settlement) -> float:
    return premium * spot if settlement == "inverse" else premium


def _t_years(expiry_days: int) -> float:
    return max(expiry_days, 0) / _DAYS_PER_YEAR


@dataclass(frozen=True)
class BookPosition:
    """One leg of an options book.

    Attributes:
        kind: ``"call"`` or ``"put"``.
        side: ``"short"`` (written) or ``"long"`` (bought).
        strike: Strike price in USD.
        expiry_days: Calendar days to expiry.
        coins: Coins (contracts) the leg covers.
        entry_premium: Premium collected/paid at inception, native unit.
        iv: Annualized IV (decimal) used for marking + Greeks.
        mark_premium: Current premium (native unit). When ``None`` the leg is
            marked to Black-Scholes at ``spot`` and ``iv``.
        label: Optional human label for the row.
    """

    kind: str
    side: str
    strike: float
    expiry_days: int
    coins: float
    entry_premium: float
    iv: float | None = None
    mark_premium: float | None = None
    label: str | None = None


@dataclass
class BookMtm:
    """Mark-to-market + aggregate Greeks for an options book."""

    settlement: Settlement
    spot: float
    coins_held: float
    total_pnl_usd: float  # premium P&L across all legs since inception
    net_option_delta: float  # Σ signed option deltas (coin units)
    net_delta_with_underlying: float  # net_option_delta + coins_held
    net_gamma: float
    net_theta_usd_day: float  # Σ signed theta, USD/day
    net_vega_usd_per_vol_pt: float  # Σ signed vega, USD per vol point
    positions: list[dict[str, Any]] = field(default_factory=list)
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def _sign(side: str) -> float:
    return -1.0 if side == "short" else 1.0


def book_mtm(
    *,
    spot: float,
    settlement: Settlement,
    positions: list[BookPosition],
    coins_held: float = 0.0,
    rate: float = 0.0,
) -> BookMtm:
    """Mark a book to market and aggregate its Greeks.

    Args:
        spot: Coin price in USD.
        settlement: ``"inverse"`` or ``"linear"`` (units of each premium).
        positions: The open legs.
        coins_held: Coins held outright (delta +1 each), folded into net delta.
        rate: Continuously-compounded annual USD rate for BS marks/Greeks.

    Returns:
        A :class:`BookMtm` with per-leg rows and book-level P&L + net Greeks.
    """
    if settlement not in ("inverse", "linear"):
        raise ValueError("settlement must be 'inverse' or 'linear'")

    rows: list[dict[str, Any]] = []
    total_pnl = 0.0
    net_delta = net_gamma = net_theta = net_vega = 0.0
    has_inverse_note = settlement == "inverse"

    for p in positions:
        sign = _sign(p.side)
        used_iv = p.iv if p.iv is not None and p.iv > 0 else _DEFAULT_SIGMA
        t = _t_years(p.expiry_days)
        model_usd = bs_price(spot, p.strike, t, rate, used_iv, p.kind)  # type: ignore[arg-type]
        mark_usd = (
            _premium_usd(p.mark_premium, spot, settlement)
            if p.mark_premium is not None
            else model_usd
        )
        entry_usd = _premium_usd(p.entry_premium, spot, settlement)
        pnl = sign * (mark_usd - entry_usd) * p.coins

        g = greeks(spot, p.strike, t, rate, used_iv, p.kind)  # type: ignore[arg-type]
        pos_delta = sign * p.coins * g.delta
        pos_gamma = sign * p.coins * g.gamma
        pos_theta = sign * p.coins * g.theta
        pos_vega = sign * p.coins * g.vega

        total_pnl += pnl
        net_delta += pos_delta
        net_gamma += pos_gamma
        net_theta += pos_theta
        net_vega += pos_vega

        rows.append(
            {
                "label": p.label,
                "kind": p.kind,
                "side": p.side,
                "strike": p.strike,
                "expiry_days": p.expiry_days,
                "coins": p.coins,
                "mark_usd": round(mark_usd, 2),
                "entry_usd": round(entry_usd, 2),
                "pnl_usd": round(pnl, 2),
                "delta": round(pos_delta, 4),
                "gamma": round(pos_gamma, 6),
                "theta_usd_day": round(pos_theta, 2),
                "vega_usd_per_vol_pt": round(pos_vega, 2),
            }
        )

    notes: list[str] = []
    if has_inverse_note:
        notes.append(
            "Inverse (coin-settled): Greeks are a USD-space Black-Scholes "
            "approximation and omit inverse-payoff convexity — directional, not exact."
        )

    return BookMtm(
        settlement=settlement,
        spot=spot,
        coins_held=coins_held,
        total_pnl_usd=total_pnl,
        net_option_delta=net_delta,
        net_delta_with_underlying=net_delta + coins_held,
        net_gamma=net_gamma,
        net_theta_usd_day=net_theta,
        net_vega_usd_per_vol_pt=net_vega,
        positions=rows,
        notes=notes,
    )


@dataclass
class ScenarioCell:
    """Book outcome at one (spot shock, IV shock) grid point."""

    spot_shock_pct: float  # e.g. -20.0 for a 20% drop
    iv_shock_pts: float  # absolute vol-point shift, e.g. +10.0
    spot: float  # shocked spot
    option_pnl_usd: float  # MTM change of the options legs
    underlying_pnl_usd: float  # MTM change of the held coins
    total_pnl_usd: float
    short_calls_itm: int  # count of short calls in-the-money (assignment risk)


@dataclass
class ScenarioResult:
    """Spot/IV stress grid over an options book + the held coins."""

    settlement: Settlement
    spot: float
    coins_held: float
    cells: list[ScenarioCell] = field(default_factory=list)
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def scenario_stress(
    *,
    spot: float,
    settlement: Settlement,
    positions: list[BookPosition],
    spot_shocks: list[float],
    iv_shocks: list[float] | None = None,
    coins_held: float = 0.0,
    rate: float = 0.0,
) -> ScenarioResult:
    """Reprice the book across a grid of spot shocks × IV shocks.

    Args:
        spot: Current coin price in USD.
        settlement: ``"inverse"`` or ``"linear"``.
        positions: The open legs (each leg's ``iv`` is the base IV that gets shocked).
        spot_shocks: Fractional spot moves, e.g. ``[-0.3, -0.15, 0, 0.15, 0.3]``.
        iv_shocks: Absolute vol-point shifts as decimals, e.g. ``[-0.1, 0, 0.1]``
            (a +0.1 shift adds 10 vol points). Defaults to ``[0.0]`` (no IV shock).
        coins_held: Coins held outright (their P&L is added to each cell).
        rate: Continuously-compounded annual USD rate for BS repricing.

    Returns:
        A :class:`ScenarioResult` — one :class:`ScenarioCell` per (spot, IV) point,
        with the options P&L, the underlying coin P&L, the total, and the count of
        short calls that go in-the-money (assignment risk) at that spot.
    """
    if settlement not in ("inverse", "linear"):
        raise ValueError("settlement must be 'inverse' or 'linear'")
    if spot <= 0.0:
        raise ValueError("spot must be positive")
    iv_shifts = iv_shocks if iv_shocks else [0.0]

    # Baseline value per leg at the current spot + base IV.
    baselines: list[float] = []
    for p in positions:
        used_iv = p.iv if p.iv is not None and p.iv > 0 else _DEFAULT_SIGMA
        baselines.append(bs_price(spot, p.strike, _t_years(p.expiry_days), rate, used_iv, p.kind))  # type: ignore[arg-type]

    cells: list[ScenarioCell] = []
    for s_shock in spot_shocks:
        shocked_spot = spot * (1.0 + s_shock)
        for iv_shift in iv_shifts:
            option_pnl = 0.0
            short_itm = 0
            for p, base in zip(positions, baselines, strict=True):
                used_iv = p.iv if p.iv is not None and p.iv > 0 else _DEFAULT_SIGMA
                scn_iv = max(used_iv + iv_shift, 0.0)
                scn_val = bs_price(
                    shocked_spot,
                    p.strike,
                    _t_years(p.expiry_days),
                    rate,
                    scn_iv,
                    p.kind,  # type: ignore[arg-type]
                )
                option_pnl += _sign(p.side) * (scn_val - base) * p.coins
                if p.side == "short" and p.kind == "call" and shocked_spot > p.strike:
                    short_itm += 1
            underlying_pnl = coins_held * (shocked_spot - spot)
            cells.append(
                ScenarioCell(
                    spot_shock_pct=round(s_shock * 100.0, 2),
                    iv_shock_pts=round(iv_shift * 100.0, 2),
                    spot=round(shocked_spot, 2),
                    option_pnl_usd=round(option_pnl, 2),
                    underlying_pnl_usd=round(underlying_pnl, 2),
                    total_pnl_usd=round(option_pnl + underlying_pnl, 2),
                    short_calls_itm=short_itm,
                )
            )

    notes: list[str] = []
    if settlement == "inverse":
        notes.append(
            "Inverse (coin-settled): repricing is a USD-space Black-Scholes "
            "approximation — directional, not an exact settlement P&L."
        )

    return ScenarioResult(
        settlement=settlement,
        spot=spot,
        coins_held=coins_held,
        cells=cells,
        notes=notes,
    )


__all__ = [
    "BookMtm",
    "BookPosition",
    "ScenarioCell",
    "ScenarioResult",
    "book_mtm",
    "scenario_stress",
]
