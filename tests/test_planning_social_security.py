# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the Social Security claiming-age calculator."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import social_security_claiming


def test_known_factors_for_fra_67() -> None:
    out = social_security_claiming(pia_monthly=2_000.0, fra_age=67)
    by_age = {row["claimAge"]: row for row in out["byClaimAge"]}
    # 70% at 62, 100% at FRA, 124% at 70 (the well-known statutory anchors).
    assert by_age[62]["pctOfPia"] == 0.7
    assert by_age[62]["monthlyBenefit"] == 1_400.0
    assert by_age[67]["pctOfPia"] == 1.0
    assert by_age[67]["monthlyBenefit"] == 2_000.0
    assert by_age[70]["pctOfPia"] == 1.24
    assert by_age[70]["monthlyBenefit"] == 2_480.0
    # full 62..70 table
    assert len(out["byClaimAge"]) == 9
    assert by_age[70]["annualBenefit"] == 2_480.0 * 12


def test_breakeven_ages() -> None:
    out = social_security_claiming(pia_monthly=2_000.0, fra_age=67)
    be = {(b["earlier"], b["later"]): b["breakevenAge"] for b in out["breakevens"]}
    assert be[(62, 67)] == 78.7  # (2000*67 - 1400*62) / 600
    assert be[(67, 70)] == 82.5  # (2480*70 - 2000*67) / 480
    assert be[(62, 70)] == 80.4  # (2480*70 - 1400*62) / 1080


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"pia_monthly": 0.0}, "must be positive"),
        ({"pia_monthly": 2_000.0, "fra_age": 71}, r"\(62, 70\]"),
        ({"pia_monthly": 2_000.0, "fra_age": 62}, r"\(62, 70\]"),
    ],
)
def test_validation(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        social_security_claiming(**kwargs)  # type: ignore[arg-type]
