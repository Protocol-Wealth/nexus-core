# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the option-chain ranking + strike-by-delta selection."""

from __future__ import annotations

from nexus_core.engine.pricing.option_chain import (
    ChainQuote,
    rank_covered_calls,
    select_by_delta,
)

_SPOT = 100_000.0
_QUOTES = [
    ChainQuote("BTC-30D-110k-C", "call", 110_000, 30, premium=0.03, delta=0.35),
    ChainQuote("BTC-30D-120k-C", "call", 120_000, 30, premium=0.02, delta=0.25),
    ChainQuote("BTC-60D-130k-C", "call", 130_000, 60, premium=0.025, delta=0.20),
    ChainQuote("BTC-30D-90k-C", "call", 90_000, 30, premium=0.12, delta=0.70),  # ITM
    ChainQuote("BTC-30D-120k-P", "put", 120_000, 30, premium=0.05, delta=-0.30),
]


def test_rank_covered_calls_orders_by_annualized_yield() -> None:
    rows = rank_covered_calls(spot=_SPOT, settlement="inverse", quotes=_QUOTES)
    strikes = [r["strike"] for r in rows]
    # ITM 90k call dropped (otm_only); puts ignored. Order: 110k (36.5%) >
    # 120k (24.3%) > 130k (15.2%).
    assert strikes == [110_000, 120_000, 130_000]
    assert rows[0]["annualized_yield_pct"] > rows[1]["annualized_yield_pct"]
    assert rows[0]["instrument_name"] == "BTC-30D-110k-C"
    # 30d 110k call: 3% static × 365/30.
    assert rows[0]["annualized_yield_pct"] == round(3.0 * 365 / 30, 2)


def test_rank_top_n_and_itm_inclusion() -> None:
    top1 = rank_covered_calls(spot=_SPOT, settlement="inverse", quotes=_QUOTES, top=1)
    assert len(top1) == 1 and top1[0]["strike"] == 110_000
    with_itm = rank_covered_calls(spot=_SPOT, settlement="inverse", quotes=_QUOTES, otm_only=False)
    assert 90_000 in [r["strike"] for r in with_itm]  # ITM call now included


def test_select_by_delta_picks_nearest() -> None:
    assert select_by_delta(quotes=_QUOTES, target_delta=0.25).strike == 120_000
    # 0.22 is closer to the 0.20 (60d/130k) leg than the 0.25 leg.
    assert select_by_delta(quotes=_QUOTES, target_delta=0.22).strike == 130_000
    # Put side selects among puts only.
    assert select_by_delta(quotes=_QUOTES, target_delta=0.30, kind="put").strike == 120_000


def test_select_by_delta_none_when_no_match() -> None:
    no_delta = [ChainQuote("X", "call", 1, 1, premium=0.1, delta=None)]
    assert select_by_delta(quotes=no_delta, target_delta=0.25) is None
