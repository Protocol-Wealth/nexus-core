# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the tax-aware withdrawal engine."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import (
    InfeasiblePlanError,
    StateResidencyChange,
    tax_aware_withdrawal,
)
from nexus_core.engine.planning.tax import ordinary_tax

_ACCOUNTS = [
    {"type": "taxable", "balance": 200000, "allocation": {"us_equity": 1.0}},
    {"type": "traditional", "balance": 800000, "allocation": {"us_equity": 0.6, "us_bonds": 0.4}},
    {"type": "roth", "balance": 300000, "allocation": {"us_equity": 1.0}},
]


def test_ordinary_tax_progressive_married_joint() -> None:
    # income 130000 - 30000 std ded = 100000 taxable:
    # 23850*.10 + (96950-23850)*.12 + (100000-96950)*.22 = 2385 + 8772 + 671 = 11828
    assert round(ordinary_tax(130_000, "married_joint")) == 11828


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
    assert r["taxTableVersion"] == "federal-income-tax-reference-2026-illustrative-v1"
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
