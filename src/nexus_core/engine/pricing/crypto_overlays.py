# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Crypto covered-call overlay — settlement-aware (inverse vs linear).

A covered-call *overwriting* illustration for a crypto treasury that holds the
coin and sells calls against it. The mechanics differ from equity options by
settlement model, which Deribit splits two ways:

* **inverse** (BTC, ETH) — coin-settled. The option premium is quoted and paid
  in the *coin* itself (Deribit ``mark_price`` is in coin units). Selling calls
  therefore literally *grows the coin stack*: the natural yield is denominated
  in coins, not dollars.
* **linear** (SOL, XRP, …) — USDC-settled. Premium is quoted and paid in USDC,
  so the overlay behaves like an equity covered call (USD premium per unit).

The two are unified here through a single ``premium_usd`` bridge (for inverse,
``premium_usd = premium_coin * spot``), so every percentage metric — static
yield, annualized yield, downside cushion, return-if-assigned — has one
definition across both models. The coin-native premium and coin income are
surfaced *additionally* for the inverse case, because "how many extra coins does
this earn per year" is the figure a coin-treasury overwriting program tracks.

Everything here is an EDUCATIONAL ILLUSTRATION over PUBLIC market parameters
(spot, strike, expiry, vol/premium). It is not advice, a recommendation to
trade, an execution instruction, or a suitability assessment — there are no
account, custody, or counterparty inputs. Booking against an ISDA/CSA, execution
(e.g. FalconX), and custody/collateral (e.g. Anchorage) are out of scope.

Degenerate inputs yield zeroed metrics rather than raising.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from nexus_core.engine.pricing.black_scholes import bs_price, greeks

#: Educational-framing string attached to every illustration.
DISCLAIMER = "Educational illustration only — not investment advice."

#: Settlement model of a listed crypto option. ``inverse`` = coin-settled
#: (BTC/ETH on Deribit); ``linear`` = USDC-settled (SOL/XRP/TRX/AVAX).
Settlement = Literal["inverse", "linear"]

_DAYS_PER_YEAR = 365.0

#: Fallback annual volatility when neither a premium nor an IV is supplied.
#: Higher than the equity default — crypto implied vols routinely sit well above.
_DEFAULT_SIGMA = 0.65


def _t_years(expiry_days: int) -> float:
    return max(expiry_days, 0) / _DAYS_PER_YEAR


def _safe_pct(numerator: float, denominator: float) -> float:
    if denominator <= 0.0:
        return 0.0
    return numerator / denominator * 100.0


def _annualize_pct(period_pct: float, expiry_days: int) -> float:
    if expiry_days <= 0:
        return 0.0
    return period_pct * (_DAYS_PER_YEAR / expiry_days)


def _prob_otm_from_delta(delta: float | None) -> float | None:
    """Approximate P(call expires OTM) ≈ ``(1 - |delta|) * 100`` — illustrative."""
    if delta is None:
        return None
    return round((1.0 - abs(delta)) * 100.0, 1)


@dataclass
class CryptoCoveredCallIllustration:
    """Settlement-aware static-payoff illustration of a crypto covered call.

    Percentage fields are defined on the coin's USD value (``premium_usd / spot``
    basis), identical across settlement models. ``premium_coin`` / ``coin_income``
    / ``coins_if_unassigned`` are populated only for inverse (coin-settled) books,
    where the premium is received in coin.
    """

    settlement: Settlement
    spot: float
    strike: float
    expiry_days: int
    coins: float
    theoretical: bool  # True when premium was derived from Black-Scholes
    premium_coin: float | None  # coin premium per coin (inverse only)
    premium_usd: float  # USD premium per coin (the cross-model bridge)
    coin_income: float | None  # coins earned across the position (inverse only)
    usd_income: float  # USD value of premium across the position
    coins_if_unassigned: float | None  # coins held if the call expires OTM (inverse)
    breakeven_usd: float  # coin USD price at which the structure is flat
    max_profit_usd: float  # capped gain if assigned, across the position
    max_loss_usd: float  # loss if the coin falls to zero (capital at risk)
    static_yield_pct: float  # premium_usd / spot — yield if spot is unchanged
    annualized_yield_pct: float  # static yield annualized over expiry_days
    return_if_assigned_pct: float  # (strike - spot + premium_usd) / spot
    downside_cushion_pct: float  # premium cushion as % of spot
    distance_to_strike_pct: float  # how far OTM the short call sits, % of spot
    delta: float | None  # call delta (observed if supplied, else Black-Scholes)
    prob_otm_approx: float | None  # approx P(call expires OTM) from delta
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def crypto_covered_call(
    *,
    spot: float,
    strike: float,
    expiry_days: int,
    settlement: Settlement,
    coins: float = 1.0,
    premium: float | None = None,
    iv: float | None = None,
    rate: float = 0.0,
    delta: float | None = None,
) -> CryptoCoveredCallIllustration:
    """Illustrate a covered call written against a crypto holding.

    Args:
        spot: Current coin price in USD (e.g. the Deribit index price).
        strike: Strike of the short call (typically above spot).
        expiry_days: Calendar days to expiration.
        settlement: ``"inverse"`` (coin-settled, BTC/ETH) or ``"linear"``
            (USDC-settled, SOL/XRP/…). Determines the unit of ``premium``.
        coins: Number of coins overwritten (the covered quantity).
        premium: Observed option premium in the settlement's native unit —
            coin for inverse (matches Deribit ``mark_price``), USD for linear.
            When ``None`` a theoretical premium is priced from ``iv``.
        iv: Annualized implied volatility (decimal, e.g. ``0.65``) used for the
            theoretical-premium path. Defaults to an illustrative 65%.
        rate: Continuously-compounded annual USD rate (default 0 — crypto is
            commonly illustrated with a flat carry).
        delta: Observed call delta (e.g. from a Deribit ticker). When ``None``
            it is computed from Black-Scholes.

    Returns:
        A :class:`CryptoCoveredCallIllustration`. Degenerate inputs zero metrics.
    """
    if settlement not in ("inverse", "linear"):
        raise ValueError("settlement must be 'inverse' or 'linear'")

    inverse = settlement == "inverse"
    used_sigma = iv if iv is not None and iv > 0 else _DEFAULT_SIGMA
    theoretical = premium is None

    # Resolve the USD premium per coin (the cross-model bridge), and the
    # coin-native premium for the inverse case.
    if theoretical:
        bs_usd = bs_price(spot, strike, _t_years(expiry_days), rate, used_sigma, "call")
        premium_usd = max(bs_usd, 0.0)
    else:
        prem = max(float(premium), 0.0)  # type: ignore[arg-type]
        premium_usd = prem * spot if inverse else prem
    premium_coin = (premium_usd / spot if spot > 0 else 0.0) if inverse else None

    if spot <= 0.0 or strike <= 0.0 or coins <= 0.0:
        return CryptoCoveredCallIllustration(
            settlement=settlement,
            spot=spot,
            strike=strike,
            expiry_days=expiry_days,
            coins=coins,
            theoretical=theoretical,
            premium_coin=premium_coin,
            premium_usd=premium_usd,
            coin_income=None,
            usd_income=0.0,
            coins_if_unassigned=None,
            breakeven_usd=0.0,
            max_profit_usd=0.0,
            max_loss_usd=0.0,
            static_yield_pct=0.0,
            annualized_yield_pct=0.0,
            return_if_assigned_pct=0.0,
            downside_cushion_pct=0.0,
            distance_to_strike_pct=0.0,
            delta=delta,
            prob_otm_approx=_prob_otm_from_delta(delta),
            notes=["Non-positive parameter supplied — metrics zeroed."],
        )

    upside_per_coin = max(strike - spot, 0.0)
    static_yield_pct = _safe_pct(premium_usd, spot)
    annualized_yield_pct = _annualize_pct(static_yield_pct, expiry_days)
    return_if_assigned_pct = _safe_pct(upside_per_coin + premium_usd, spot)
    downside_cushion_pct = static_yield_pct
    distance_to_strike_pct = _safe_pct(strike - spot, spot)
    breakeven_usd = spot - premium_usd

    usd_income = premium_usd * coins
    coin_income = premium_coin * coins if (inverse and premium_coin is not None) else None
    coins_if_unassigned = coins + coin_income if coin_income is not None else None
    max_profit_usd = (upside_per_coin + premium_usd) * coins
    max_loss_usd = breakeven_usd * coins  # coin → 0

    if delta is None and expiry_days > 0:
        delta = greeks(spot, strike, _t_years(expiry_days), rate, used_sigma, "call").delta
    prob_otm = _prob_otm_from_delta(delta)

    notes: list[str] = []
    if inverse:
        notes.append(
            "Inverse (coin-settled): premium is received in coin, so the "
            f"annualized yield (~{annualized_yield_pct:.1f}%) grows the coin "
            "treasury itself if the call expires OTM."
        )
    else:
        notes.append("Linear (USDC-settled): premium is received in USDC.")
    if theoretical:
        notes.append(
            f"Premium is theoretical (Black-Scholes, IV={used_sigma:.0%}); "
            "supply an observed premium (e.g. a Deribit mark) for a market view."
        )
    if strike <= spot:
        notes.append("Strike is at or below spot — illustrates an in/at-the-money call.")

    return CryptoCoveredCallIllustration(
        settlement=settlement,
        spot=spot,
        strike=strike,
        expiry_days=expiry_days,
        coins=coins,
        theoretical=theoretical,
        premium_coin=premium_coin,
        premium_usd=premium_usd,
        coin_income=coin_income,
        usd_income=usd_income,
        coins_if_unassigned=coins_if_unassigned,
        breakeven_usd=breakeven_usd,
        max_profit_usd=max_profit_usd,
        max_loss_usd=max_loss_usd,
        static_yield_pct=static_yield_pct,
        annualized_yield_pct=annualized_yield_pct,
        return_if_assigned_pct=return_if_assigned_pct,
        downside_cushion_pct=downside_cushion_pct,
        distance_to_strike_pct=distance_to_strike_pct,
        delta=delta,
        prob_otm_approx=prob_otm,
        notes=notes,
    )


@dataclass
class CryptoProtectivePutIllustration:
    """Settlement-aware illustration of a protective put on a crypto holding.

    Buying a put against coins held caps the downside at the put strike for the
    cost of the premium. Percentage fields are on the coin's USD value; the
    coin-native cost is surfaced for inverse (coin-settled) books.
    """

    settlement: Settlement
    spot: float
    strike: float
    expiry_days: int
    coins: float
    theoretical: bool
    premium_coin: float | None  # coin premium per coin (inverse only)
    premium_usd: float  # USD premium per coin (the cost of protection)
    cost_coin: float | None  # coins paid across the position (inverse only)
    cost_usd: float  # USD premium paid across the position
    floor_usd: float  # protected value per coin (≈ the put strike)
    protection_level_pct: float  # (spot - strike) / spot — drop before protection
    cost_pct: float  # premium_usd / spot — the drag of protection
    annualized_cost_pct: float
    breakeven_usd: float  # spot + premium_usd (recover the premium)
    max_loss_usd: float  # (spot - strike + premium_usd) × coins, floored at strike
    delta: float | None  # put delta (negative; observed or Black-Scholes)
    prob_itm_approx: float | None  # ≈ |delta| × 100 — P(protection pays)
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def crypto_protective_put(
    *,
    spot: float,
    strike: float,
    expiry_days: int,
    settlement: Settlement,
    coins: float = 1.0,
    premium: float | None = None,
    iv: float | None = None,
    rate: float = 0.0,
    delta: float | None = None,
) -> CryptoProtectivePutIllustration:
    """Illustrate a protective put bought against a crypto holding.

    Args mirror :func:`crypto_covered_call`; ``strike`` is the (typically OTM)
    put floor. ``premium`` is in the settlement's native unit. Returns a
    :class:`CryptoProtectivePutIllustration`; degenerate inputs zero the metrics.
    """
    if settlement not in ("inverse", "linear"):
        raise ValueError("settlement must be 'inverse' or 'linear'")

    inverse = settlement == "inverse"
    used_sigma = iv if iv is not None and iv > 0 else _DEFAULT_SIGMA
    theoretical = premium is None
    if theoretical:
        premium_usd = max(
            bs_price(spot, strike, _t_years(expiry_days), rate, used_sigma, "put"), 0.0
        )
    else:
        prem = max(float(premium), 0.0)  # type: ignore[arg-type]
        premium_usd = prem * spot if inverse else prem
    premium_coin = (premium_usd / spot if spot > 0 else 0.0) if inverse else None

    if spot <= 0.0 or strike <= 0.0 or coins <= 0.0:
        return CryptoProtectivePutIllustration(
            settlement=settlement,
            spot=spot,
            strike=strike,
            expiry_days=expiry_days,
            coins=coins,
            theoretical=theoretical,
            premium_coin=premium_coin,
            premium_usd=premium_usd,
            cost_coin=None,
            cost_usd=0.0,
            floor_usd=0.0,
            protection_level_pct=0.0,
            cost_pct=0.0,
            annualized_cost_pct=0.0,
            breakeven_usd=0.0,
            max_loss_usd=0.0,
            delta=delta,
            prob_itm_approx=(round(abs(delta) * 100.0, 1) if delta is not None else None),
            notes=["Non-positive parameter supplied — metrics zeroed."],
        )

    cost_pct = _safe_pct(premium_usd, spot)
    cost_coin = premium_coin * coins if (inverse and premium_coin is not None) else None
    if delta is None and expiry_days > 0:
        delta = greeks(spot, strike, _t_years(expiry_days), rate, used_sigma, "put").delta

    notes: list[str] = []
    if inverse:
        notes.append("Inverse (coin-settled): the put premium is paid in coin.")
    else:
        notes.append("Linear (USDC-settled): the put premium is paid in USDC.")
    if theoretical:
        notes.append(f"Premium is theoretical (Black-Scholes, IV={used_sigma:.0%}).")
    if strike >= spot:
        notes.append("Strike is at or above spot — illustrates an in/at-the-money put.")

    return CryptoProtectivePutIllustration(
        settlement=settlement,
        spot=spot,
        strike=strike,
        expiry_days=expiry_days,
        coins=coins,
        theoretical=theoretical,
        premium_coin=premium_coin,
        premium_usd=premium_usd,
        cost_coin=cost_coin,
        cost_usd=premium_usd * coins,
        floor_usd=strike,
        protection_level_pct=_safe_pct(spot - strike, spot),
        cost_pct=cost_pct,
        annualized_cost_pct=_annualize_pct(cost_pct, expiry_days),
        breakeven_usd=spot + premium_usd,
        max_loss_usd=(spot - strike + premium_usd) * coins,
        delta=delta,
        prob_itm_approx=(round(abs(delta) * 100.0, 1) if delta is not None else None),
        notes=notes,
    )


@dataclass
class CryptoCollarIllustration:
    """Settlement-aware collar: long coins + protective put + financing short call.

    ``net_premium_usd`` is the call credit minus the put debit (>0 net credit,
    <0 net debit). Percentage fields are on the coin's USD value.
    """

    settlement: Settlement
    spot: float
    put_strike: float
    call_strike: float
    expiry_days: int
    coins: float
    theoretical: bool
    put_premium_usd: float
    call_premium_usd: float
    net_premium_coin: float | None  # (call - put) in coin (inverse only)
    net_premium_usd: float  # call credit minus put debit, per coin
    breakeven_usd: float  # spot - net per coin (a debit raises it)
    max_profit_usd: float  # capped at the call strike, across the position
    max_loss_usd: float  # floored at the put strike, across the position
    upside_cap_pct: float  # (call_strike - spot) / spot
    downside_protection_pct: float  # (spot - put_strike) / spot
    net_yield_pct: float  # net_premium_usd / spot (can be negative)
    annualized_net_yield_pct: float
    call_delta: float | None
    prob_call_otm_approx: float | None
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def crypto_collar(
    *,
    spot: float,
    put_strike: float,
    call_strike: float,
    expiry_days: int,
    settlement: Settlement,
    coins: float = 1.0,
    put_premium: float | None = None,
    call_premium: float | None = None,
    iv: float | None = None,
    rate: float = 0.0,
    call_delta: float | None = None,
) -> CryptoCollarIllustration:
    """Illustrate a protective collar on a crypto holding (put floor + call cap).

    Premiums are in the settlement's native unit; either may be theoretical
    (priced from ``iv``). Returns a :class:`CryptoCollarIllustration`.
    """
    if settlement not in ("inverse", "linear"):
        raise ValueError("settlement must be 'inverse' or 'linear'")

    inverse = settlement == "inverse"
    used_sigma = iv if iv is not None and iv > 0 else _DEFAULT_SIGMA
    put_theo = put_premium is None
    call_theo = call_premium is None
    theoretical = put_theo or call_theo

    def _usd(prem: float) -> float:
        return prem * spot if inverse else prem

    put_usd = (
        max(bs_price(spot, put_strike, _t_years(expiry_days), rate, used_sigma, "put"), 0.0)
        if put_theo
        else _usd(max(float(put_premium), 0.0))  # type: ignore[arg-type]
    )
    call_usd = (
        max(bs_price(spot, call_strike, _t_years(expiry_days), rate, used_sigma, "call"), 0.0)
        if call_theo
        else _usd(max(float(call_premium), 0.0))  # type: ignore[arg-type]
    )

    if spot <= 0.0 or put_strike <= 0.0 or call_strike <= 0.0 or coins <= 0.0:
        return CryptoCollarIllustration(
            settlement=settlement,
            spot=spot,
            put_strike=put_strike,
            call_strike=call_strike,
            expiry_days=expiry_days,
            coins=coins,
            theoretical=theoretical,
            put_premium_usd=put_usd,
            call_premium_usd=call_usd,
            net_premium_coin=None,
            net_premium_usd=0.0,
            breakeven_usd=0.0,
            max_profit_usd=0.0,
            max_loss_usd=0.0,
            upside_cap_pct=0.0,
            downside_protection_pct=0.0,
            net_yield_pct=0.0,
            annualized_net_yield_pct=0.0,
            call_delta=call_delta,
            prob_call_otm_approx=None,
            notes=["Non-positive parameter supplied — metrics zeroed."],
        )

    net_per_coin = call_usd - put_usd  # >0 credit, <0 debit
    net_premium_coin = (net_per_coin / spot if spot > 0 else 0.0) if inverse else None
    upside_per_coin = max(call_strike - spot, 0.0)
    downside_per_coin = max(spot - put_strike, 0.0)
    net_yield_pct = _safe_pct(net_per_coin, spot)

    if call_delta is None and expiry_days > 0:
        call_delta = greeks(
            spot, call_strike, _t_years(expiry_days), rate, used_sigma, "call"
        ).delta

    notes: list[str] = []
    if inverse:
        notes.append("Inverse (coin-settled): premiums are coin amounts; net shown in USD at spot.")
    if theoretical:
        notes.append(f"Theoretical premium(s) (Black-Scholes, IV={used_sigma:.0%}).")
    if put_strike >= call_strike:
        notes.append("Put strike is at or above the call strike — atypical collar geometry.")

    return CryptoCollarIllustration(
        settlement=settlement,
        spot=spot,
        put_strike=put_strike,
        call_strike=call_strike,
        expiry_days=expiry_days,
        coins=coins,
        theoretical=theoretical,
        put_premium_usd=put_usd,
        call_premium_usd=call_usd,
        net_premium_coin=net_premium_coin,
        net_premium_usd=net_per_coin,
        breakeven_usd=spot - net_per_coin,
        max_profit_usd=(upside_per_coin + net_per_coin) * coins,
        max_loss_usd=(downside_per_coin - net_per_coin) * coins,
        upside_cap_pct=_safe_pct(call_strike - spot, spot),
        downside_protection_pct=_safe_pct(spot - put_strike, spot),
        net_yield_pct=net_yield_pct,
        annualized_net_yield_pct=_annualize_pct(net_yield_pct, expiry_days),
        call_delta=call_delta,
        prob_call_otm_approx=_prob_otm_from_delta(call_delta),
        notes=notes,
    )


__all__ = [
    "DISCLAIMER",
    "CryptoCollarIllustration",
    "CryptoCoveredCallIllustration",
    "CryptoProtectivePutIllustration",
    "Settlement",
    "crypto_collar",
    "crypto_covered_call",
    "crypto_protective_put",
]
