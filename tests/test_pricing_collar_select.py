# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the batch equity collar-screen engine (``collar_select``).

Pure math — no market provider, no network, no clock.
"""

from __future__ import annotations

import math

from nexus_core.engine.pricing import (
    CollarScreenPosition,
    evaluate_collar_position,
    screen_collars,
)
from nexus_core.engine.pricing.black_scholes import greeks


def _pos(
    symbol: str = "TEST",
    spot: float = 100.0,
    sigma: float = 0.25,
    expiry_days: int = 45,
    dividend_yield: float = 0.0,
) -> CollarScreenPosition:
    return CollarScreenPosition(
        symbol=symbol,
        spot=spot,
        sigma=sigma,
        expiry_days=expiry_days,
        dividend_yield=dividend_yield,
    )


def _on_grid(strike: float, increment: float) -> bool:
    return math.isclose(strike / increment, round(strike / increment), abs_tol=1e-9)


def test_put_call_strike_geometry() -> None:
    r = evaluate_collar_position(_pos())
    # 15% below 100 on the $1 grid.
    assert r.put_strike == 85.0
    assert r.put_strike < r.spot < r.call_strike
    # Minimum-OTM floor: call at least 1% above spot even after snapping.
    assert r.call_strike >= 100.0 * 1.01
    assert r.floor_pct == 15.0
    assert r.downside_protection_pct == r.floor_pct
    assert r.cap_pct > 0.0
    assert r.theoretical is True
    assert "not investment advice" in r.disclaimer.lower()


def test_call_strike_targets_delta() -> None:
    r = evaluate_collar_position(_pos(), target_call_delta=0.30)
    # The solved strike hits 0.30 exactly; snapping UP one grid step at most
    # nudges the delta down a little. It must stay near — and not above — target.
    assert 0.20 <= r.call_delta <= 0.301
    # Result delta matches an independent Greeks evaluation at the same strike.
    check = greeks(100.0, r.call_strike, 45 / 365.0, 0.04, 0.25, "call").delta
    assert math.isclose(r.call_delta, check, abs_tol=1e-12)


def test_call_min_otm_floor_binds_for_high_delta_targets() -> None:
    # A 0.60-delta call sits below spot*(1.01): the floor must win, snapped UP.
    r = evaluate_collar_position(_pos(), target_call_delta=0.60)
    assert r.call_strike >= 100.0 * 1.01
    assert any("minimum-OTM" in w for w in r.warnings)


def test_dividend_yield_changes_premiums() -> None:
    # Pin the call strike to the floor in both runs so premiums are compared
    # at identical strikes.
    r0 = evaluate_collar_position(_pos(dividend_yield=0.0), target_call_delta=0.9)
    rq = evaluate_collar_position(_pos(dividend_yield=0.04), target_call_delta=0.9)
    assert r0.put_strike == rq.put_strike
    assert r0.call_strike == rq.call_strike
    # A continuous dividend yield cheapens calls and enriches puts.
    assert rq.call_premium < r0.call_premium
    assert rq.put_premium > r0.put_premium
    # Dividend income is credited over the window and in the annual total.
    assert r0.dividend_income == 0.0
    assert math.isclose(rq.dividend_income, 100.0 * 0.04 * 45 / 365.0)
    assert math.isclose(
        rq.total_annualized_income_pct, rq.annualized_return_pct + 4.0, abs_tol=1e-9
    )


def test_degenerate_inputs_zero_out() -> None:
    for pos in (
        _pos(spot=0.0),
        _pos(spot=-5.0),
        _pos(sigma=0.0),
        _pos(sigma=-0.2),
        _pos(expiry_days=0),
        _pos(expiry_days=-10),
    ):
        r = evaluate_collar_position(pos)
        assert r.put_strike == 0.0 and r.call_strike == 0.0
        assert r.net_credit == 0.0 and r.max_profit == 0.0 and r.max_loss == 0.0
        assert r.total_annualized_income_pct == 0.0
        assert r.prob_put_otm_approx is None and r.prob_call_otm_approx is None
        assert r.warnings, pos


def test_strike_grid_bands() -> None:
    # <25: $0.50 — <200: $1 — <500: $5 — else $10 (documented approximation).
    for spot, increment in ((20.0, 0.5), (100.0, 1.0), (300.0, 5.0), (800.0, 10.0)):
        r = evaluate_collar_position(_pos(spot=spot))
        assert _on_grid(r.put_strike, increment), (spot, r.put_strike)
        assert _on_grid(r.call_strike, increment), (spot, r.call_strike)


def test_prob_otm_uses_one_minus_delta_convention() -> None:
    r = evaluate_collar_position(_pos())
    assert r.prob_put_otm_approx == round((1.0 - abs(r.put_delta)) * 100.0, 1)
    assert r.prob_call_otm_approx == round((1.0 - abs(r.call_delta)) * 100.0, 1)


def test_net_debit_warns() -> None:
    # A long tenor + heavy dividend yield makes the put far dearer than the call.
    r = evaluate_collar_position(_pos(expiry_days=365, dividend_yield=0.5))
    assert r.net_credit < 0.0
    assert any("Net debit" in w for w in r.warnings)
    assert r.breakeven > r.spot  # a debit raises breakeven


def test_screen_ranks_net_credit_before_higher_income_debit() -> None:
    credit = _pos(symbol="CRD", expiry_days=365, dividend_yield=0.0)
    debit = _pos(symbol="DBT", expiry_days=365, dividend_yield=0.5)
    ranked = screen_collars([debit, credit])
    # The debit collar shows a higher total income (dividends), but the
    # net-credit structure still ranks first per the documented heuristic.
    assert ranked[0].symbol == "CRD" and ranked[0].net_credit >= 0.0
    assert ranked[1].symbol == "DBT" and ranked[1].net_credit < 0.0
    assert ranked[1].total_annualized_income_pct > ranked[0].total_annualized_income_pct


def test_screen_ranks_by_income_within_credit_group() -> None:
    low = _pos(symbol="LOWVOL", sigma=0.15)
    high = _pos(symbol="HIVOL", sigma=0.45)
    ranked = screen_collars([low, high])
    assert [r.symbol for r in ranked] == ["HIVOL", "LOWVOL"]
    assert all(r.net_credit >= 0.0 for r in ranked)
    assert ranked[0].total_annualized_income_pct >= ranked[1].total_annualized_income_pct
