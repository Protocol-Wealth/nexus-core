# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the regime-conditioned safe-withdrawal-rate overlay."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import regime_conditioned_swr
from nexus_core.engine.planning.regime import GENERIC_REGIMES


def test_crisis_trims_the_rate() -> None:
    out = regime_conditioned_swr(regime="crisis", base_swr=0.04)
    assert out["regimeMultiplier"] == 0.75
    assert out["adjustedSwr"] == 0.03  # 0.04 * 0.75


def test_expansion_lifts_the_rate() -> None:
    out = regime_conditioned_swr(regime="expansion", base_swr=0.04)
    assert out["regimeMultiplier"] == 1.10
    assert out["adjustedSwr"] == 0.044


def test_first_year_withdrawal_when_balance_given() -> None:
    out = regime_conditioned_swr(
        regime="crisis", base_swr=0.04, portfolio_balance=1_000_000.0
    )
    assert out["firstYearWithdrawal"] == 30_000.0  # 1,000,000 * 0.03


def test_every_regime_has_a_multiplier() -> None:
    for regime in GENERIC_REGIMES:
        out = regime_conditioned_swr(regime=regime)
        assert out["adjustedSwr"] > 0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"regime": "boom"}, "regime must be one of"),
        ({"regime": "crisis", "base_swr": 0.0}, r"\(0, 1\)"),
        ({"regime": "crisis", "base_swr": 1.0}, r"\(0, 1\)"),
        (
            {"regime": "crisis", "portfolio_balance": -1.0},
            "portfolio_balance must be non-negative",
        ),
    ],
)
def test_validation(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        regime_conditioned_swr(**kwargs)  # type: ignore[arg-type]
