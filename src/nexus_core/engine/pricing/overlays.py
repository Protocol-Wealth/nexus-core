# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Educational option-overlay illustrators for stocks and ETFs.

This module computes the static payoff arithmetic of three common option
*structures* layered on a stock/ETF position:

    * ``covered_call_overlay`` — long shares + short call.
    * ``cash_secured_put_overlay`` — short put fully collateralised by cash.
    * ``collar_overlay`` — long shares + protective long put + short call.

Everything here is an EDUCATIONAL ILLUSTRATION of how a structure's payoff,
breakeven, max gain/loss and approximate probabilities behave for a given set
of PUBLIC market parameters (spot, strike, expiry, vol, rate). It is *not*
individualized advice, a recommendation to trade, or a suitability assessment.
There are no "buy/sell" verbs, no position-sizing-for-a-person logic, and no
account/holdings inputs — only public structure parameters.

When a premium is not supplied, a THEORETICAL premium is computed from the
:mod:`nexus_core.engine.pricing.black_scholes` engine using a default annual
volatility, so an illustration can still be rendered. Supplying an observed
premium overrides the theoretical value.

All functions are best-effort: degenerate inputs yield zeroed metrics rather
than raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nexus_core.disclaimers import TERSE
from nexus_core.engine.pricing.black_scholes import bs_price, greeks

#: Educational-framing string attached to every illustration. Sourced from the
#: canonical :data:`nexus_core.disclaimers.TERSE` — never hand-written, so a
#: Marketing-Rule change to ``TERSE`` propagates to every option-overlay surface.
DISCLAIMER = TERSE

#: Calendar days per year for annualization of static returns.
_DAYS_PER_YEAR = 365.0

#: Fallback annual volatility used when neither a premium nor a sigma is given.
_DEFAULT_SIGMA = 0.30

#: Shares represented by one standard equity option contract.
_SHARES_PER_CONTRACT = 100


def _safe_pct(numerator: float, denominator: float) -> float:
    """Percentage ``numerator / denominator * 100``; ``0.0`` if denominator <= 0."""
    if denominator <= 0.0:
        return 0.0
    return numerator / denominator * 100.0


def _annualize_pct(period_pct: float, expiry_days: int) -> float:
    """Scale a period return percentage to an annualized figure (simple, no compounding)."""
    if expiry_days <= 0:
        return 0.0
    return period_pct * (_DAYS_PER_YEAR / expiry_days)


def _t_years(expiry_days: int) -> float:
    return max(expiry_days, 0) / _DAYS_PER_YEAR


def _theoretical_call_premium(
    spot: float, strike: float, expiry_days: int, rate: float, sigma: float
) -> float:
    return bs_price(spot, strike, _t_years(expiry_days), rate, sigma, "call")


def _theoretical_put_premium(
    spot: float, strike: float, expiry_days: int, rate: float, sigma: float
) -> float:
    return bs_price(spot, strike, _t_years(expiry_days), rate, sigma, "put")


def _call_delta(spot: float, strike: float, expiry_days: int, rate: float, sigma: float) -> float | None:
    if spot <= 0.0 or strike <= 0.0 or expiry_days <= 0 or sigma <= 0.0:
        return None
    return greeks(spot, strike, _t_years(expiry_days), rate, sigma, "call").delta


def _put_delta(spot: float, strike: float, expiry_days: int, rate: float, sigma: float) -> float | None:
    if spot <= 0.0 or strike <= 0.0 or expiry_days <= 0 or sigma <= 0.0:
        return None
    return greeks(spot, strike, _t_years(expiry_days), rate, sigma, "put").delta


def _prob_otm_from_delta(delta: float | None) -> float | None:
    """Approximate probability the option expires OTM, ``(1 - |delta|) * 100``.

    Risk-neutral delta is a rough proxy for assignment probability; the
    complement approximates the probability of expiring out-of-the-money. This
    is an illustrative approximation, not a forecast.
    """
    if delta is None:
        return None
    return round((1.0 - abs(delta)) * 100.0, 1)


# ─────────────────────────── Covered call ───────────────────────────


@dataclass
class CoveredCallIllustration:
    """Static-payoff illustration of a long-stock + short-call structure.

    All percentage fields are expressed on the share price (per-share basis).
    Dollar fields (``net_premium``, ``max_profit``, ``max_loss``) are scaled to
    the ``shares`` quantity supplied.
    """

    spot: float
    strike: float
    expiry_days: int
    premium: float
    shares: int
    theoretical: bool  # True when premium was derived from Black-Scholes
    net_premium: float  # credit (+) received for selling the call
    breakeven: float  # share price at which the combined structure is flat
    max_profit: float  # capped gain if shares are called away
    max_loss: float  # loss if the share price falls to zero (capital at risk)
    static_return_pct: float  # premium / spot — return if price is unchanged
    return_if_assigned_pct: float  # (strike - spot + premium) / spot
    annualized_return_pct: float  # static_return_pct annualized over expiry_days
    downside_protection_pct: float  # premium cushion as % of spot
    otm_pct: float  # how far OTM the short call strike sits, % of spot
    prob_otm_approx: float | None  # approx P(call expires OTM) from delta
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def covered_call_overlay(
    spot: float,
    strike: float,
    expiry_days: int,
    premium: float | None = None,
    *,
    rate: float = 0.04,
    sigma: float | None = None,
    shares: int = 100,
) -> CoveredCallIllustration:
    """Illustrate the payoff of a covered-call structure on public parameters.

    Args:
        spot: Current public share price of the underlying.
        strike: Strike of the short call (typically above spot).
        expiry_days: Calendar days to expiration.
        premium: Observed call premium per share. When ``None`` a theoretical
            premium is computed from Black-Scholes using ``sigma`` (or a default).
        rate: Continuously-compounded annual risk-free rate.
        sigma: Annual volatility for the theoretical-premium path. Defaults to
            an illustrative 30% when omitted.
        shares: Share count the structure is illustrated over (≥100, per contract).

    Returns:
        A :class:`CoveredCallIllustration`. Degenerate inputs yield zeroed metrics.
    """
    used_sigma = sigma if sigma is not None else _DEFAULT_SIGMA
    theoretical = premium is None
    if theoretical:
        prem = _theoretical_call_premium(spot, strike, expiry_days, rate, used_sigma)
    else:
        prem = float(premium)  # type: ignore[arg-type]

    if spot <= 0.0 or strike <= 0.0 or shares <= 0:
        return CoveredCallIllustration(
            spot=spot,
            strike=strike,
            expiry_days=expiry_days,
            premium=max(prem, 0.0),
            shares=shares,
            theoretical=theoretical,
            net_premium=0.0,
            breakeven=0.0,
            max_profit=0.0,
            max_loss=0.0,
            static_return_pct=0.0,
            return_if_assigned_pct=0.0,
            annualized_return_pct=0.0,
            downside_protection_pct=0.0,
            otm_pct=0.0,
            prob_otm_approx=None,
            notes=["Non-positive parameter supplied — metrics zeroed."],
        )

    prem = max(prem, 0.0)
    net_premium = prem * shares  # credit received
    breakeven = spot - prem  # downside breakeven on the long stock
    upside_per_share = max(strike - spot, 0.0)
    max_profit = (upside_per_share + prem) * shares  # capped at the strike
    max_loss = breakeven * shares  # if shares fall to zero

    static_return_pct = _safe_pct(prem, spot)
    return_if_assigned_pct = _safe_pct(upside_per_share + prem, spot)
    annualized_return_pct = _annualize_pct(static_return_pct, expiry_days)
    downside_protection_pct = _safe_pct(prem, spot)
    otm_pct = _safe_pct(strike - spot, spot)

    delta = _call_delta(spot, strike, expiry_days, rate, used_sigma)
    prob_otm = _prob_otm_from_delta(delta)

    notes: list[str] = []
    if theoretical:
        notes.append(
            f"Premium is theoretical (Black-Scholes, sigma={used_sigma:.0%}); "
            "supply an observed premium for a market-based illustration."
        )
    if strike <= spot:
        notes.append("Strike is at or below spot — this illustrates an in/at-the-money call.")

    return CoveredCallIllustration(
        spot=spot,
        strike=strike,
        expiry_days=expiry_days,
        premium=prem,
        shares=shares,
        theoretical=theoretical,
        net_premium=net_premium,
        breakeven=breakeven,
        max_profit=max_profit,
        max_loss=max_loss,
        static_return_pct=static_return_pct,
        return_if_assigned_pct=return_if_assigned_pct,
        annualized_return_pct=annualized_return_pct,
        downside_protection_pct=downside_protection_pct,
        otm_pct=otm_pct,
        prob_otm_approx=prob_otm,
        notes=notes,
    )


# ─────────────────────── Cash-secured put ───────────────────────


@dataclass
class CashSecuredPutIllustration:
    """Static-payoff illustration of a short-put structure backed by cash.

    Dollar fields are scaled to ``contracts * 100`` shares.
    """

    spot: float
    strike: float
    expiry_days: int
    premium: float
    contracts: int
    theoretical: bool
    net_premium: float  # credit (+) received for selling the put
    breakeven: float  # strike - premium (effective entry if assigned)
    cash_secured: float  # collateral set aside (strike * 100 * contracts)
    max_profit: float  # premium kept if the put expires OTM
    max_loss: float  # if the underlying falls to zero
    static_return_pct: float  # premium / strike — yield on secured cash
    return_if_assigned_pct: float  # premium / breakeven (cost-basis view)
    annualized_return_pct: float
    otm_pct: float  # how far OTM the short put strike sits
    prob_otm_approx: float | None
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def cash_secured_put_overlay(
    spot: float,
    strike: float,
    expiry_days: int,
    premium: float | None = None,
    *,
    rate: float = 0.04,
    sigma: float | None = None,
    contracts: int = 1,
) -> CashSecuredPutIllustration:
    """Illustrate the payoff of a cash-secured-put structure on public parameters.

    Args:
        spot: Current public share price of the underlying.
        strike: Strike of the short put (typically below spot).
        expiry_days: Calendar days to expiration.
        premium: Observed put premium per share. When ``None`` a theoretical
            premium is computed from Black-Scholes.
        rate: Continuously-compounded annual risk-free rate.
        sigma: Annual volatility for the theoretical path (default illustrative 30%).
        contracts: Number of put contracts (each covers 100 shares).

    Returns:
        A :class:`CashSecuredPutIllustration`. Degenerate inputs yield zeroed metrics.
    """
    used_sigma = sigma if sigma is not None else _DEFAULT_SIGMA
    theoretical = premium is None
    if theoretical:
        prem = _theoretical_put_premium(spot, strike, expiry_days, rate, used_sigma)
    else:
        prem = float(premium)  # type: ignore[arg-type]

    shares = contracts * _SHARES_PER_CONTRACT
    if spot <= 0.0 or strike <= 0.0 or contracts <= 0:
        return CashSecuredPutIllustration(
            spot=spot,
            strike=strike,
            expiry_days=expiry_days,
            premium=max(prem, 0.0),
            contracts=contracts,
            theoretical=theoretical,
            net_premium=0.0,
            breakeven=0.0,
            cash_secured=0.0,
            max_profit=0.0,
            max_loss=0.0,
            static_return_pct=0.0,
            return_if_assigned_pct=0.0,
            annualized_return_pct=0.0,
            otm_pct=0.0,
            prob_otm_approx=None,
            notes=["Non-positive parameter supplied — metrics zeroed."],
        )

    prem = max(prem, 0.0)
    net_premium = prem * shares  # credit received
    breakeven = strike - prem  # effective entry price if assigned
    cash_secured = strike * shares  # collateral fully securing the put
    max_profit = prem * shares  # premium kept if put expires OTM
    max_loss = breakeven * shares  # if underlying goes to zero

    static_return_pct = _safe_pct(prem, strike)
    return_if_assigned_pct = _safe_pct(prem, breakeven)
    annualized_return_pct = _annualize_pct(static_return_pct, expiry_days)
    otm_pct = _safe_pct(spot - strike, spot)

    delta = _put_delta(spot, strike, expiry_days, rate, used_sigma)
    prob_otm = _prob_otm_from_delta(delta)

    notes: list[str] = []
    if theoretical:
        notes.append(
            f"Premium is theoretical (Black-Scholes, sigma={used_sigma:.0%}); "
            "supply an observed premium for a market-based illustration."
        )
    if strike >= spot:
        notes.append("Strike is at or above spot — this illustrates an in/at-the-money put.")

    return CashSecuredPutIllustration(
        spot=spot,
        strike=strike,
        expiry_days=expiry_days,
        premium=prem,
        contracts=contracts,
        theoretical=theoretical,
        net_premium=net_premium,
        breakeven=breakeven,
        cash_secured=cash_secured,
        max_profit=max_profit,
        max_loss=max_loss,
        static_return_pct=static_return_pct,
        return_if_assigned_pct=return_if_assigned_pct,
        annualized_return_pct=annualized_return_pct,
        otm_pct=otm_pct,
        prob_otm_approx=prob_otm,
        notes=notes,
    )


# ───────────────────────────── Collar ─────────────────────────────


@dataclass
class CollarIllustration:
    """Static-payoff illustration of a long-stock + long-put + short-call collar.

    The short call partially or fully finances the protective put. ``net_premium``
    is positive for a net credit, negative for a net debit.
    """

    spot: float
    put_strike: float
    call_strike: float
    expiry_days: int
    put_premium: float
    call_premium: float
    shares: int
    theoretical: bool
    net_premium: float  # call credit minus put debit, scaled to shares
    breakeven: float  # spot + net per-share cost (debit raises breakeven)
    max_profit: float  # capped at the call strike
    max_loss: float  # floored by the put strike
    static_return_pct: float  # net premium per share / spot
    return_if_assigned_pct: float  # (call_strike - spot + net) / spot
    annualized_return_pct: float
    downside_protection_pct: float  # distance from spot down to the put floor
    otm_pct: float  # how far OTM the short call sits
    prob_otm_approx: float | None  # approx P(short call expires OTM)
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def collar_overlay(
    spot: float,
    put_strike: float,
    call_strike: float,
    expiry_days: int,
    put_premium: float | None = None,
    call_premium: float | None = None,
    *,
    rate: float = 0.04,
    sigma: float | None = None,
    shares: int = 100,
) -> CollarIllustration:
    """Illustrate the payoff of a collar structure on public parameters.

    Args:
        spot: Current public share price of the underlying.
        put_strike: Strike of the protective long put (below spot).
        call_strike: Strike of the financing short call (above spot).
        expiry_days: Calendar days to expiration.
        put_premium: Observed put premium per share; theoretical when ``None``.
        call_premium: Observed call premium per share; theoretical when ``None``.
        rate: Continuously-compounded annual risk-free rate.
        sigma: Annual volatility for theoretical premiums (default illustrative 30%).
        shares: Share count the structure is illustrated over.

    Returns:
        A :class:`CollarIllustration`. Degenerate inputs yield zeroed metrics.
    """
    used_sigma = sigma if sigma is not None else _DEFAULT_SIGMA
    put_theo = put_premium is None
    call_theo = call_premium is None
    theoretical = put_theo or call_theo

    put_prem = (
        _theoretical_put_premium(spot, put_strike, expiry_days, rate, used_sigma)
        if put_theo
        else float(put_premium)  # type: ignore[arg-type]
    )
    call_prem = (
        _theoretical_call_premium(spot, call_strike, expiry_days, rate, used_sigma)
        if call_theo
        else float(call_premium)  # type: ignore[arg-type]
    )

    if spot <= 0.0 or put_strike <= 0.0 or call_strike <= 0.0 or shares <= 0:
        return CollarIllustration(
            spot=spot,
            put_strike=put_strike,
            call_strike=call_strike,
            expiry_days=expiry_days,
            put_premium=max(put_prem, 0.0),
            call_premium=max(call_prem, 0.0),
            shares=shares,
            theoretical=theoretical,
            net_premium=0.0,
            breakeven=0.0,
            max_profit=0.0,
            max_loss=0.0,
            static_return_pct=0.0,
            return_if_assigned_pct=0.0,
            annualized_return_pct=0.0,
            downside_protection_pct=0.0,
            otm_pct=0.0,
            prob_otm_approx=None,
            notes=["Non-positive parameter supplied — metrics zeroed."],
        )

    put_prem = max(put_prem, 0.0)
    call_prem = max(call_prem, 0.0)
    # Net per-share cash: receive call premium, pay put premium.
    net_per_share = call_prem - put_prem  # >0 credit, <0 debit
    net_premium = net_per_share * shares

    # A debit raises breakeven, a credit lowers it.
    breakeven = spot - net_per_share
    upside_per_share = max(call_strike - spot, 0.0)
    downside_per_share = max(spot - put_strike, 0.0)

    max_profit = (upside_per_share + net_per_share) * shares  # capped at call strike
    max_loss = (downside_per_share - net_per_share) * shares  # floored at put strike

    static_return_pct = _safe_pct(net_per_share, spot)
    return_if_assigned_pct = _safe_pct(upside_per_share + net_per_share, spot)
    annualized_return_pct = _annualize_pct(static_return_pct, expiry_days)
    downside_protection_pct = _safe_pct(spot - put_strike, spot)
    otm_pct = _safe_pct(call_strike - spot, spot)

    delta = _call_delta(spot, call_strike, expiry_days, rate, used_sigma)
    prob_otm = _prob_otm_from_delta(delta)

    notes: list[str] = []
    if theoretical:
        which = []
        if put_theo:
            which.append("put")
        if call_theo:
            which.append("call")
        notes.append(
            f"Theoretical {'/'.join(which)} premium (Black-Scholes, sigma={used_sigma:.0%}); "
            "supply observed premiums for a market-based illustration."
        )
    if put_strike >= call_strike:
        notes.append("Put strike is at or above the call strike — atypical collar geometry.")

    return CollarIllustration(
        spot=spot,
        put_strike=put_strike,
        call_strike=call_strike,
        expiry_days=expiry_days,
        put_premium=put_prem,
        call_premium=call_prem,
        shares=shares,
        theoretical=theoretical,
        net_premium=net_premium,
        breakeven=breakeven,
        max_profit=max_profit,
        max_loss=max_loss,
        static_return_pct=static_return_pct,
        return_if_assigned_pct=return_if_assigned_pct,
        annualized_return_pct=annualized_return_pct,
        downside_protection_pct=downside_protection_pct,
        otm_pct=otm_pct,
        prob_otm_approx=prob_otm,
        notes=notes,
    )


__all__ = [
    "DISCLAIMER",
    "CashSecuredPutIllustration",
    "CollarIllustration",
    "CoveredCallIllustration",
    "cash_secured_put_overlay",
    "collar_overlay",
    "covered_call_overlay",
]

