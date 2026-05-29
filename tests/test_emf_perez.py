# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic tests for EMF Check 5 — Perez Phase."""

from __future__ import annotations

from nexus_core.engine.scoring import CheckResult, ScoringContext
from nexus_core.engine.scoring.emf.perez import (
    PEREZ_FRENZY_LATE,
    PEREZ_FRENZY_START,
    PerezPhaseCheck,
    compute_perez_phase,
    normalize_phase,
)


def _ctx(**fundamentals: object) -> ScoringContext:
    return ScoringContext(ticker="TEST", fundamentals=dict(fundamentals))


# --------------------------------------------------------------------------
# normalize_phase — substring mapping mirrors pw-nexus _check_perez_cycle
# --------------------------------------------------------------------------


def test_normalize_phase_canonical_tokens() -> None:
    assert normalize_phase("Late Installation") == "Installation"
    assert normalize_phase("Early Deployment") == "Deployment"
    assert normalize_phase("Mature Deployment") == "Deployment"
    assert normalize_phase("Synergy") == "Deployment"
    assert normalize_phase("Frenzy") == "Frenzy"
    assert normalize_phase("Turning Point") == "Turning Point"


def test_normalize_phase_unrecognized_and_empty() -> None:
    assert normalize_phase("Unclassified") is None
    assert normalize_phase("") is None
    assert normalize_phase(None) is None


# --------------------------------------------------------------------------
# compute_perez_phase — capex vs revenue growth model
# --------------------------------------------------------------------------


def test_compute_installation_capex_outpaces_revenue() -> None:
    # capex +25% (under frenzy gates), revenue +10% -> capex_growth > rev_growth.
    inc = [{"revenue": 110.0}, {"revenue": 100.0}]
    cf = [{"capitalExpenditure": -125.0}, {"capitalExpenditure": -100.0}]
    assert compute_perez_phase(inc, cf) == "Installation"


def test_compute_deployment_revenue_outpaces_capex() -> None:
    # revenue +10%, capex flat -> rev_growth >= capex_growth, low frenzy.
    inc = [{"revenue": 110.0}, {"revenue": 100.0}]
    cf = [{"capitalExpenditure": -100.0}, {"capitalExpenditure": -100.0}]
    assert compute_perez_phase(inc, cf) == "Deployment"


def test_compute_frenzy_high_score() -> None:
    # capex +100% (>0.3, >0.5, > rev), revenue +60% (>0.2, >0.4):
    # score = 0.3 + 0.2 + 0.2 + 0.15 + 0.15 = 1.0 > PEREZ_FRENZY_LATE -> Frenzy.
    inc = [{"revenue": 160.0}, {"revenue": 100.0}]
    cf = [{"capitalExpenditure": -200.0}, {"capitalExpenditure": -100.0}]
    assert compute_perez_phase(inc, cf) == "Frenzy"


def test_compute_uses_plural_capex_key() -> None:
    # MBOUM-style "capitalExpenditures" (plural) and {"raw": ...} wrapped values.
    inc = [{"totalRevenue": {"raw": 110.0}}, {"totalRevenue": {"raw": 100.0}}]
    cf = [
        {"capitalExpenditures": {"raw": -125.0}},
        {"capitalExpenditures": {"raw": -100.0}},
    ]
    assert compute_perez_phase(inc, cf) == "Installation"


def test_compute_insufficient_statements() -> None:
    assert compute_perez_phase([{"revenue": 100.0}], [{"capitalExpenditure": -10.0}]) is None
    assert compute_perez_phase(None, None) is None
    assert compute_perez_phase([{"revenue": 100.0}, {"revenue": 90.0}], None) is None


def test_compute_capex_missing_undeterminable() -> None:
    inc = [{"revenue": 110.0}, {"revenue": 100.0}]
    cf = [{"capitalExpenditure": 0.0}, {"capitalExpenditure": 0.0}]
    assert compute_perez_phase(inc, cf) is None


def test_frenzy_thresholds_match_pw_nexus() -> None:
    assert PEREZ_FRENZY_START == 0.65
    assert PEREZ_FRENZY_LATE == 0.80


# --------------------------------------------------------------------------
# PerezPhaseCheck — verdict (pass / fail / missing)
# --------------------------------------------------------------------------


def test_check_shape() -> None:
    check = PerezPhaseCheck()
    result = check(_ctx(perez_phase="Installation"))
    assert isinstance(result, CheckResult)
    assert result.check_number == 5
    assert result.name == "Perez Phase"
    assert result.threshold == "Installation or Deployment"
    assert result.value is None  # pw-nexus reports phase via details, not value


def test_pass_explicit_installation() -> None:
    result = PerezPhaseCheck()(_ctx(perez_phase="Late Installation"))
    assert result.passed is True
    assert result.signal == "favorable"
    assert result.details["current_phase"] == "Installation"


def test_pass_explicit_deployment() -> None:
    result = PerezPhaseCheck()(_ctx(perez_phase="Mature Deployment"))
    assert result.passed is True
    assert result.details["current_phase"] == "Deployment"


def test_fail_frenzy() -> None:
    result = PerezPhaseCheck()(_ctx(perez_phase="Frenzy"))
    assert result.passed is False
    assert result.signal == "elevated_risk"
    assert result.details["current_phase"] == "Frenzy"


def test_fail_turning_point() -> None:
    result = PerezPhaseCheck()(_ctx(perez_phase="Turning Point"))
    assert result.passed is False
    assert result.details["current_phase"] == "Turning Point"


def test_infrastructure_layer_override_frenzy_to_installation() -> None:
    # L1-L3 Frenzy reading is reclassified to Installation and passes.
    result = PerezPhaseCheck()(_ctx(perez_phase="Frenzy", layer="L2"))
    assert result.passed is True
    assert result.details["current_phase"] == "Installation"
    assert result.details["infrastructure_override"] is True


def test_no_override_for_application_layer() -> None:
    # L5 Frenzy stays Frenzy and fails (override only applies to L1-L3).
    result = PerezPhaseCheck()(_ctx(perez_phase="Frenzy", layer="L5"))
    assert result.passed is False
    assert result.details["current_phase"] == "Frenzy"
    assert "infrastructure_override" not in result.details


def test_dynamic_fallback_when_no_explicit_phase() -> None:
    inc = [{"revenue": 110.0}, {"revenue": 100.0}]
    cf = [{"capitalExpenditure": -125.0}, {"capitalExpenditure": -100.0}]
    result = PerezPhaseCheck()(_ctx(income_statements=inc, cash_flows=cf))
    assert result.passed is True
    assert result.details["current_phase"] == "Installation"


def test_missing_data_returns_none() -> None:
    result = PerezPhaseCheck()(_ctx())
    assert result.passed is None
    assert result.value is None
    assert result.signal == "insufficient_data"
    assert result.details["current_phase"] == "N/A"


def test_unclassified_phase_string_returns_none() -> None:
    # An explicit but unrecognized phase with no statements -> insufficient_data.
    result = PerezPhaseCheck()(_ctx(perez_phase="Unclassified"))
    assert result.passed is None
    assert result.signal == "insufficient_data"


def test_phase_from_extra_when_absent_in_fundamentals() -> None:
    ctx = ScoringContext(ticker="TEST", extra={"perez_phase": "Deployment"})
    result = PerezPhaseCheck()(ctx)
    assert result.passed is True
    assert result.details["current_phase"] == "Deployment"


def test_compute_accepts_snake_case_capex() -> None:
    """The nexus-core SEC fetcher emits snake_case 'capital_expenditure'."""
    inc = [{"revenue": 110.0}, {"revenue": 100.0}]
    cf = [{"capital_expenditure": -125.0}, {"capital_expenditure": -100.0}]
    assert compute_perez_phase(inc, cf) == "Installation"


def test_compute_dynamic_phase_from_sec_shaped_statements() -> None:
    """SEC-fetcher field names compute a real phase (capex +50% > revenue +5.3%)."""
    inc = [{"fiscal_year": 2024, "revenue": 1000.0}, {"fiscal_year": 2023, "revenue": 950.0}]
    cf = [
        {"fiscal_year": 2024, "operating_cash_flow": 200.0, "capital_expenditure": 90.0},
        {"fiscal_year": 2023, "operating_cash_flow": 180.0, "capital_expenditure": 60.0},
    ]
    assert compute_perez_phase(inc, cf) == "Installation"
