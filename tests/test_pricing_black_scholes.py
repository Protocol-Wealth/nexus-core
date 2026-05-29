# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic tests for the Black-Scholes-Merton pricing engine.

No network, no fixtures — pure-math assertions against textbook values, the
put-call parity identity, Greek sign/range conventions, implied-vol round-trips,
and degenerate-input edge cases.
"""

from __future__ import annotations

import math

import pytest

from nexus_core.engine.pricing.black_scholes import (
    Greeks,
    bs_price,
    greeks,
    implied_vol,
)

# A canonical textbook parameter set: at-the-money, 1y, r=5%, sigma=20%, no div.
# Closed-form references: call ≈ 10.4506, put ≈ 5.5735.
_S = 100.0
_K = 100.0
_T = 1.0
_R = 0.05
_SIG = 0.20


# --------------------------- known textbook values ---------------------------


def test_atm_call_matches_textbook() -> None:
    assert bs_price(_S, _K, _T, _R, _SIG, "call") == pytest.approx(10.4506, abs=1e-4)


def test_atm_put_matches_textbook() -> None:
    assert bs_price(_S, _K, _T, _R, _SIG, "put") == pytest.approx(5.5735, abs=1e-4)


def test_deep_itm_call_approaches_forward_minus_discounted_strike() -> None:
    # Deep ITM call with low vol -> ~ discounted intrinsic on the forward.
    price = bs_price(200.0, 100.0, 1.0, 0.05, 0.05, "call")
    expected = 200.0 - 100.0 * math.exp(-0.05)
    assert price == pytest.approx(expected, abs=0.05)


def test_deep_otm_put_is_near_zero() -> None:
    assert bs_price(200.0, 100.0, 1.0, 0.05, 0.20, "put") == pytest.approx(0.0, abs=0.5)


# ------------------------------ put-call parity ------------------------------


def test_put_call_parity_no_dividend() -> None:
    call = bs_price(_S, _K, _T, _R, _SIG, "call")
    put = bs_price(_S, _K, _T, _R, _SIG, "put")
    # C - P = S - K e^{-rT}
    rhs = _S - _K * math.exp(-_R * _T)
    assert (call - put) == pytest.approx(rhs, abs=1e-9)


def test_put_call_parity_with_dividend() -> None:
    q = 0.03
    call = bs_price(_S, _K, _T, _R, _SIG, "call", dividend_yield=q)
    put = bs_price(_S, _K, _T, _R, _SIG, "put", dividend_yield=q)
    # C - P = S e^{-qT} - K e^{-rT}
    rhs = _S * math.exp(-q * _T) - _K * math.exp(-_R * _T)
    assert (call - put) == pytest.approx(rhs, abs=1e-9)


@pytest.mark.parametrize("strike", [80.0, 100.0, 120.0])
@pytest.mark.parametrize("sigma", [0.1, 0.3, 0.6])
def test_put_call_parity_holds_across_strikes_and_vols(strike: float, sigma: float) -> None:
    call = bs_price(_S, strike, _T, _R, sigma, "call")
    put = bs_price(_S, strike, _T, _R, sigma, "put")
    rhs = _S - strike * math.exp(-_R * _T)
    assert (call - put) == pytest.approx(rhs, abs=1e-9)


# ----------------------------------- Greeks ----------------------------------


def test_greeks_returns_dataclass() -> None:
    g = greeks(_S, _K, _T, _R, _SIG, "call")
    assert isinstance(g, Greeks)


def test_atm_call_delta_matches_textbook() -> None:
    g = greeks(_S, _K, _T, _R, _SIG, "call")
    assert g.delta == pytest.approx(0.6368, abs=1e-4)


def test_call_delta_in_zero_one() -> None:
    for strike in (50.0, 100.0, 150.0):
        g = greeks(_S, strike, _T, _R, _SIG, "call")
        assert 0.0 <= g.delta <= 1.0


def test_put_delta_in_minus_one_zero() -> None:
    for strike in (50.0, 100.0, 150.0):
        g = greeks(_S, strike, _T, _R, _SIG, "put")
        assert -1.0 <= g.delta <= 0.0


def test_gamma_and_vega_equal_for_call_and_put() -> None:
    gc = greeks(_S, _K, _T, _R, _SIG, "call")
    gp = greeks(_S, _K, _T, _R, _SIG, "put")
    assert gc.gamma == pytest.approx(gp.gamma, abs=1e-12)
    assert gc.vega == pytest.approx(gp.vega, abs=1e-12)
    assert gc.gamma > 0.0
    assert gc.vega > 0.0


def test_long_option_theta_is_negative() -> None:
    # A long ATM option loses value as time passes -> theta < 0.
    assert greeks(_S, _K, _T, _R, _SIG, "call").theta < 0.0
    assert greeks(_S, _K, _T, _R, _SIG, "put").theta < 0.0


def test_call_rho_positive_put_rho_negative() -> None:
    assert greeks(_S, _K, _T, _R, _SIG, "call").rho > 0.0
    assert greeks(_S, _K, _T, _R, _SIG, "put").rho < 0.0


def test_vega_per_point_convention() -> None:
    # vega (per 1% vol) * 100 ≈ finite-difference dPrice/dSigma over a 1% bump.
    g = greeks(_S, _K, _T, _R, _SIG, "call")
    bump = 0.01
    up = bs_price(_S, _K, _T, _R, _SIG + bump, "call")
    down = bs_price(_S, _K, _T, _R, _SIG - bump, "call")
    fd = (up - down) / (2.0 * bump)
    assert g.vega * 100.0 == pytest.approx(fd, abs=1e-2)


def test_theta_per_day_convention() -> None:
    # theta (per day) * 365 ≈ analytic annual decay; verify against tiny dt bump.
    g = greeks(_S, _K, _T, _R, _SIG, "call")
    dt = 1.0 / 365.0
    p0 = bs_price(_S, _K, _T, _R, _SIG, "call")
    p1 = bs_price(_S, _K, _T - dt, _R, _SIG, "call")
    one_day_decay = p1 - p0
    assert g.theta == pytest.approx(one_day_decay, abs=2e-3)


def test_delta_matches_finite_difference() -> None:
    g = greeks(_S, _K, _T, _R, _SIG, "call")
    bump = 0.01
    up = bs_price(_S + bump, _K, _T, _R, _SIG, "call")
    down = bs_price(_S - bump, _K, _T, _R, _SIG, "call")
    fd = (up - down) / (2.0 * bump)
    assert g.delta == pytest.approx(fd, abs=1e-4)


# -------------------------------- implied vol --------------------------------


def test_implied_vol_round_trips_call() -> None:
    price = bs_price(_S, _K, _T, _R, _SIG, "call")
    iv = implied_vol(price, _S, _K, _T, _R, "call")
    assert iv is not None
    assert iv == pytest.approx(_SIG, abs=1e-6)


def test_implied_vol_round_trips_put() -> None:
    price = bs_price(_S, _K, _T, _R, _SIG, "put")
    iv = implied_vol(price, _S, _K, _T, _R, "put")
    assert iv is not None
    assert iv == pytest.approx(_SIG, abs=1e-6)


@pytest.mark.parametrize("strike", [70.0, 90.0, 100.0, 110.0, 130.0])
@pytest.mark.parametrize("true_sigma", [0.08, 0.15, 0.35, 0.75])
def test_implied_vol_round_trips_across_grid(strike: float, true_sigma: float) -> None:
    price = bs_price(_S, strike, _T, _R, true_sigma, "call")
    iv = implied_vol(price, _S, strike, _T, _R, "call")
    assert iv is not None
    assert iv == pytest.approx(true_sigma, abs=1e-4)


def test_implied_vol_round_trips_with_dividend() -> None:
    q = 0.04
    price = bs_price(_S, _K, _T, _R, _SIG, "call", dividend_yield=q)
    iv = implied_vol(price, _S, _K, _T, _R, "call", dividend_yield=q)
    assert iv is not None
    assert iv == pytest.approx(_SIG, abs=1e-5)


def test_implied_vol_deep_itm_low_vega_uses_bisection() -> None:
    # Deep ITM, short-dated -> tiny vega; Newton stalls and bisection takes over.
    true_sigma = 0.20
    price = bs_price(_S, 50.0, 0.05, _R, true_sigma, "call")
    iv = implied_vol(price, _S, 50.0, 0.05, _R, "call")
    # Deep ITM intrinsic dominates; recovered IV should be plausible & non-None.
    assert iv is not None
    assert 0.0 < iv <= 10.0


def test_implied_vol_below_intrinsic_returns_none() -> None:
    # A price below the no-arbitrage floor has no real implied vol.
    floor = bs_price(_S, 50.0, _T, _R, 1e-9, "call")  # ~ discounted intrinsic
    assert implied_vol(floor - 1.0, _S, 50.0, _T, _R, "call") is None


def test_implied_vol_above_upper_bound_returns_none() -> None:
    # A call cannot be worth more than the (dividend-discounted) spot.
    assert implied_vol(_S + 5.0, _S, _K, _T, _R, "call") is None


def test_implied_vol_non_positive_price_returns_none() -> None:
    assert implied_vol(0.0, _S, _K, _T, _R, "call") is None
    assert implied_vol(-1.0, _S, _K, _T, _R, "call") is None


# ------------------------------- edge / degenerate ---------------------------


def test_price_at_expiry_is_intrinsic_call() -> None:
    assert bs_price(110.0, 100.0, 0.0, _R, _SIG, "call") == pytest.approx(10.0, abs=1e-12)
    assert bs_price(90.0, 100.0, 0.0, _R, _SIG, "call") == pytest.approx(0.0, abs=1e-12)


def test_price_at_expiry_is_intrinsic_put() -> None:
    assert bs_price(90.0, 100.0, 0.0, _R, _SIG, "put") == pytest.approx(10.0, abs=1e-12)
    assert bs_price(110.0, 100.0, 0.0, _R, _SIG, "put") == pytest.approx(0.0, abs=1e-12)


def test_negative_time_treated_as_expired() -> None:
    assert bs_price(110.0, 100.0, -1.0, _R, _SIG, "call") == pytest.approx(10.0, abs=1e-12)


def test_zero_sigma_returns_discounted_intrinsic() -> None:
    # sigma <= 0 -> forward-consistent discounted intrinsic, never NaN/raise.
    price = bs_price(_S, _K, _T, _R, 0.0, "call")
    fwd = _S * math.exp(_R * _T)
    expected = max(fwd - _K, 0.0) * math.exp(-_R * _T)
    assert price == pytest.approx(expected, abs=1e-12)


def test_non_positive_spot_or_strike_returns_intrinsic() -> None:
    assert bs_price(0.0, 100.0, _T, _R, _SIG, "call") == 0.0
    assert bs_price(100.0, 0.0, _T, _R, _SIG, "put") == 0.0
    assert bs_price(-5.0, 100.0, _T, _R, _SIG, "call") == 0.0


def test_greeks_degenerate_inputs_return_intrinsic_delta_step() -> None:
    # At expiry, delta collapses to the intrinsic ±1/0 step; others zero.
    g_itm = greeks(110.0, 100.0, 0.0, _R, _SIG, "call")
    assert g_itm.delta == 1.0
    assert g_itm.gamma == 0.0
    assert g_itm.theta == 0.0
    assert g_itm.vega == 0.0
    assert g_itm.rho == 0.0

    g_otm = greeks(90.0, 100.0, 0.0, _R, _SIG, "call")
    assert g_otm.delta == 0.0

    g_put = greeks(90.0, 100.0, 0.0, _R, _SIG, "put")
    assert g_put.delta == -1.0


def test_greeks_zero_sigma_returns_intrinsic_delta_step() -> None:
    g = greeks(110.0, 100.0, _T, _R, 0.0, "call")
    assert g.delta == 1.0
    assert g.gamma == 0.0


def test_implied_vol_zero_time_returns_none() -> None:
    assert implied_vol(10.0, 110.0, 100.0, 0.0, _R, "call") is None


def test_implied_vol_non_positive_spot_returns_none() -> None:
    assert implied_vol(10.0, 0.0, 100.0, _T, _R, "call") is None
    assert implied_vol(10.0, 100.0, 0.0, _T, _R, "call") is None

