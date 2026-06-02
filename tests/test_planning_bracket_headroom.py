# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the tax-bracket-headroom / Roth-fill calculator."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import bracket_headroom


def test_single_in_22pct_bracket() -> None:
    # $100k gross, single -> taxable 85,000; 22% bracket runs to 103,350 taxable.
    out = bracket_headroom(taxable_income=100_000.0, filing_status="single")
    assert out["taxableIncome"] == 85_000.0
    assert out["marginalRate"] == 0.22
    assert out["bracketFloor"] == 48_475.0
    assert out["bracketCeiling"] == 103_350.0
    assert out["roomToNextBracket"] == 18_350.0  # 103350 - 85000
    assert out["nextRate"] == 0.24


def test_fill_to_target_rate() -> None:
    # Filling up to the 24% bracket ceiling (197,300 taxable).
    out = bracket_headroom(
        taxable_income=100_000.0, filing_status="single", target_rate=0.24
    )
    assert out["targetRate"] == 0.24
    assert out["roomToTargetRate"] == 197_300.0 - 85_000.0


def test_top_bracket_has_no_ceiling() -> None:
    out = bracket_headroom(taxable_income=2_000_000.0, filing_status="single")
    assert out["marginalRate"] == 0.37
    assert out["bracketCeiling"] is None
    assert out["roomToNextBracket"] is None
    assert out["nextRate"] is None


def test_target_at_top_rate_is_unbounded() -> None:
    out = bracket_headroom(
        taxable_income=100_000.0, filing_status="single", target_rate=0.37
    )
    assert out["roomToTargetRate"] is None


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"taxable_income": -1.0, "filing_status": "single"}, "non-negative"),
        (
            {"taxable_income": 100.0, "filing_status": "single", "target_rate": 1.0},
            r"\[0, 1\)",
        ),
    ],
)
def test_validation(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        bracket_headroom(**kwargs)  # type: ignore[arg-type]
