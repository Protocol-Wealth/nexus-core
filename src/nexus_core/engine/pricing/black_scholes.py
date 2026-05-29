# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Black-Scholes-Merton option pricing, Greeks, and implied volatility.

A clean-room implementation of the standard textbook Black-Scholes-Merton
equations for European options on a single underlying with a continuous
dividend yield. Built directly from the well-known closed-form formulas using
:func:`scipy.stats.norm`; no third-party pricing code is reproduced here.

Everything in this module is an **educational illustration** of option-pricing
mathematics over PUBLIC market parameters (spot, strike, expiry, vol, rate). It
is not investment advice, a recommendation, or a suitability determination.

Conventions:
    * ``t_years`` is calendar time to expiry in years (e.g. 30 days ≈ 30/365).
    * ``rate`` and ``dividend_yield`` are continuously-compounded annual rates
      expressed as decimals (0.05 == 5%).
    * ``sigma`` is annualized volatility expressed as a decimal (0.25 == 25%).
    * :attr:`Greeks.theta` is reported **per calendar day** (annual theta / 365).
    * :attr:`Greeks.vega` is reported **per one volatility point** (annual
      vega / 100 — the price change for a +1% absolute move in ``sigma``).
    * :attr:`Greeks.rho` is reported **per one rate point** (annual rho / 100 —
      the price change for a +1% absolute move in ``rate``).

Best-effort by design: functions clamp degenerate inputs to the option's
(discounted) intrinsic value rather than raising. :func:`implied_vol` returns
``None`` when no volatility reproduces the supplied price.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from scipy.stats import norm

#: Side of a European option. ``"call"`` confers the right to buy at the
#: strike; ``"put"`` the right to sell.
OptionKind = Literal["call", "put"]

#: Days per year used to convert annualized theta into a per-day figure.
_DAYS_PER_YEAR = 365.0

#: Newton-Raphson controls for :func:`implied_vol`.
_IV_MAX_ITER = 100
_IV_PRICE_TOL = 1e-8
_IV_VEGA_FLOOR = 1e-12

#: Bisection bracket for the implied-vol fallback (0.01% .. 1000% vol).
_IV_SIGMA_LO = 1e-4
_IV_SIGMA_HI = 10.0
_IV_BISECT_MAX_ITER = 200


def _intrinsic(spot: float, strike: float, kind: OptionKind) -> float:
    """Undiscounted intrinsic value, floored at zero."""
    if kind == "call":
        return max(spot - strike, 0.0)
    return max(strike - spot, 0.0)


def _discounted_intrinsic(
    spot: float,
    strike: float,
    t_years: float,
    rate: float,
    kind: OptionKind,
    dividend_yield: float,
) -> float:
    """Intrinsic value with forward-consistent discounting.

    Used as the degenerate-input fallback so a ``t<=0`` or ``sigma<=0`` price is
    internally consistent with the no-arbitrage forward (spot grown at
    ``rate - dividend_yield`` then discounted back at ``rate``). Reduces to the
    plain intrinsic value when ``t_years <= 0``.
    """
    if t_years <= 0.0:
        return _intrinsic(spot, strike, kind)
    fwd = spot * math.exp((rate - dividend_yield) * t_years)
    disc = math.exp(-rate * t_years)
    if kind == "call":
        return max(fwd - strike, 0.0) * disc
    return max(strike - fwd, 0.0) * disc


def _d1_d2(
    spot: float,
    strike: float,
    t_years: float,
    rate: float,
    sigma: float,
    dividend_yield: float,
) -> tuple[float, float]:
    """Black-Scholes ``d1`` and ``d2`` terms.

    Callers must guarantee ``spot > 0``, ``strike > 0``, ``t_years > 0`` and
    ``sigma > 0`` before calling.
    """
    vol_sqrt_t = sigma * math.sqrt(t_years)
    d1 = (
        math.log(spot / strike) + (rate - dividend_yield + 0.5 * sigma * sigma) * t_years
    ) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    return d1, d2


def bs_price(
    spot: float,
    strike: float,
    t_years: float,
    rate: float,
    sigma: float,
    kind: OptionKind,
    *,
    dividend_yield: float = 0.0,
) -> float:
    """Black-Scholes-Merton price of a European option.

    Args:
        spot: Current underlying price (> 0).
        strike: Strike price (> 0).
        t_years: Time to expiry in years.
        rate: Continuously-compounded risk-free rate (decimal).
        sigma: Annualized volatility (decimal).
        kind: ``"call"`` or ``"put"``.
        dividend_yield: Continuous dividend yield (decimal).

    Returns:
        Theoretical option price. Degenerate inputs (non-positive spot/strike,
        ``t_years <= 0`` or ``sigma <= 0``) fall back to the (discounted)
        intrinsic value rather than raising.
    """
    if spot <= 0.0 or strike <= 0.0:
        return _intrinsic(max(spot, 0.0), max(strike, 0.0), kind)
    if t_years <= 0.0 or sigma <= 0.0:
        return _discounted_intrinsic(spot, strike, t_years, rate, kind, dividend_yield)

    d1, d2 = _d1_d2(spot, strike, t_years, rate, sigma, dividend_yield)
    disc_r = math.exp(-rate * t_years)
    disc_q = math.exp(-dividend_yield * t_years)
    if kind == "call":
        return spot * disc_q * float(norm.cdf(d1)) - strike * disc_r * float(norm.cdf(d2))
    return strike * disc_r * float(norm.cdf(-d2)) - spot * disc_q * float(norm.cdf(-d1))


@dataclass
class Greeks:
    """First-order option sensitivities (the "Greeks").

    Attributes:
        delta: ∂price/∂spot. In ``[0, 1]`` for calls, ``[-1, 0]`` for puts.
        gamma: ∂²price/∂spot² (identical for calls and puts), per $1 of spot.
        theta: ∂price/∂time, expressed **per calendar day** (annual theta / 365).
            Typically negative for long options (time decay).
        vega: ∂price/∂sigma, expressed **per one volatility point** (annual
            vega / 100 — price change for a +1% absolute move in ``sigma``).
        rho: ∂price/∂rate, expressed **per one rate point** (annual rho / 100 —
            price change for a +1% absolute move in ``rate``).
    """

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


def greeks(
    spot: float,
    strike: float,
    t_years: float,
    rate: float,
    sigma: float,
    kind: OptionKind,
    *,
    dividend_yield: float = 0.0,
) -> Greeks:
    """First-order Black-Scholes-Merton Greeks for a European option.

    See :class:`Greeks` for sign conventions and per-day / per-point scaling.

    Degenerate inputs (non-positive spot/strike, ``t_years <= 0`` or
    ``sigma <= 0``) return an all-zero :class:`Greeks` except for delta, which
    collapses to the intrinsic ±1/0 step so callers still get a sensible hedge
    ratio at expiry.
    """
    if spot <= 0.0 or strike <= 0.0 or t_years <= 0.0 or sigma <= 0.0:
        return _degenerate_greeks(spot, strike, kind)

    d1, d2 = _d1_d2(spot, strike, t_years, rate, sigma, dividend_yield)
    sqrt_t = math.sqrt(t_years)
    disc_r = math.exp(-rate * t_years)
    disc_q = math.exp(-dividend_yield * t_years)
    pdf_d1 = float(norm.pdf(d1))

    # Gamma and vega are kind-independent.
    gamma = disc_q * pdf_d1 / (spot * sigma * sqrt_t)
    vega_annual = spot * disc_q * pdf_d1 * sqrt_t
    common_theta = -(spot * disc_q * pdf_d1 * sigma) / (2.0 * sqrt_t)

    if kind == "call":
        delta = disc_q * float(norm.cdf(d1))
        theta_annual = (
            common_theta
            - rate * strike * disc_r * float(norm.cdf(d2))
            + dividend_yield * spot * disc_q * float(norm.cdf(d1))
        )
        rho_annual = strike * t_years * disc_r * float(norm.cdf(d2))
    else:
        delta = -disc_q * float(norm.cdf(-d1))
        theta_annual = (
            common_theta
            + rate * strike * disc_r * float(norm.cdf(-d2))
            - dividend_yield * spot * disc_q * float(norm.cdf(-d1))
        )
        rho_annual = -strike * t_years * disc_r * float(norm.cdf(-d2))

    return Greeks(
        delta=delta,
        gamma=gamma,
        theta=theta_annual / _DAYS_PER_YEAR,
        vega=vega_annual / 100.0,
        rho=rho_annual / 100.0,
    )


def _degenerate_greeks(spot: float, strike: float, kind: OptionKind) -> Greeks:
    """Greeks at/after expiry or with zero vol: an intrinsic delta step."""
    delta = float(spot > strike) if kind == "call" else -float(spot < strike)
    return Greeks(delta=delta, gamma=0.0, theta=0.0, vega=0.0, rho=0.0)


def implied_vol(
    price: float,
    spot: float,
    strike: float,
    t_years: float,
    rate: float,
    kind: OptionKind,
    *,
    dividend_yield: float = 0.0,
) -> float | None:
    """Implied volatility that reproduces ``price`` under Black-Scholes-Merton.

    Solves ``bs_price(..., sigma) == price`` for ``sigma`` using Newton-Raphson
    seeded by a Brenner-Subrahmanyam ATM guess, falling back to a robust
    bisection when Newton stalls (e.g. very low vega deep ITM/OTM).

    Args:
        price: Observed option price to invert.
        spot: Current underlying price (> 0).
        strike: Strike price (> 0).
        t_years: Time to expiry in years (> 0).
        rate: Continuously-compounded risk-free rate (decimal).
        kind: ``"call"`` or ``"put"``.
        dividend_yield: Continuous dividend yield (decimal).

    Returns:
        The implied volatility as a decimal, or ``None`` if inputs are
        degenerate (non-positive spot/strike/time/price), the target price
        violates no-arbitrage bounds, or neither solver converges.
    """
    if spot <= 0.0 or strike <= 0.0 or t_years <= 0.0 or price <= 0.0:
        return None

    # No-arbitrage bounds: the price must sit between the discounted intrinsic
    # value and the discounted underlying (call) / strike (put). Outside that
    # band no real implied volatility exists.
    disc_r = math.exp(-rate * t_years)
    disc_q = math.exp(-dividend_yield * t_years)
    lower = _discounted_intrinsic(spot, strike, t_years, rate, kind, dividend_yield)
    upper = spot * disc_q if kind == "call" else strike * disc_r
    if price < lower - _IV_PRICE_TOL or price > upper + _IV_PRICE_TOL:
        return None

    # Newton-Raphson from a Brenner-Subrahmanyam style ATM seed.
    sigma = max(math.sqrt(2.0 * math.pi / t_years) * (price / spot), _IV_SIGMA_LO)
    for _ in range(_IV_MAX_ITER):
        model = bs_price(spot, strike, t_years, rate, sigma, kind, dividend_yield=dividend_yield)
        diff = model - price
        if abs(diff) < _IV_PRICE_TOL:
            return sigma
        # Annual vega = (per-point vega) * 100.
        vega_annual = (
            greeks(spot, strike, t_years, rate, sigma, kind, dividend_yield=dividend_yield).vega
            * 100.0
        )
        if vega_annual < _IV_VEGA_FLOOR:
            break
        sigma -= diff / vega_annual
        if sigma <= 0.0 or sigma > _IV_SIGMA_HI:
            break

    return _implied_vol_bisect(price, spot, strike, t_years, rate, kind, dividend_yield)


def _implied_vol_bisect(
    price: float,
    spot: float,
    strike: float,
    t_years: float,
    rate: float,
    kind: OptionKind,
    dividend_yield: float,
) -> float | None:
    """Bisection fallback for :func:`implied_vol`.

    Price is monotonically increasing in ``sigma``, so a sign change between the
    bracket endpoints guarantees a root we can bisect to.
    """
    lo, hi = _IV_SIGMA_LO, _IV_SIGMA_HI

    def diff(sig: float) -> float:
        return (
            bs_price(spot, strike, t_years, rate, sig, kind, dividend_yield=dividend_yield) - price
        )

    d_lo = diff(lo)
    d_hi = diff(hi)
    if d_lo > 0.0 or d_hi < 0.0:
        # Target price not bracketed within [lo, hi] -> no convergence.
        return None

    mid = 0.5 * (lo + hi)
    for _ in range(_IV_BISECT_MAX_ITER):
        mid = 0.5 * (lo + hi)
        d_mid = diff(mid)
        if abs(d_mid) < _IV_PRICE_TOL:
            return mid
        if d_mid < 0.0:
            lo = mid
        else:
            hi = mid

    # Accept the final bracket midpoint if the bracket has tightened enough.
    if hi - lo < 1e-6:
        return mid
    return None


__all__ = [
    "Greeks",
    "OptionKind",
    "bs_price",
    "greeks",
    "implied_vol",
]

