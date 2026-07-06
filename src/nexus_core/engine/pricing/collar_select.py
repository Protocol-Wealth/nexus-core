# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Batch equity collar screening — dividend-aware theoretical strike selection.

Given a set of equity/ETF positions (symbol, spot, volatility, tenor, dividend
yield), this module picks a protective-put strike a fixed percentage below spot
and a short-call strike targeting a Black-Scholes delta (subject to a
minimum-OTM floor), prices both legs THEORETICALLY via
:func:`nexus_core.engine.pricing.black_scholes.bs_price` with the position's
``dividend_yield`` threaded through (the single-name overlays in
:mod:`nexus_core.engine.pricing.overlays` price without it), and reports each
collar's floor/cap geometry and income arithmetic. All dollar figures are
per share.

Strike grid: strikes snap to an approximate US-listed-equity increment grid
chosen by the underlying's price band (< $25: $0.50, < $200: $1, < $500: $5,
else $10). Real chains vary by name and venue — the grid is an illustration
convention, **an approximation**, not exchange data. The call strike snaps UP
to the grid so the minimum-OTM floor always holds after snapping.

Everything here is an EDUCATIONAL ILLUSTRATION over public market parameters —
not individualized advice, a recommendation to trade, or a suitability
assessment. Premiums are theoretical Black-Scholes values (``theoretical=True``
on every result), not market quotes. Degenerate inputs yield zeroed metrics
rather than raising, and the module is clock-free (callers supply
``expiry_days``).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from nexus_core.engine.pricing.black_scholes import bs_price, greeks
from nexus_core.engine.pricing.overlays import DISCLAIMER

#: Calendar days per year for annualization and year-fraction conversion.
_DAYS_PER_YEAR = 365.0

#: Bisection controls for the call-strike-by-delta solve.
_DELTA_TOL = 1e-6
_DELTA_BISECT_MAX_ITER = 200

#: Bracket bounds for the strike solve, as multiples of spot.
_STRIKE_BRACKET_LO = 1e-3
_STRIKE_BRACKET_HI = 1e3


@dataclass(frozen=True)
class CollarScreenPosition:
    """One equity/ETF position submitted to the collar screen.

    Attributes:
        symbol: Public ticker (labelling only — no data is fetched here).
        spot: Current share price.
        sigma: Annualized volatility as a decimal (0.25 == 25%).
        expiry_days: Calendar days to the collar's expiry.
        dividend_yield: Annualized continuous dividend yield as a decimal
            fraction (0.02 == 2%). Threaded into the Black-Scholes pricing of
            both legs and credited as window income.
    """

    symbol: str
    spot: float
    sigma: float
    expiry_days: int
    dividend_yield: float = 0.0


@dataclass
class CollarScreenResult:
    """Theoretical collar evaluation for one screened position.

    Percentage fields are on the share price; dollar fields are per share.
    ``prob_*_otm_approx`` uses the repo's ``(1 - |delta|) * 100`` convention —
    an illustrative approximation, not a forecast.
    """

    symbol: str
    spot: float
    sigma: float
    expiry_days: int
    dividend_yield: float
    put_strike: float  # protective long put, snapped to the strike grid
    call_strike: float  # financing short call, snapped UP to the grid
    put_premium: float  # theoretical Black-Scholes value (dividend-aware)
    call_premium: float  # theoretical Black-Scholes value (dividend-aware)
    put_delta: float
    call_delta: float
    net_credit: float  # call premium received minus put premium paid (+ credit)
    breakeven: float  # spot - net_credit (a debit raises breakeven)
    max_profit: float  # per share, capped at the call strike
    max_loss: float  # per share, floored by the put strike
    floor_pct: float  # distance from spot down to the put floor, % of spot
    cap_pct: float  # distance from spot up to the call cap, % of spot
    downside_protection_pct: float  # alias of floor_pct (CollarIllustration vocab)
    static_return_pct: float  # net_credit / spot — option income over the window
    annualized_return_pct: float  # static_return_pct annualized over expiry_days
    dividend_income: float  # per-share dividends over the window (pro-rata approx)
    dividend_income_pct: float  # dividend_income / spot over the window
    total_annualized_income_pct: float  # annualized option income + dividend yield
    prob_put_otm_approx: float | None  # approx P(put expires OTM), 1-|delta|
    prob_call_otm_approx: float | None  # approx P(call expires OTM), 1-|delta|
    theoretical: bool = True  # premiums are Black-Scholes values, never quotes
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER


def _strike_increment(price: float) -> float:
    """Approximate US-listed strike increment for the underlying's price band.

    < $25: $0.50 — < $200: $1 — < $500: $5 — else $10. An illustration
    convention (real chains vary by name/venue), documented as an approximation.
    """
    if price < 25.0:
        return 0.5
    if price < 200.0:
        return 1.0
    if price < 500.0:
        return 5.0
    return 10.0


def _snap_nearest(value: float, increment: float) -> float:
    """Snap ``value`` to the nearest grid point, floored at one increment."""
    return max(round(value / increment) * increment, increment)


def _snap_up(value: float, increment: float) -> float:
    """Snap ``value`` UP to the grid (exact multiples stay put), floored at one increment."""
    return max(math.ceil(value / increment - 1e-9) * increment, increment)


def _solve_call_strike_for_delta(
    spot: float,
    t_years: float,
    rate: float,
    sigma: float,
    dividend_yield: float,
    target_delta: float,
) -> float | None:
    """Strike at which the Black-Scholes call delta equals ``target_delta``.

    Call delta is monotonically decreasing in strike, so bisection over a
    bracket that spans the target converges. Returns ``None`` when the target
    is unattainable (e.g. above the dividend-discounted maximum ``e^{-qT}`` or
    not bracketed within ``spot × [1e-3, 1e3]``).
    """

    def call_delta(strike: float) -> float:
        return greeks(
            spot, strike, t_years, rate, sigma, "call", dividend_yield=dividend_yield
        ).delta

    lo = spot * _STRIKE_BRACKET_LO
    if call_delta(lo) < target_delta:
        return None  # target above the deliverable maximum (≈ e^{-qT})
    hi = spot
    while call_delta(hi) > target_delta:
        hi *= 2.0
        if hi > spot * _STRIKE_BRACKET_HI:
            return None
    for _ in range(_DELTA_BISECT_MAX_ITER):
        mid = 0.5 * (lo + hi)
        d_mid = call_delta(mid)
        if abs(d_mid - target_delta) < _DELTA_TOL:
            return mid
        if d_mid > target_delta:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _prob_otm(delta: float) -> float:
    """Approximate P(expires OTM) as ``(1 - |delta|) * 100`` (repo convention)."""
    return round((1.0 - abs(delta)) * 100.0, 1)


def _zeroed(position: CollarScreenPosition, warning: str) -> CollarScreenResult:
    """All-zero metrics for a degenerate position (never raises)."""
    return CollarScreenResult(
        symbol=position.symbol,
        spot=position.spot,
        sigma=position.sigma,
        expiry_days=position.expiry_days,
        dividend_yield=position.dividend_yield,
        put_strike=0.0,
        call_strike=0.0,
        put_premium=0.0,
        call_premium=0.0,
        put_delta=0.0,
        call_delta=0.0,
        net_credit=0.0,
        breakeven=0.0,
        max_profit=0.0,
        max_loss=0.0,
        floor_pct=0.0,
        cap_pct=0.0,
        downside_protection_pct=0.0,
        static_return_pct=0.0,
        annualized_return_pct=0.0,
        dividend_income=0.0,
        dividend_income_pct=0.0,
        total_annualized_income_pct=0.0,
        prob_put_otm_approx=None,
        prob_call_otm_approx=None,
        warnings=[warning],
    )


def evaluate_collar_position(
    position: CollarScreenPosition,
    *,
    put_otm_pct: float = 15.0,
    call_min_otm_pct: float = 1.0,
    target_call_delta: float = 0.30,
    risk_free_rate: float = 0.04,
) -> CollarScreenResult:
    """Evaluate one theoretical collar on a screened position.

    Strike selection:
        * ``put_strike`` = ``spot × (1 - put_otm_pct/100)`` snapped to the
          nearest grid point.
        * ``call_strike`` = the strike whose Black-Scholes call delta equals
          ``target_call_delta`` (bisection), floored at
          ``spot × (1 + call_min_otm_pct/100)``, then snapped UP to the grid so
          the minimum-OTM floor always holds.

    Both legs are priced THEORETICALLY with the position's ``dividend_yield``
    threaded through :func:`bs_price`. ``dividend_income`` is the simple
    pro-rata approximation ``spot × dividend_yield × expiry_days / 365``
    (ignores discrete ex-dividend dates and compounding), and
    ``total_annualized_income_pct`` adds the full annual dividend yield to the
    annualized option income.

    Args:
        position: The position to evaluate.
        put_otm_pct: How far below spot the protective put sits, in percent.
        call_min_otm_pct: Minimum call-strike distance above spot, in percent.
        target_call_delta: Target Black-Scholes delta for the short call.
        risk_free_rate: Continuously-compounded annual risk-free rate (decimal).

    Returns:
        A :class:`CollarScreenResult`. Degenerate inputs (``spot <= 0``,
        ``sigma <= 0`` or ``expiry_days <= 0``) yield zeroed metrics plus a
        warning rather than raising.
    """
    spot, sigma, days = position.spot, position.sigma, position.expiry_days
    q = position.dividend_yield
    if spot <= 0.0 or sigma <= 0.0 or days <= 0:
        return _zeroed(position, "Non-positive parameter supplied — metrics zeroed.")

    t_years = days / _DAYS_PER_YEAR
    increment = _strike_increment(spot)
    warnings: list[str] = []

    put_strike = _snap_nearest(spot * (1.0 - put_otm_pct / 100.0), increment)

    solved = _solve_call_strike_for_delta(spot, t_years, risk_free_rate, sigma, q, target_call_delta)
    call_floor = spot * (1.0 + call_min_otm_pct / 100.0)
    if solved is None or solved < call_floor:
        warnings.append(
            "Call strike floored at the minimum-OTM constraint — the delta target "
            "would sit closer to spot."
        )
    call_strike = _snap_up(max(solved, call_floor) if solved is not None else call_floor, increment)

    put_premium = bs_price(spot, put_strike, t_years, risk_free_rate, sigma, "put", dividend_yield=q)
    call_premium = bs_price(
        spot, call_strike, t_years, risk_free_rate, sigma, "call", dividend_yield=q
    )
    put_delta = greeks(spot, put_strike, t_years, risk_free_rate, sigma, "put", dividend_yield=q).delta
    call_delta = greeks(
        spot, call_strike, t_years, risk_free_rate, sigma, "call", dividend_yield=q
    ).delta

    net_credit = call_premium - put_premium
    if net_credit < 0.0:
        warnings.append(
            "Net debit — the protective put costs more than the call premium received."
        )

    static_return_pct = net_credit / spot * 100.0
    annualized_return_pct = static_return_pct * (_DAYS_PER_YEAR / days)
    dividend_income = spot * q * (days / _DAYS_PER_YEAR)
    dividend_income_pct = q * (days / _DAYS_PER_YEAR) * 100.0
    floor_pct = (spot - put_strike) / spot * 100.0

    return CollarScreenResult(
        symbol=position.symbol,
        spot=spot,
        sigma=sigma,
        expiry_days=days,
        dividend_yield=q,
        put_strike=put_strike,
        call_strike=call_strike,
        put_premium=put_premium,
        call_premium=call_premium,
        put_delta=put_delta,
        call_delta=call_delta,
        net_credit=net_credit,
        breakeven=spot - net_credit,
        max_profit=(call_strike - spot) + net_credit,
        max_loss=(spot - put_strike) - net_credit,
        floor_pct=floor_pct,
        cap_pct=(call_strike - spot) / spot * 100.0,
        downside_protection_pct=floor_pct,
        static_return_pct=static_return_pct,
        annualized_return_pct=annualized_return_pct,
        dividend_income=dividend_income,
        dividend_income_pct=dividend_income_pct,
        total_annualized_income_pct=annualized_return_pct + q * 100.0,
        prob_put_otm_approx=_prob_otm(put_delta),
        prob_call_otm_approx=_prob_otm(call_delta),
        warnings=warnings,
    )


def screen_collars(
    positions: Sequence[CollarScreenPosition],
    *,
    put_otm_pct: float = 15.0,
    call_min_otm_pct: float = 1.0,
    target_call_delta: float = 0.30,
    risk_free_rate: float = 0.04,
) -> list[CollarScreenResult]:
    """Evaluate and rank theoretical collars across a batch of positions.

    Ranking heuristic (documented on purpose — it is a screening convention,
    not an optimum): net-credit structures (``net_credit >= 0``) rank ahead of
    net-debit ones, and within each group results sort by
    ``total_annualized_income_pct`` descending. Rationale: a collar that
    finances its own protection is conventionally preferred over one that pays
    for protection, even when the debit structure shows a nominally higher
    total income figure. Degenerate (zeroed) positions carry zero income and
    sink accordingly within the net-credit group.

    Args:
        positions: Positions to evaluate (order does not matter).
        put_otm_pct: See :func:`evaluate_collar_position`.
        call_min_otm_pct: See :func:`evaluate_collar_position`.
        target_call_delta: See :func:`evaluate_collar_position`.
        risk_free_rate: See :func:`evaluate_collar_position`.

    Returns:
        Ranked :class:`CollarScreenResult` list, best-scoring first.
    """
    results = [
        evaluate_collar_position(
            p,
            put_otm_pct=put_otm_pct,
            call_min_otm_pct=call_min_otm_pct,
            target_call_delta=target_call_delta,
            risk_free_rate=risk_free_rate,
        )
        for p in positions
    ]
    results.sort(key=lambda r: (0 if r.net_credit >= 0.0 else 1, -r.total_annualized_income_pct))
    return results


__all__ = [
    "CollarScreenPosition",
    "CollarScreenResult",
    "evaluate_collar_position",
    "screen_collars",
]
