# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for regime-conditioned covered-call strike selection."""

from __future__ import annotations

import pytest

from nexus_core.engine.pricing.option_chain import ChainQuote
from nexus_core.engine.pricing.regime_overlay import (
    regime_adjusted_target_delta,
    regime_conditioned_overwrite,
)

_QUOTES = [
    ChainQuote("BTC-110k-C", "call", 110_000, 30, premium=0.02, delta=0.30),
    ChainQuote("BTC-120k-C", "call", 120_000, 30, premium=0.02, delta=0.20),
    ChainQuote("BTC-140k-C", "call", 140_000, 30, premium=0.02, delta=0.12),
]


def test_adjusted_delta_by_regime() -> None:
    # Crisis writes further OTM (lower delta); expansion writes closer.
    assert regime_adjusted_target_delta("crisis", 0.25) == (0.125, 0.50)
    assert regime_adjusted_target_delta("expansion", 0.25) == (0.30, 1.20)
    assert regime_adjusted_target_delta("inflationary", 0.25) == (0.25, 1.00)
    # Clamp to the OTM band ceiling.
    adjusted, mult = regime_adjusted_target_delta("expansion", 0.40)
    assert mult == 1.20
    assert adjusted == 0.45  # 0.40 × 1.2 = 0.48 -> clamped


def test_regime_tilts_the_strike_selection() -> None:
    # Same chain, different regime -> different strike. This is the differentiator.
    crisis = regime_conditioned_overwrite(
        regime="crisis", spot=100_000, settlement="inverse", quotes=_QUOTES
    )
    expansion = regime_conditioned_overwrite(
        regime="expansion", spot=100_000, settlement="inverse", quotes=_QUOTES
    )
    # Crisis target 0.125 -> the 0.12-delta 140k call (furthest OTM).
    assert crisis.adjusted_target_delta == 0.125
    assert crisis.selected["strike"] == 140_000
    # Expansion target 0.30 -> the 0.30-delta 110k call (closest, richest premium).
    assert expansion.adjusted_target_delta == 0.30
    assert expansion.selected["strike"] == 110_000
    # The covered-call illustration is attached and consistent.
    assert crisis.covered_call["annualized_yield_pct"] > 0
    assert "crisis" in crisis.rationale.lower()


def test_no_delta_quotes_yields_no_selection() -> None:
    out = regime_conditioned_overwrite(
        regime="crisis",
        spot=100_000,
        settlement="inverse",
        quotes=[ChainQuote("X", "call", 110_000, 30, premium=0.02, delta=None)],
    )
    assert out.selected is None
    assert out.covered_call is None
    assert any("delta" in n for n in out.notes)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"settlement": "x", "base_target_delta": 0.25}, "settlement"),
        ({"settlement": "inverse", "base_target_delta": 1.5}, "base_target_delta"),
    ],
)
def test_validation(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        regime_conditioned_overwrite(regime="crisis", spot=100_000, quotes=_QUOTES, **kwargs)  # type: ignore[arg-type]
