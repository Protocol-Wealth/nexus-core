# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic unit tests for the educational option-overlay illustrators."""

from __future__ import annotations

import math

import pytest

from nexus_core.disclaimers import TERSE
from nexus_core.engine.pricing.black_scholes import bs_price
from nexus_core.engine.pricing.overlays import (
    DISCLAIMER,
    cash_secured_put_overlay,
    collar_overlay,
    covered_call_overlay,
)


def test_disclaimer_is_canonical_terse() -> None:
    # The module must not hand-write regulatory copy — DISCLAIMER is sourced
    # from the single-source canonical TERSE.
    assert DISCLAIMER == TERSE


@pytest.mark.unit
class TestCoveredCall:
    def test_worked_example(self) -> None:
        # spot 100, strike 105, 30 days, premium 2, 100 shares.
        ill = covered_call_overlay(100.0, 105.0, 30, premium=2.0, shares=100)

        assert ill.theoretical is False
        assert ill.net_premium == pytest.approx(200.0)  # 2 * 100, credit
        assert ill.breakeven == pytest.approx(98.0)  # spot - premium
        # max profit if assigned: (105 - 100 + 2) * 100 = 700
        assert ill.max_profit == pytest.approx(700.0)
        # static return = premium / spot = 2%
        assert ill.static_return_pct == pytest.approx(2.0)
        # return if assigned = (5 + 2) / 100 = 7%
        assert ill.return_if_assigned_pct == pytest.approx(7.0)
        # downside protection = premium / spot = 2%
        assert ill.downside_protection_pct == pytest.approx(2.0)
        # OTM% = (105 - 100) / 100 = 5%
        assert ill.otm_pct == pytest.approx(5.0)
        # annualized static = 2% * 365/30
        assert ill.annualized_return_pct == pytest.approx(2.0 * 365.0 / 30.0)
        assert ill.disclaimer == DISCLAIMER

    def test_max_loss_is_breakeven_capital(self) -> None:
        ill = covered_call_overlay(100.0, 105.0, 30, premium=2.0, shares=100)
        # If the stock falls to zero: lose (spot - premium) per share.
        assert ill.max_loss == pytest.approx(98.0 * 100)

    def test_theoretical_premium_path(self) -> None:
        ill = covered_call_overlay(100.0, 105.0, 30, premium=None, sigma=0.30, rate=0.04)
        assert ill.theoretical is True
        expected = bs_price(100.0, 105.0, 30 / 365.0, 0.04, 0.30, "call")
        assert ill.premium == pytest.approx(expected)
        assert ill.premium > 0.0
        assert any("theoretical" in n.lower() for n in ill.notes)

    def test_prob_otm_in_unit_range(self) -> None:
        ill = covered_call_overlay(100.0, 110.0, 30, premium=None, sigma=0.25)
        assert ill.prob_otm_approx is not None
        assert 0.0 <= ill.prob_otm_approx <= 100.0
        # A 10%-OTM call with 30 DTE should be more likely than not to expire OTM.
        assert ill.prob_otm_approx > 50.0

    def test_degenerate_inputs_zeroed(self) -> None:
        ill = covered_call_overlay(0.0, 105.0, 30, premium=2.0)
        assert ill.net_premium == 0.0
        assert ill.max_profit == 0.0
        assert ill.prob_otm_approx is None
        assert ill.disclaimer == DISCLAIMER


@pytest.mark.unit
class TestCashSecuredPut:
    def test_worked_example_cash_and_breakeven(self) -> None:
        # spot 100, strike 95, 30 days, premium 2, 1 contract.
        ill = cash_secured_put_overlay(100.0, 95.0, 30, premium=2.0, contracts=1)

        assert ill.cash_secured == pytest.approx(95.0 * 100)  # strike * 100
        assert ill.breakeven == pytest.approx(93.0)  # strike - premium
        assert ill.net_premium == pytest.approx(200.0)  # 2 * 100
        assert ill.max_profit == pytest.approx(200.0)  # premium kept
        # static return on secured cash = premium / strike
        assert ill.static_return_pct == pytest.approx(2.0 / 95.0 * 100)
        # OTM% = (100 - 95) / 100 = 5%
        assert ill.otm_pct == pytest.approx(5.0)
        assert ill.disclaimer == DISCLAIMER

    def test_max_loss_to_zero(self) -> None:
        ill = cash_secured_put_overlay(100.0, 95.0, 30, premium=2.0, contracts=2)
        # If underlying → 0: lose breakeven per share over 200 shares.
        assert ill.max_loss == pytest.approx(93.0 * 200)
        assert ill.cash_secured == pytest.approx(95.0 * 200)

    def test_theoretical_premium_path(self) -> None:
        ill = cash_secured_put_overlay(100.0, 95.0, 30, premium=None, sigma=0.30, rate=0.04)
        assert ill.theoretical is True
        expected = bs_price(100.0, 95.0, 30 / 365.0, 0.04, 0.30, "put")
        assert ill.premium == pytest.approx(expected)
        assert ill.premium > 0.0

    def test_multiple_contracts_scale(self) -> None:
        one = cash_secured_put_overlay(100.0, 95.0, 30, premium=2.0, contracts=1)
        three = cash_secured_put_overlay(100.0, 95.0, 30, premium=2.0, contracts=3)
        assert three.net_premium == pytest.approx(one.net_premium * 3)
        assert three.cash_secured == pytest.approx(one.cash_secured * 3)
        # Per-share percentages are independent of contract count.
        assert three.static_return_pct == pytest.approx(one.static_return_pct)


@pytest.mark.unit
class TestCollar:
    def test_max_loss_bounded_by_put_floor(self) -> None:
        # spot 100, put 95, call 110, 30 days, put debit 3, call credit 2.
        ill = collar_overlay(
            100.0, 95.0, 110.0, 30, put_premium=3.0, call_premium=2.0, shares=100
        )
        # net per share = call - put = 2 - 3 = -1 (debit)
        assert ill.net_premium == pytest.approx(-1.0 * 100)
        # max loss = (spot - put_strike - net) * shares = (5 - (-1)) * 100 = 600
        assert ill.max_loss == pytest.approx(600.0)
        # max profit = (call_strike - spot + net) * shares = (10 + (-1)) * 100 = 900
        assert ill.max_profit == pytest.approx(900.0)
        # Loss is strictly bounded (collar floors downside) — finite and modest.
        assert ill.max_loss < ill.spot * ill.shares
        assert ill.disclaimer == DISCLAIMER

    def test_breakeven_debit_raises(self) -> None:
        ill = collar_overlay(
            100.0, 95.0, 110.0, 30, put_premium=3.0, call_premium=2.0, shares=100
        )
        # net debit of 1/share raises breakeven above spot.
        assert ill.breakeven == pytest.approx(101.0)
        assert ill.downside_protection_pct == pytest.approx(5.0)  # (100-95)/100
        assert ill.otm_pct == pytest.approx(10.0)  # (110-100)/100

    def test_zero_cost_collar_credit(self) -> None:
        ill = collar_overlay(
            100.0, 95.0, 110.0, 30, put_premium=2.0, call_premium=2.5, shares=100
        )
        # net credit 0.5/share lowers breakeven below spot.
        assert ill.net_premium == pytest.approx(50.0)
        assert ill.breakeven == pytest.approx(99.5)

    def test_theoretical_both_premiums(self) -> None:
        ill = collar_overlay(100.0, 95.0, 110.0, 30, sigma=0.30, rate=0.04)
        assert ill.theoretical is True
        exp_put = bs_price(100.0, 95.0, 30 / 365.0, 0.04, 0.30, "put")
        exp_call = bs_price(100.0, 110.0, 30 / 365.0, 0.04, 0.30, "call")
        assert ill.put_premium == pytest.approx(exp_put)
        assert ill.call_premium == pytest.approx(exp_call)
        # Max loss must remain finite and bounded by the put floor.
        assert math.isfinite(ill.max_loss)
        assert ill.max_loss < ill.spot * ill.shares

    def test_degenerate_inputs_zeroed(self) -> None:
        ill = collar_overlay(-1.0, 95.0, 110.0, 30, put_premium=3.0, call_premium=2.0)
        assert ill.max_loss == 0.0
        assert ill.max_profit == 0.0
        assert ill.prob_otm_approx is None


@pytest.mark.unit
class TestEducationalFraming:
    def test_all_outputs_carry_disclaimer(self) -> None:
        cc = covered_call_overlay(100.0, 105.0, 30, premium=2.0)
        csp = cash_secured_put_overlay(100.0, 95.0, 30, premium=2.0)
        col = collar_overlay(100.0, 95.0, 110.0, 30, put_premium=3.0, call_premium=2.0)
        for ill in (cc, csp, col):
            assert ill.disclaimer == DISCLAIMER
            assert ill.disclaimer == TERSE
            assert "not investment, tax, legal, or financial advice" in ill.disclaimer.lower()

