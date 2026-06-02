# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the settlement-aware crypto covered-call overlay."""

from __future__ import annotations

import pytest

from nexus_core.engine.pricing.crypto_overlays import crypto_covered_call


def test_inverse_covered_call_hand_values() -> None:
    # BTC at 100k, sell the 120k call, 30d, observed coin premium 0.02 BTC, 2 BTC.
    out = crypto_covered_call(
        spot=100_000,
        strike=120_000,
        expiry_days=30,
        settlement="inverse",
        coins=2.0,
        premium=0.02,
        delta=0.25,
    )
    assert out.premium_coin == 0.02
    assert out.premium_usd == 2_000.0  # 0.02 BTC × 100k
    assert out.static_yield_pct == 2.0  # 2000 / 100k
    assert out.annualized_yield_pct == pytest.approx(24.3333, rel=1e-4)  # 2% × 365/30
    assert out.coin_income == pytest.approx(0.04)  # 0.02 × 2 BTC
    assert out.usd_income == 4_000.0
    assert out.coins_if_unassigned == pytest.approx(2.04)  # grows the stack
    assert out.breakeven_usd == 98_000.0  # 100k − 2000
    assert out.distance_to_strike_pct == 20.0
    assert out.return_if_assigned_pct == 22.0  # (20k + 2000) / 100k
    assert out.downside_cushion_pct == 2.0
    assert out.max_profit_usd == 44_000.0  # (20k + 2000) × 2
    assert out.max_loss_usd == 196_000.0  # 98k × 2
    assert out.delta == 0.25
    assert out.prob_otm_approx == 75.0  # (1 − 0.25) × 100
    assert out.theoretical is False


def test_linear_covered_call_hand_values() -> None:
    # SOL at 150, sell the 180 call, 30d, observed USD premium 5, 100 SOL.
    out = crypto_covered_call(
        spot=150,
        strike=180,
        expiry_days=30,
        settlement="linear",
        coins=100,
        premium=5.0,
    )
    assert out.premium_coin is None  # USDC-settled — premium is not coin
    assert out.premium_usd == 5.0
    assert out.coin_income is None
    assert out.coins_if_unassigned is None
    assert out.usd_income == 500.0
    assert out.static_yield_pct == pytest.approx(3.3333, rel=1e-4)
    assert out.breakeven_usd == 145.0
    assert out.distance_to_strike_pct == 20.0
    assert out.return_if_assigned_pct == pytest.approx(23.3333, rel=1e-4)


def test_theoretical_premium_inverse_bridges_to_coin() -> None:
    out = crypto_covered_call(
        spot=100_000, strike=120_000, expiry_days=30, settlement="inverse", iv=0.65
    )
    assert out.theoretical is True
    assert out.premium_usd > 0
    # The coin premium is exactly the USD premium bridged back through spot.
    assert out.premium_coin == pytest.approx(out.premium_usd / 100_000)
    # No observed delta supplied -> Black-Scholes delta computed for the prob.
    assert out.delta is not None
    assert out.prob_otm_approx is not None


def test_bad_settlement_raises() -> None:
    with pytest.raises(ValueError, match="settlement"):
        crypto_covered_call(spot=1, strike=2, expiry_days=30, settlement="weekly")  # type: ignore[arg-type]


def test_degenerate_inputs_zeroed() -> None:
    out = crypto_covered_call(
        spot=0, strike=120_000, expiry_days=30, settlement="inverse", premium=0.02
    )
    assert out.static_yield_pct == 0.0
    assert out.max_loss_usd == 0.0
    assert "zeroed" in " ".join(out.notes)
