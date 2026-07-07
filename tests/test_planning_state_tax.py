# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for illustrative state-tax planning rules."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import (
    StateResidencyChange,
    estimate_state_income_tax,
    estimate_state_income_tax_components,
    reference_state_tax_rule,
    state_code_for_year,
    state_tax_notes,
)
from nexus_core.engine.planning.tables import TableError


def test_no_income_tax_states_reduce_to_zero_state_tax() -> None:
    for code in ("AK", "FL", "NV", "SD", "TN", "TX", "WY", "NH", "WA"):
        rule = reference_state_tax_rule(code)
        assert rule is not None
        estimate = estimate_state_income_tax(
            rule,
            gross_income=100_000.0,
            age=45,
            source="earned_income",
        )
        assert estimate.tax == 0.0
        assert estimate.taxable_income == 100_000.0
        if code == "WA":
            assert "wa_capital_gains_excise_not_modeled" in rule.flags


def test_pa_and_il_retirement_exclusion_paths() -> None:
    pa = reference_state_tax_rule("PA")
    il = reference_state_tax_rule("IL")
    assert pa is not None
    assert il is not None

    pa_early = estimate_state_income_tax(
        pa,
        gross_income=80_000.0,
        age=50,
        source="traditional_distribution",
    )
    pa_retirement_age = estimate_state_income_tax(
        pa,
        gross_income=80_000.0,
        age=60,
        source="traditional_distribution",
    )
    il_any_age = estimate_state_income_tax(
        il,
        gross_income=80_000.0,
        age=45,
        source="traditional_distribution",
    )
    il_wages = estimate_state_income_tax(
        il,
        gross_income=80_000.0,
        age=45,
        source="earned_income",
    )

    assert pa_early.tax == pytest.approx(2_456.0)
    assert pa_retirement_age.tax == 0.0
    assert il_any_age.tax == 0.0
    assert il_wages.tax == pytest.approx(3_960.0)


def test_nj_exclusion_cliff_boundary() -> None:
    rule = reference_state_tax_rule("NJ")
    assert rule is not None

    at_cliff = estimate_state_income_tax(
        rule,
        gross_income=100_000.0,
        age=65,
        source="traditional_distribution",
        filing_status="single",
        total_income=150_000.0,
    )
    over_cliff = estimate_state_income_tax(
        rule,
        gross_income=100_000.0,
        age=65,
        source="traditional_distribution",
        filing_status="single",
        total_income=150_001.0,
    )

    assert at_cliff.exclusion == pytest.approx(18_750.0)
    assert over_cliff.exclusion == 0.0
    assert over_cliff.tax > at_cliff.tax


def test_ny_government_pension_and_shared_private_cap() -> None:
    rule = reference_state_tax_rule("NY")
    assert rule is not None

    government = estimate_state_income_tax(
        rule,
        gross_income=100_000.0,
        age=65,
        source="government_pension",
        filing_status="single",
        total_income=100_000.0,
    )
    private_components = estimate_state_income_tax_components(
        rule,
        [
            ("pension", "pension", 20_000.0),
            ("traditional", "traditional_distribution", 20_000.0),
        ],
        age=65,
        filing_status="single",
        total_income=40_000.0,
    )

    assert government.tax == 0.0
    assert sum(row.exclusion for row in private_components.values()) == pytest.approx(20_000.0)
    assert sum(row.tax for row in private_components.values()) == pytest.approx(1_370.0)


def test_bracketed_state_tax_uses_shared_bracket_not_per_component_zero_band() -> None:
    rule = reference_state_tax_rule("MS")
    assert rule is not None

    components = estimate_state_income_tax_components(
        rule,
        [("pension", "pension", 10_000.0), ("earned", "earned_income", 10_000.0)],
        age=50,
        filing_status="single",
        total_income=20_000.0,
    )
    incremental = estimate_state_income_tax_components(
        rule,
        [("traditional", "traditional_distribution", 10_000.0)],
        age=50,
        filing_status="single",
        total_income=20_000.0,
        baseline_taxable_income=10_000.0,
    )

    assert sum(row.tax for row in components.values()) == pytest.approx(440.0)
    assert incremental["traditional"].tax == pytest.approx(440.0)


def test_rule_notes_surface_caveats() -> None:
    rule = reference_state_tax_rule("WA")
    assert rule is not None
    estimates = estimate_state_income_tax_components(
        rule,
        [("gain", "taxable_gain", 100_000.0)],
        age=60,
        filing_status="single",
        total_income=100_000.0,
    )

    notes = state_tax_notes(rule, tuple(estimates.values()))
    assert any("capital-gains excise" in note for note in notes)


def test_residency_change_boundary() -> None:
    change = StateResidencyChange(year=2030, from_state="PA", to_state="FL")

    assert state_code_for_year(base_state="PA", residency_change=change, year=2029) == "PA"
    assert state_code_for_year(base_state="PA", residency_change=change, year=2030) == "FL"


def test_state_code_validation_rejects_address_like_values() -> None:
    with pytest.raises(TableError, match="two-letter"):
        state_code_for_year(base_state="Pennsylvania", residency_change=None, year=2026)
    with pytest.raises(TableError, match="two-letter"):
        StateResidencyChange(year=2027, from_state="Pennsylvania", to_state="FL")
