# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the tax-aware withdrawal engine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from nexus_core.engine.planning import (
    InfeasiblePlanError,
    StateResidencyChange,
    tax_aware_withdrawal,
)
from nexus_core.engine.planning.tax import (
    ltcg_tax,
    ordinary_brackets,
    ordinary_tax,
    standard_deduction,
)

_ACCOUNTS = [
    {"type": "taxable", "balance": 200000, "allocation": {"us_equity": 1.0}},
    {"type": "traditional", "balance": 800000, "allocation": {"us_equity": 0.6, "us_bonds": 0.4}},
    {"type": "roth", "balance": 300000, "allocation": {"us_equity": 1.0}},
]


def test_ordinary_tax_progressive_married_joint() -> None:
    # 2026: income 130,000 - 32,200 std ded = 97,800 taxable (below the 100,800 12% top):
    # 24,800*.10 + (97,800-24,800)*.12 = 2,480 + 8,760 = 11,240
    assert round(ordinary_tax(130_000, "married_joint")) == 11240


def test_ordering_taxable_first_when_young() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="married_joint",
        accounts=_ACCOUNTS,
        gross_need=120_000,
        age=65,
        other_taxable_income=0,
    )
    assert [w["type"] for w in r["withdrawals"]] == ["taxable"]  # age<73 ⇒ no RMD; taxable first
    assert r["withdrawals"][0]["gross"] == 120_000
    assert r["taxTableYear"] == 2026
    assert r["taxTableVersion"] == "federal-income-tax-reference-2026-v2"
    assert r["rmdSatisfied"] is True  # RMD = 0
    assert 0.0 <= r["effectiveRate"] <= 1.0


def test_roth_is_tax_free() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[{"type": "roth", "balance": 300000, "allocation": {"x": 1.0}}],
        gross_need=50_000,
        age=70,
        other_taxable_income=0,
    )
    assert r["withdrawals"][0]["type"] == "roth"
    assert r["withdrawals"][0]["tax"] == 0.0
    assert r["totalTax"] == 0.0


def test_rmd_enforced_at_73_plus() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[
            {"type": "traditional", "balance": 1_000_000, "allocation": {"x": 1.0}},
            {"type": "taxable", "balance": 500_000, "allocation": {"x": 1.0}},
        ],
        gross_need=10_000,
        age=80,
        other_taxable_income=0,
    )
    # RMD at 80 = 1,000,000 / 20.2 ≈ 49,505 — taken even though it exceeds the need.
    traditional = next(w for w in r["withdrawals"] if w["type"] == "traditional")
    assert traditional["gross"] > 49_000
    assert r["rmdSatisfied"] is True
    assert traditional["tax"] > 0  # ordinary income


def test_birth_year_policy_defers_rmd_for_1960_plus_cohort() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[
            {"type": "traditional", "balance": 1_000_000, "allocation": {"x": 1.0}},
            {"type": "taxable", "balance": 500_000, "allocation": {"x": 1.0}},
        ],
        gross_need=10_000,
        age=73,
        other_taxable_income=0,
        birth_year=1960,
    )
    assert r["rmdStartAge"] == 75
    assert r["withdrawals"][0]["type"] == "taxable"
    assert r["withdrawals"][0]["gross"] == 10_000
    assert r["rmdSatisfied"] is True


def test_birth_year_policy_enforces_rmd_at_75_for_1960_plus_cohort() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[
            {"type": "traditional", "balance": 1_000_000, "allocation": {"x": 1.0}},
            {"type": "taxable", "balance": 500_000, "allocation": {"x": 1.0}},
        ],
        gross_need=10_000,
        age=75,
        other_taxable_income=0,
        birth_year=1960,
    )
    traditional = next(w for w in r["withdrawals"] if w["type"] == "traditional")
    assert traditional["gross"] == round(1_000_000 / 24.6, 2)
    assert r["rmdStartAge"] == 75
    assert r["rmdSatisfied"] is True


def test_unregistered_tax_year_fails_closed() -> None:
    with pytest.raises(ValueError, match="no reference federal tax table registered"):
        tax_aware_withdrawal(
            year=2027,
            filing_status="single",
            accounts=[{"type": "taxable", "balance": 100_000, "allocation": {"x": 1.0}}],
            gross_need=10_000,
            age=65,
            other_taxable_income=0,
        )


def test_traditional_taxed_as_ordinary_income() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[{"type": "traditional", "balance": 500_000, "allocation": {"x": 1.0}}],
        gross_need=80_000,
        age=65,
        other_taxable_income=0,
    )
    trad = r["withdrawals"][0]
    assert trad["type"] == "traditional"
    assert trad["tax"] > 0
    assert r["totalTax"] == trad["tax"]


def test_state_tax_exposes_federal_and_state_split() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[{"type": "traditional", "balance": 500_000, "allocation": {"x": 1.0}}],
        gross_need=80_000,
        age=50,
        other_taxable_income=0,
        state="PA",
    )
    trad = r["withdrawals"][0]

    assert r["stateCode"] == "PA"
    assert r["stateTaxModeled"] is True
    assert r["stateTax"] == pytest.approx(2_456.0)
    assert r["taxTableSource"].startswith("IRS Rev. Proc.")
    assert r["taxTableLastVerified"] == "2026-10-22"
    assert r["stateTaxTableSource"].startswith("Pennsylvania Department")
    assert r["stateTaxTableLastVerified"] == "2026-07-08"
    assert trad["stateTax"] == pytest.approx(2_456.0)
    assert trad["federalTax"] > 0.0
    assert trad["tax"] == pytest.approx(trad["federalTax"] + trad["stateTax"])
    assert r["totalTax"] == pytest.approx(r["federalTax"] + r["stateTax"])


def test_state_tax_pa_retirement_age_excludes_traditional_distribution() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[{"type": "traditional", "balance": 500_000, "allocation": {"x": 1.0}}],
        gross_need=80_000,
        age=65,
        other_taxable_income=0,
        state="PA",
    )

    assert r["stateCode"] == "PA"
    assert r["stateTaxModeled"] is True
    assert r["stateTax"] == 0.0


def test_state_tax_residency_change_uses_projection_year() -> None:
    no_change = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[{"type": "traditional", "balance": 500_000, "allocation": {"x": 1.0}}],
        gross_need=50_000,
        age=50,
        other_taxable_income=0,
        state="PA",
        projection_year=2026,
    )
    changed = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[{"type": "traditional", "balance": 500_000, "allocation": {"x": 1.0}}],
        gross_need=50_000,
        age=50,
        other_taxable_income=0,
        state="PA",
        residency_change=StateResidencyChange(year=2027, from_state="PA", to_state="FL"),
        projection_year=2027,
    )

    assert no_change["stateCode"] == "PA"
    assert no_change["stateTax"] > 0.0
    assert changed["stateCode"] == "FL"
    assert changed["stateTax"] == 0.0


def test_bracketed_state_tax_stacks_on_other_income() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[{"type": "traditional", "balance": 100_000, "allocation": {"x": 1.0}}],
        gross_need=10_000,
        age=50,
        other_taxable_income=10_000,
        state="MS",
    )

    assert r["stateCode"] == "MS"
    assert r["stateTax"] == pytest.approx(440.0)
    assert r["withdrawals"][0]["stateTax"] == pytest.approx(440.0)


def test_state_tax_notes_include_rule_caveats() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[{"type": "taxable", "balance": 100_000, "allocation": {"x": 1.0}}],
        gross_need=20_000,
        age=60,
        other_taxable_income=0,
        state="WA",
    )

    assert r["stateTax"] == 0.0
    assert any("capital-gains excise" in note for note in r["stateTaxNotes"])


def test_unregistered_state_marks_state_tax_unmodeled() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[{"type": "traditional", "balance": 500_000, "allocation": {"x": 1.0}}],
        gross_need=50_000,
        age=50,
        other_taxable_income=0,
        state="CA",
    )

    assert r["stateCode"] == "CA"
    assert r["stateTaxModeled"] is False
    assert r["stateTax"] == 0.0
    assert "not modeled" in r["stateTaxNotes"][0]


def test_infeasible_when_need_exceeds_balances() -> None:
    with pytest.raises(InfeasiblePlanError):
        tax_aware_withdrawal(
            year=2026,
            filing_status="single",
            accounts=[{"type": "roth", "balance": 10_000, "allocation": {"x": 1.0}}],
            gross_need=50_000,
            age=65,
            other_taxable_income=0,
        )


def test_bad_filing_status_raises_value_error() -> None:
    with pytest.raises(ValueError, match="filingStatus"):
        tax_aware_withdrawal(
            year=2026,
            filing_status="nope",
            accounts=_ACCOUNTS,
            gross_need=1_000,
            age=65,
            other_taxable_income=0,
        )


# --- Decimal money path (#346) ------------------------------------------------


def test_ordinary_tax_zero_at_and_below_standard_deduction() -> None:
    deduction = standard_deduction("married_joint")
    assert deduction == 32_200.0
    assert ordinary_tax(deduction, "married_joint") == 0.0
    assert ordinary_tax(deduction - 1, "married_joint") == 0.0
    assert ordinary_tax(0, "married_joint") == 0.0


def test_ordinary_tax_at_10_percent_bracket_edges() -> None:
    # 2026 MFJ: std 32,200; 10% top at 24,800 taxable → income 57,000.
    assert ordinary_tax(57_000, "married_joint") == 2_480.0
    # One dollar into the 12% bracket.
    assert ordinary_tax(57_001, "married_joint") == 2_480.12
    # 2026 single: std 16,100; 10% top at 12,400 taxable → income 28,500.
    assert ordinary_tax(28_500, "single") == 1_240.0
    assert ordinary_tax(28_501, "single") == 1_240.12


def test_ordinary_tax_at_later_bracket_edges() -> None:
    # Single 12% top is 50,400 taxable → income 16,100 + 50,400 = 66,500.
    # 12,400*0.10 + (50,400-12,400)*0.12 = 1,240 + 4,560 = 5,800.
    assert ordinary_tax(66_500, "single") == 5_800.0
    # One dollar into the 22% bracket.
    assert ordinary_tax(66_501, "single") == 5_800.22
    # 22% top is 105,700 taxable → income 121,800.
    # 5,800 + (105,700-50,400)*0.22 = 5,800 + 12,166 = 17,966.
    assert ordinary_tax(121_800, "single") == 17_966.0
    assert ordinary_tax(121_801, "single") == 17_966.24


def test_ordinary_tax_quantizes_sub_cent_slice_half_even() -> None:
    # Income $0.05 over the MFJ standard deduction is a $0.005 tax (10% * 0.05),
    # which ROUND_HALF_EVEN quantizes to 0.00. $0.10 over is an exact cent.
    deduction = standard_deduction("married_joint")
    assert ordinary_tax(Decimal(str(deduction)) + Decimal("0.05"), "married_joint") == 0.0
    assert ordinary_tax(Decimal(str(deduction)) + Decimal("0.10"), "married_joint") == 0.01


def test_ordinary_tax_accepts_decimal_income() -> None:
    assert ordinary_tax(Decimal("130000"), "married_joint") == 11_240.0


def test_ordinary_tax_rejects_non_finite_income() -> None:
    with pytest.raises(ValueError, match="income must be a finite number"):
        ordinary_tax(True, "single")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="income must be a finite number"):
        ordinary_tax(float("nan"), "single")
    with pytest.raises(ValueError, match="income must be a finite number"):
        ordinary_tax(float("inf"), "single")


def test_standard_deduction_matches_published_table() -> None:
    assert standard_deduction("single") == 16_100.0
    assert standard_deduction("head_of_household") == 24_150.0


def test_ltcg_tax_zero_below_and_fifteen_at_zero_breakpoint() -> None:
    # Single 2026 0% LTCG top is 49,450; selection uses a strict `<`.
    assert ltcg_tax(10_000, 49_449.99, "single") == 0.0
    assert ltcg_tax(10_000, 49_450, "single") == 1_500.0
    assert ltcg_tax(10_000, 49_450.01, "single") == 1_500.0


def test_ltcg_tax_twenty_percent_at_fifteen_breakpoint() -> None:
    # Single 2026 15% LTCG top is 545,500.
    assert ltcg_tax(10_000, 545_499.99, "single") == 1_500.0
    assert ltcg_tax(10_000, 545_500, "single") == 2_000.0
    assert ltcg_tax(10_000, 545_500.01, "single") == 2_000.0


def test_ltcg_tax_zero_and_negative_gains() -> None:
    assert ltcg_tax(0, 100_000, "single") == 0.0
    assert ltcg_tax(-1, 100_000, "single") == 0.0


def test_ltcg_tax_quantizes_half_cents_even() -> None:
    # 1.15 * 0.15 = 0.1725 → 0.17; 10.05 * 0.15 = 1.5075 → 1.51.
    assert ltcg_tax(1.15, 50_000, "single") == 0.17
    assert ltcg_tax(Decimal("10.05"), 50_000, "single") == 1.51


def test_ordinary_brackets_still_expose_float_table() -> None:
    rows = ordinary_brackets("single")
    assert rows[0] == (12_400, 0.1)
    assert rows[-1][0] == float("inf")
    assert rows[-1][1] == 0.37


def test_tax_aware_withdrawal_accepts_decimal_need_and_balance() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[{"type": "roth", "balance": Decimal("300000"), "allocation": {"x": 1.0}}],
        gross_need=Decimal("50000"),
        age=70,
        other_taxable_income=Decimal("0"),
    )
    assert r["withdrawals"][0]["gross"] == 50_000.0
    assert r["totalTax"] == 0.0


def test_tax_aware_withdrawal_rmd_matches_decimal_cents() -> None:
    r = tax_aware_withdrawal(
        year=2026,
        filing_status="single",
        accounts=[
            {"type": "traditional", "balance": 1_000_000, "allocation": {"x": 1.0}},
            {"type": "taxable", "balance": 500_000, "allocation": {"x": 1.0}},
        ],
        gross_need=10_000,
        age=75,
        other_taxable_income=0,
        birth_year=1960,
    )
    traditional = next(w for w in r["withdrawals"] if w["type"] == "traditional")
    expected = float((Decimal("1000000") / Decimal("24.6")).quantize(Decimal("0.01")))
    assert traditional["gross"] == expected == 40_650.41
    assert r["rmdSatisfied"] is True
