# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the options-book mark-to-market + scenario stress."""

from __future__ import annotations

from nexus_core.engine.pricing.options_book import (
    BookPosition,
    book_mtm,
    scenario_stress,
)

_SHORT_CALL = BookPosition(
    kind="call",
    side="short",
    strike=120_000,
    expiry_days=30,
    coins=1.0,
    entry_premium=0.03,
    iv=0.6,
    mark_premium=0.02,
    label="overwrite",
)


def test_book_mtm_short_call_pnl_and_net_delta() -> None:
    out = book_mtm(spot=100_000, settlement="inverse", positions=[_SHORT_CALL], coins_held=1.0)
    # Short call: collected 3000 (0.03×100k), now worth 2000 -> +1000 profit.
    assert out.total_pnl_usd == 1_000.0
    # Short call delta is negative; underlying coin adds +1, net stays < 1.
    assert out.net_option_delta < 0
    assert out.net_delta_with_underlying == out.net_option_delta + 1.0
    assert out.net_delta_with_underlying < 1.0
    assert out.net_theta_usd_day > 0  # short option -> positive theta (time decay helps)
    assert out.net_vega_usd_per_vol_pt < 0  # short vega
    assert out.positions[0]["pnl_usd"] == 1_000.0
    assert any("Inverse" in n for n in out.notes)


def test_scenario_stress_grid_and_assignment_flag() -> None:
    out = scenario_stress(
        spot=100_000,
        settlement="inverse",
        positions=[_SHORT_CALL],
        spot_shocks=[-0.2, 0.0, 0.25],
        coins_held=1.0,
    )
    assert len(out.cells) == 3  # 3 spot shocks × 1 (default) iv shock
    by_shock = {c.spot_shock_pct: c for c in out.cells}

    flat = by_shock[0.0]
    assert flat.underlying_pnl_usd == 0.0  # spot unchanged

    down = by_shock[-20.0]
    assert down.spot == 80_000.0
    assert down.underlying_pnl_usd == -20_000.0  # 1 coin × (80k − 100k)
    assert down.short_calls_itm == 0  # 80k < 120k strike
    assert down.option_pnl_usd > 0  # short call gains as spot falls

    up = by_shock[25.0]
    assert up.spot == 125_000.0
    assert up.underlying_pnl_usd == 25_000.0
    assert up.short_calls_itm == 1  # 125k > 120k strike -> assignment risk
    assert up.option_pnl_usd < 0  # short call loses as spot rises


def test_scenario_iv_shock_grid_dimensions() -> None:
    out = scenario_stress(
        spot=100_000,
        settlement="inverse",
        positions=[_SHORT_CALL],
        spot_shocks=[-0.1, 0.0, 0.1],
        iv_shocks=[-0.1, 0.0, 0.1],
        coins_held=1.0,
    )
    assert len(out.cells) == 9  # 3 × 3 grid
    # A short option loses when IV rises (vol up, spot flat).
    flat_iv_up = next(c for c in out.cells if c.spot_shock_pct == 0.0 and c.iv_shock_pts == 10.0)
    assert flat_iv_up.option_pnl_usd < 0


def test_linear_book_uses_usd_premiums_directly() -> None:
    leg = BookPosition(
        kind="call",
        side="short",
        strike=180,
        expiry_days=30,
        coins=100,
        entry_premium=6.0,
        iv=0.8,
        mark_premium=4.0,
    )
    out = book_mtm(spot=150, settlement="linear", positions=[leg], coins_held=100)
    # Linear: premiums are USD. Short collected 6, now 4 -> +2/contract × 100 = 200.
    assert out.total_pnl_usd == 200.0
