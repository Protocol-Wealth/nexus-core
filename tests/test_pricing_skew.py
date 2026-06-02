# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the call-side volatility skew (IV + vega by strike)."""

from __future__ import annotations

import pytest

from nexus_core.engine.pricing.option_chain import ChainQuote
from nexus_core.engine.pricing.skew import vol_skew

# spot 100k; a call wing with positive 25Δ skew (OTM calls richer than ATM).
_QUOTES = [
    ChainQuote("BTC-95k-C", "call", 95_000, 30, premium=0.08, delta=0.60, mark_iv=60.0),
    ChainQuote("BTC-100k-C", "call", 100_000, 30, premium=0.05, delta=0.50, mark_iv=58.0),
    ChainQuote("BTC-120k-C", "call", 120_000, 30, premium=0.02, delta=0.25, mark_iv=65.0),
    ChainQuote("BTC-140k-C", "call", 140_000, 30, premium=0.01, delta=0.12, mark_iv=70.0),
]


def test_vol_skew_hand_values() -> None:
    sk = vol_skew(spot=100_000, expiry_days=30, settlement="inverse", quotes=_QUOTES)
    assert sk.atm_strike == 100_000  # nearest to spot
    assert sk.atm_iv == 58.0
    assert sk.call_25d_strike == 120_000  # the 0.25-delta call
    assert sk.call_25d_iv == 65.0
    assert sk.skew_25d_pts == 7.0  # 65 − 58, positive -> OTM calls richer
    assert sk.richest_strike == 140_000  # highest-IV OTM call
    assert sk.richest_iv == 70.0
    assert [p.strike for p in sk.points] == [95_000, 100_000, 120_000, 140_000]
    # Vega is computed (positive) for every priced strike.
    assert all(p.vega is not None and p.vega > 0 for p in sk.points)
    assert any("OTM calls richer" in n for n in sk.notes)
    assert any("Inverse" in n for n in sk.notes)


def test_negative_skew_note() -> None:
    quotes = [
        ChainQuote("A", "call", 100_000, 30, premium=0.05, delta=0.50, mark_iv=70.0),
        ChainQuote("B", "call", 120_000, 30, premium=0.02, delta=0.25, mark_iv=60.0),
    ]
    sk = vol_skew(spot=100_000, expiry_days=30, settlement="linear", quotes=quotes)
    assert sk.skew_25d_pts == -10.0  # 60 − 70
    assert any("cheaper than ATM" in n for n in sk.notes)
    assert not any("Inverse" in n for n in sk.notes)  # linear -> no inverse caveat


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"settlement": "x", "quotes": _QUOTES}, "settlement"),
        ({"settlement": "inverse", "quotes": []}, "at least one call"),
    ],
)
def test_validation(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        vol_skew(spot=100_000, expiry_days=30, **kwargs)  # type: ignore[arg-type]
