# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the pure Uniswap V3 LP math.

Tick/amount/fee-APR/uncollected-fee vectors are ported from the pw-onchain
reference oracle (test_lp_analytics_math.py). The impermanent-loss tests are
NEW — the engine implements EXACT IL (amount reconstruction vs a HODL of the
deposited amounts), not the reference's capped full-range heuristic, so the
heuristic's 50x-cap vectors do not apply.
"""

from __future__ import annotations

import pytest

from nexus_core.engine.lp import (
    analyze_uniswap_v3_position,
    estimate_fee_apr,
    get_amounts_for_liquidity,
    impermanent_loss_vs_hodl,
    is_in_range,
    sqrt_price_x96_to_price,
    tick_to_price,
    tick_to_sqrt_price_x96,
    uncollected_fees_from_growth,
)
from nexus_core.engine.lp.uniswap_v3 import Q96, Q128

# ── tick / price ────────────────────────────────────────────────────


def test_tick_to_price() -> None:
    assert tick_to_price(0) == pytest.approx(1.0)
    assert 1.01 < tick_to_price(100) < 1.011
    assert 0.99 < tick_to_price(-100) < 1.0
    assert tick_to_price(500) * tick_to_price(-500) == pytest.approx(1.0)
    assert tick_to_price(200000) > 1000


def test_tick_to_sqrt_price_x96() -> None:
    assert tick_to_sqrt_price_x96(0) == Q96
    assert tick_to_sqrt_price_x96(100) > Q96
    assert tick_to_sqrt_price_x96(-100) < Q96
    assert isinstance(tick_to_sqrt_price_x96(1000), int)


def test_sqrt_price_x96_to_price() -> None:
    assert sqrt_price_x96_to_price(Q96, 18, 18) == pytest.approx(1.0)
    assert sqrt_price_x96_to_price(tick_to_sqrt_price_x96(0), 18, 18) == pytest.approx(1.0)
    # USDC(6)/ETH(18): 12-decimal delta → 1e-12
    assert sqrt_price_x96_to_price(Q96, 6, 18) == pytest.approx(1e-12, rel=0.01)


# ── amounts ─────────────────────────────────────────────────────────


def test_amounts_below_range_all_token0() -> None:
    a0, a1 = get_amounts_for_liquidity(tick_to_sqrt_price_x96(50), 100, 200, 10**18)
    assert a0 > 0 and a1 == 0.0


def test_amounts_above_range_all_token1() -> None:
    a0, a1 = get_amounts_for_liquidity(tick_to_sqrt_price_x96(300), 100, 200, 10**18)
    assert a0 == 0.0 and a1 > 0


def test_amounts_in_range_both_tokens() -> None:
    a0, a1 = get_amounts_for_liquidity(tick_to_sqrt_price_x96(150), 100, 200, 10**18)
    assert a0 > 0 and a1 > 0


def test_amounts_decimals_scaling() -> None:
    spx = tick_to_sqrt_price_x96(50)  # below range, all token0
    a0_18, _ = get_amounts_for_liquidity(spx, 100, 200, 10**18, decimals0=18)
    a0_6, _ = get_amounts_for_liquidity(spx, 100, 200, 10**18, decimals0=6)
    assert a0_6 > a0_18 * 1e11


def test_amounts_zero_liquidity() -> None:
    assert get_amounts_for_liquidity(tick_to_sqrt_price_x96(150), 100, 200, 0) == (0.0, 0.0)


def test_amounts_returns_floats() -> None:
    result = get_amounts_for_liquidity(Q96, 0, 100, 1000)
    assert isinstance(result, tuple) and len(result) == 2
    assert all(isinstance(x, float) for x in result)


def test_is_in_range() -> None:
    assert is_in_range(150, 100, 200)
    assert not is_in_range(50, 100, 200)
    assert not is_in_range(200, 100, 200)  # upper bound exclusive
    assert is_in_range(100, 100, 200)  # lower bound inclusive


# ── fee APR ─────────────────────────────────────────────────────────


def test_fee_apr_out_of_range_zero() -> None:
    assert estimate_fee_apr(1_000_000, 10_000_000, 3000, 10**18, 10**20, in_range=False) == 0.0


def test_fee_apr_zero_tvl_or_liquidity() -> None:
    assert estimate_fee_apr(1_000_000, 0, 3000, 10**18, 10**20, in_range=True) == 0.0
    assert estimate_fee_apr(1_000_000, 10_000_000, 3000, 10**18, 0, in_range=True) == 0.0


def test_fee_apr_full_share_vector() -> None:
    # $1M vol * 0.3% = $3000/day; *365 / $10M TVL * 100 = 10.95%
    apr = estimate_fee_apr(1_000_000, 10_000_000, 3000, 10**18, 10**18, in_range=True)
    assert apr == pytest.approx(10.95, rel=0.01)


def test_fee_apr_proportional_share_same_rate() -> None:
    full = estimate_fee_apr(1_000_000, 10_000_000, 3000, 10**18, 10**18, in_range=True)
    tiny = estimate_fee_apr(1_000_000, 10_000_000, 3000, 10**16, 10**18, in_range=True)
    assert full == pytest.approx(tiny, rel=0.01)


def test_fee_apr_scales_with_fee_tier() -> None:
    base = {
        "pool_volume_24h_usd": 1_000_000,
        "pool_tvl_usd": 10_000_000,
        "position_liquidity": 10**18,
        "pool_liquidity": 10**18,
        "in_range": True,
    }
    low = estimate_fee_apr(fee_tier=500, **base)
    high = estimate_fee_apr(fee_tier=10_000, **base)
    assert high == pytest.approx(low * 20, rel=0.01)


# ── uncollected fees (feeGrowth delta) ──────────────────────────────


def test_uncollected_no_delta_zero() -> None:
    assert uncollected_fees_from_growth(100, 200, 100, 200, 10**18) == (0.0, 0.0)


def test_uncollected_positive_growth() -> None:
    f0, f1 = uncollected_fees_from_growth(Q128, Q128 * 2, 0, 0, 10**18, 18, 18)
    assert f0 == pytest.approx(1.0)
    assert f1 == pytest.approx(2.0)


def test_uncollected_uint256_wraparound() -> None:
    f0, _ = uncollected_fees_from_growth(10, 0, 2**256 - 10, 0, 10**18)
    assert f0 > 0  # delta = 20 via modular arithmetic


def test_uncollected_decimals_magnitude() -> None:
    args = {
        "fee_growth_inside0_x128": Q128,
        "fee_growth_inside1_x128": 0,
        "fee_growth_inside0_last_x128": 0,
        "fee_growth_inside1_last_x128": 0,
        "liquidity": 10**18,
    }
    f0_18, _ = uncollected_fees_from_growth(**args, decimals0=18, decimals1=18)
    f0_6, _ = uncollected_fees_from_growth(**args, decimals0=6, decimals1=18)
    assert f0_6 == pytest.approx(f0_18 * 1e12, rel=0.01)


# ── impermanent loss (EXACT — new) ──────────────────────────────────


def test_il_flat_no_divergence() -> None:
    # LP amounts equal deposited amounts → zero IL regardless of prices.
    il_usd, il_pct = impermanent_loss_vs_hodl(1.0, 1000.0, 1.0, 1000.0, 2000.0, 1.0)
    assert il_usd == pytest.approx(0.0)
    assert il_pct == pytest.approx(0.0)


def test_il_divergence_is_negative() -> None:
    # Deposited 1 ETH + 1000 USDC; ETH now $2000. HODL = 1*2000 + 1000 = 3000.
    # LP rebalanced to 0.7 ETH + 1400 USDC → 0.7*2000 + 1400 = 2800. IL = -200.
    il_usd, il_pct = impermanent_loss_vs_hodl(1.0, 1000.0, 0.7, 1400.0, 2000.0, 1.0)
    assert il_usd == pytest.approx(-200.0)
    assert il_pct == pytest.approx(-200.0 / 3000.0 * 100)


def test_il_zero_baseline_returns_zero_pct() -> None:
    il_usd, il_pct = impermanent_loss_vs_hodl(0.0, 0.0, 0.0, 0.0, 2000.0, 1.0)
    assert il_usd == pytest.approx(0.0)
    assert il_pct == 0.0


def test_il_excludes_fees() -> None:
    # IL is purely value-vs-HODL; identical token composition → 0 IL.
    il_usd, _ = impermanent_loss_vs_hodl(2.0, 0.0, 2.0, 0.0, 1500.0, 1.0)
    assert il_usd == pytest.approx(0.0)


# ── orchestrator ────────────────────────────────────────────────────


def test_analyze_position_composes() -> None:
    res = analyze_uniswap_v3_position(
        token_id="123",
        chain="ethereum",
        pool="0xpool",
        token0_symbol="USDC",
        token1_symbol="WETH",
        decimals0=6,
        decimals1=18,
        fee_tier=3000,
        liquidity=10**18,
        tick_lower=100,
        tick_upper=300,
        current_tick=200,
        sqrt_price_x96=tick_to_sqrt_price_x96(200),
        deposited0=1000.0,
        deposited1=0.5,
        pool_liquidity=10**18,
        pool_tvl_usd=10_000_000,
        pool_avg_daily_volume_usd=1_000_000,
        price_token0_usd=1.0,
        price_token1_usd=2000.0,
        uncollected0=10.0,
        uncollected1=0.001,
        reward_apr=4.0,
    )
    assert res.in_range is True
    assert res.fee_apr_estimate == pytest.approx(10.95, rel=0.01)
    assert res.reward_apr == 4.0
    assert res.total_apr_estimate == pytest.approx(14.95, rel=0.01)
    assert res.uncollected_fees_usd == pytest.approx(10.0 * 1.0 + 0.001 * 2000.0)
    assert res.impermanent_loss_usd is not None  # deposit baseline present
    assert res.liquidity == "1000000000000000000"


def test_analyze_position_out_of_range_no_fee_apr_no_il_baseline() -> None:
    res = analyze_uniswap_v3_position(
        token_id="1",
        chain="ethereum",
        pool="0xp",
        token0_symbol="A",
        token1_symbol="B",
        decimals0=18,
        decimals1=18,
        fee_tier=3000,
        liquidity=10**18,
        tick_lower=100,
        tick_upper=200,
        current_tick=50,
        sqrt_price_x96=tick_to_sqrt_price_x96(50),
        deposited0=0.0,
        deposited1=0.0,
        pool_liquidity=10**18,
        pool_tvl_usd=1_000_000,
        pool_avg_daily_volume_usd=100_000,
        price_token0_usd=1.0,
        price_token1_usd=1.0,
        uncollected0=0.0,
        uncollected1=0.0,
    )
    assert res.in_range is False
    assert res.fee_apr_estimate == 0.0  # out of range
    assert res.impermanent_loss_usd is None  # no deposit baseline
