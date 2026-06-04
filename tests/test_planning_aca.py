# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the injected ACA premium-tax-credit cliff estimate (flag-with-magnitude)."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from nexus_core.app.planning.contract import find_identity_keys
from nexus_core.engine.planning import (
    analyze_roth_conversion,
    reference_aca_situation,
    reference_bracket_table,
    reference_irmaa_table,
)
from nexus_core.engine.planning.aca import aca_cliff_estimate, aca_ptc, applicable_pct
from nexus_core.engine.planning.case import PlanningContract
from nexus_core.engine.planning.tables import AcaSituation, TableError

# fpl = 15000 + 5000*(2-1) = 20000; 150% = 30000; 400% = 80000; cap 8.5%.
_S = AcaSituation(
    marketplace_enrolled=True,
    household_size=2,
    benchmark_premium_annual=18_000.0,
    fpl_base=15_000.0,
    fpl_per_person=5_000.0,
)
_S_CAPPED = AcaSituation(
    marketplace_enrolled=True,
    household_size=2,
    benchmark_premium_annual=18_000.0,
    fpl_base=15_000.0,
    fpl_per_person=5_000.0,
    cliff_mode="capped_8_5",
)


def test_fpl_and_applicable_pct() -> None:
    assert _S.fpl() == 20_000.0
    assert applicable_pct(1.0, _S) == 0.0  # below 150% FPL
    assert applicable_pct(4.0, _S) == pytest.approx(0.085)  # at 400%
    assert applicable_pct(2.75, _S) == pytest.approx(0.085 * 0.5)  # midpoint of 1.5..4.0


def test_aca_ptc_full_credit_at_low_income() -> None:
    assert aca_ptc(30_000.0, _S) == pytest.approx(18_000.0)  # 150% FPL -> 0% expected


def test_aca_ptc_at_400pct() -> None:
    # 80000 = 400% FPL: expected = 0.085 * 80000 = 6800 -> PTC = 18000 - 6800.
    assert aca_ptc(80_000.0, _S) == pytest.approx(11_200.0)


def test_hard_cliff_zeroes_ptc_above_400pct() -> None:
    assert aca_ptc(80_001.0, _S) == 0.0  # one dollar over -> $0 (hard cliff)


def test_capped_mode_has_no_hard_cliff() -> None:
    # 85000 (425% FPL), capped: expected = 0.085*85000 = 7225 -> PTC = 10775 (still > 0).
    assert aca_ptc(85_000.0, _S_CAPPED) == pytest.approx(10_775.0)


def test_cliff_estimate_detects_crossing_and_loss() -> None:
    est = aca_cliff_estimate(70_000.0, 85_000.0, _S)  # 350% -> 425% FPL, hard mode
    assert est.crosses_hard_cliff is True
    # before: applicable 0.085*0.8=0.068 -> expected 4760 -> ptc 13240; after: 0.
    assert est.ptc_before == pytest.approx(13_240.0)
    assert est.ptc_after == 0.0
    assert est.incremental_ptc_loss == pytest.approx(13_240.0)


def test_no_loss_when_already_above_range() -> None:
    est = aca_cliff_estimate(90_000.0, 120_000.0, _S)  # already > 400% before
    assert est.ptc_before == 0.0 and est.ptc_after == 0.0
    assert est.incremental_ptc_loss == 0.0


def test_situation_validation_and_from_dict() -> None:
    with pytest.raises(TableError, match="household_size"):
        AcaSituation(marketplace_enrolled=True, household_size=0, benchmark_premium_annual=1.0,
                     fpl_base=15_000.0, fpl_per_person=5_000.0)
    with pytest.raises(TableError, match="cliff_mode"):
        AcaSituation(marketplace_enrolled=True, household_size=1, benchmark_premium_annual=1.0,
                     fpl_base=15_000.0, fpl_per_person=5_000.0, cliff_mode="nope")
    s = AcaSituation.from_dict(
        {"marketplace_enrolled": True, "household_size": 3, "benchmark_premium_annual": 20000}
    )
    assert s.household_size == 3 and s.fpl_base == 15_060.0  # defaults applied


def test_reference_situation_state_fpl() -> None:
    assert reference_aca_situation(household_size=1, benchmark_premium_annual=12000).fpl() == 15_060.0
    assert reference_aca_situation(household_size=1, benchmark_premium_annual=12000, state_code="AK").fpl() == 18_810.0


# --- composite integration: injected ACA quantifies the note; absent = generic ---

_CONTRACT = {
    "case_id": "aca-1", "tax_year": 2026, "filing_status": "mfj", "state_code": "PA",
    "birth_years": [1962, 1963], "medicare_enrolled": 0,  # both < 65 in 2026
    "income_ex_conversion": {"pension": 40_000, "taxable_interest": 5_000},
    "accounts": {"trad_ira_aggregate": 1_400_000, "taxable_liquidity": 250_000},
    "intent": {"target_rule": "fill_to_rate", "target_rate": 0.24, "years": [2026]},
}


def _analyze(aca: AcaSituation | None):
    c = PlanningContract.from_dict(_CONTRACT)
    return analyze_roth_conversion(
        c,
        irmaa_table=reference_irmaa_table("married_joint"),
        bracket_table=reference_bracket_table(2026),
        aca=aca,
    )


def test_injected_aca_quantifies_the_year_note() -> None:
    aca = reference_aca_situation(household_size=2, benchmark_premium_annual=18_000.0)
    notes = _analyze(aca).years[0].notes
    aca_notes = [n for n in notes if n.startswith("ACA")]
    assert aca_notes, "expected a quantified ACA note"
    assert "FPL" in aca_notes[0]
    # the generic 'not modeled here' flag must be gone when quantified
    assert not any("not modeled here" in n for n in notes)


def test_absent_aca_leaves_generic_flag_and_null_struct() -> None:
    y = _analyze(None).years[0]
    assert any("not modeled here" in n for n in y.notes)
    assert y.aca is None  # structured field null when no situation injected


def test_injected_aca_populates_structured_field() -> None:
    y = _analyze(reference_aca_situation(household_size=2, benchmark_premium_annual=18_000.0)).years[0]
    assert y.aca is not None  # contract v1.1.0 structured AcaInteraction
    assert y.aca.cliff_mode == "hard_400fpl"
    assert y.aca.magi_pct_fpl_after >= y.aca.magi_pct_fpl_before
    assert y.aca.incremental_ptc_loss >= 0.0


def test_output_unchanged_serializable_and_identity_free_with_aca() -> None:
    res = _analyze(reference_aca_situation(household_size=2, benchmark_premium_annual=18_000.0))
    d = asdict(res)
    json.dumps(d, allow_nan=False)
    assert find_identity_keys(d) == []
