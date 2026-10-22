# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the tax-bracket-headroom / Roth-fill calculator."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import bracket_headroom


def test_single_in_22pct_bracket() -> None:
    # $100k gross, single -> taxable 83,900 (2026: 100,000 - 16,100 standard
    # deduction); 22% bracket runs 50,400 to 105,700 taxable.
    out = bracket_headroom(taxable_income=100_000.0, filing_status="single")
    assert out["taxableIncome"] == 83_900.0
    assert out["marginalRate"] == 0.22
    assert out["bracketFloor"] == 50_400.0
    assert out["bracketCeiling"] == 105_700.0
    assert out["roomToNextBracket"] == 21_800.0  # 2026: 105,700 - 83,900
    assert out["nextRate"] == 0.24
    assert out["taxTableYear"] == 2026
    assert out["taxTableVersion"] == "federal-income-tax-reference-2026-v2"


def test_reference_provenance_only_when_whole_table_is_reference() -> None:
    # Both inputs omitted -> the whole table is the IRS reference.
    full_ref = bracket_headroom(taxable_income=100_000.0, filing_status="single")
    assert full_ref["taxTableSource"].startswith("IRS Rev. Proc.")
    assert full_ref["taxTableLastVerified"] == "2026-10-22"
    assert full_ref["taxTableVersion"] == "federal-income-tax-reference-2026-v2"

    # A partial caller override (custom brackets, reference std deduction) makes
    # the effective table caller-modified — it must NOT claim the IRS source.
    partial = bracket_headroom(
        taxable_income=100_000.0,
        filing_status="single",
        brackets=[(50_000.0, 0.10), (float("inf"), 0.35)],
    )
    assert partial["taxTableSource"] == "caller_provided"
    assert partial["taxTableLastVerified"] is None
    assert partial["taxTableVersion"] == "caller-provided-unversioned"


def test_fill_to_target_rate() -> None:
    # Filling up to the 24% bracket ceiling (2026: 201,775 taxable).
    out = bracket_headroom(taxable_income=100_000.0, filing_status="single", target_rate=0.24)
    assert out["targetRate"] == 0.24
    # 2026: 201,775 - 83,900 taxable (100,000 - 16,100) = 117,875
    assert out["roomToTargetRate"] == 201_775.0 - 83_900.0


def test_top_bracket_has_no_ceiling() -> None:
    out = bracket_headroom(taxable_income=2_000_000.0, filing_status="single")
    assert out["marginalRate"] == 0.37
    assert out["bracketCeiling"] is None
    assert out["roomToNextBracket"] is None
    assert out["nextRate"] is None


def test_target_at_top_rate_is_unbounded() -> None:
    out = bracket_headroom(taxable_income=100_000.0, filing_status="single", target_rate=0.37)
    assert out["roomToTargetRate"] is None


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"taxable_income": -1.0, "filing_status": "single"}, "non-negative"),
        (
            {"taxable_income": 100.0, "filing_status": "single", "target_rate": 1.0},
            r"\[0, 1\)",
        ),
        (
            {"taxable_income": 100.0, "filing_status": "single", "year": 2027},
            "no reference federal tax table registered",
        ),
    ],
)
def test_validation(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        bracket_headroom(**kwargs)  # type: ignore[arg-type]
