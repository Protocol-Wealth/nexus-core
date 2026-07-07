# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the composite analyze_roth_conversion + sequence_conversions."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import pytest

from nexus_core.app.planning.contract import find_identity_keys
from nexus_core.engine.planning import (
    analyze_roth_conversion,
    reference_bracket_table,
    reference_irmaa_table,
    reference_state_rule,
    sequence_conversions,
)
from nexus_core.engine.planning.case import PlanningContract

_BASE: dict[str, Any] = {
    "case_id": "c1",
    "tax_year": 2026,
    "filing_status": "mfj",
    "state_code": "PA",
    "birth_years": [1962, 1963],
    "medicare_enrolled": 2,
    "income_ex_conversion": {
        "pension": 30_000,
        "social_security_gross": 48_000,
        "taxable_interest": 5_000,
        "tax_exempt_interest": 8_000,
        "ordinary_dividends": 12_000,
        "qualified_dividends": 9_000,
        "long_term_gains": 10_000,
    },
    "accounts": {
        "trad_ira_aggregate": 1_400_000,
        "nondeductible_basis": 0,
        "roth_balance": 200_000,
        "taxable_liquidity": 250_000,
    },
    "intent": {"target_rule": "fill_to_irmaa_tier", "years": [2026, 2027]},
}


def _contract(**overrides: Any) -> PlanningContract:
    payload = json.loads(json.dumps(_BASE))  # deep copy
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(payload.get(key), dict):
            payload[key].update(value)
        else:
            payload[key] = value
    return PlanningContract.from_dict(payload)


def _run(contract: PlanningContract, *, state: str | None = "auto") -> Any:
    fs = contract.engine_filing_status
    rule = reference_state_rule(contract.state_code) if state == "auto" else None
    return analyze_roth_conversion(
        contract,
        irmaa_table=reference_irmaa_table(fs),
        bracket_table=reference_bracket_table(2026),
        state_rule=rule,
        bracket_table_source="engine_reference",
        irmaa_table_source="engine_reference",
        state_rule_source="engine_reference",
    )


def test_irmaa_binds_for_a_60s_mfj_retiree() -> None:
    res = _run(_contract())
    y = res.years[0]
    assert y.binding_constraint == "irmaa"
    assert (
        "Federal tax table version: federal-income-tax-reference-2026-illustrative-v1."
        in res.assumptions
    )
    assert (
        "IRMAA table version: irmaa-reference-2025-married_joint-illustrative-v1."
        in res.assumptions
    )
    assert y.irmaa_ceiling is not None
    assert y.recommended_amount == pytest.approx(y.irmaa_ceiling, abs=2.0)
    assert y.bracket_ceiling is None  # fill_to_irmaa with no target_rate → bracket non-binding


def test_binding_ceiling_is_the_min_of_bracket_and_irmaa() -> None:
    # fill_to_rate at 24% — bracket room is large, IRMAA is the smaller ceiling.
    res = _run(
        _contract(intent={"target_rule": "fill_to_rate", "target_rate": 0.24, "years": [2026]})
    )
    y = res.years[0]
    assert y.bracket_ceiling is not None and y.irmaa_ceiling is not None
    assert y.binding_ceiling == pytest.approx(min(y.bracket_ceiling, y.irmaa_ceiling), abs=2.0)
    assert y.binding_constraint == "irmaa"


def test_bracket_binds_when_no_one_is_on_medicare() -> None:
    # A pre-Medicare single filer: nobody on Medicare in the target year → IRMAA
    # does not bind, the bracket does.
    res = _run(
        _contract(
            filing_status="single",
            birth_years=[1975],
            medicare_enrolled=0,
            intent={"target_rule": "fill_to_rate", "target_rate": 0.22, "years": [2026]},
        )
    )
    y = res.years[0]
    assert y.irmaa_ceiling is None
    assert y.binding_constraint == "bracket"
    assert y.recommended_amount == pytest.approx(y.bracket_ceiling, abs=2.0)


def test_liquidity_gate_reduces_the_recommendation() -> None:
    res = _run(_contract(accounts={"taxable_liquidity": 8_000}))
    y = res.years[0]
    assert y.liquidity.gated is True
    assert y.binding_constraint == "liquidity"
    assert y.liquidity.total_tax_due <= 8_000 + 1.0
    assert y.recommended_amount < y.binding_ceiling


def test_pro_rata_splits_basis() -> None:
    res = _run(_contract(accounts={"nondeductible_basis": 140_000}))  # 10% basis
    y = res.years[0]
    assert y.pro_rata.applies is True
    assert y.pro_rata.taxable_fraction == pytest.approx(0.9, abs=0.01)
    assert y.pro_rata.taxable_portion == pytest.approx(y.recommended_amount * 0.9, rel=0.01)
    assert y.pro_rata.basis_recovered > 0.0


def test_no_basis_means_pro_rata_does_not_apply() -> None:
    y = _run(_contract()).years[0]
    assert y.pro_rata.applies is False
    assert y.pro_rata.taxable_fraction == 1.0


def test_two_year_sequence_splits_and_draws_down_balance() -> None:
    res = _run(_contract())
    assert len(res.years) == 2
    assert len(res.sequence.recommended_by_year) == 2
    assert res.sequence.total_recommended == pytest.approx(sum(res.sequence.recommended_by_year))
    assert res.sequence.residual_trad_balance < _BASE["accounts"]["trad_ira_aggregate"]
    # sequence_conversions returns the same roll-up.
    summary = sequence_conversions(
        _contract(),
        irmaa_table=reference_irmaa_table("married_joint"),
        bracket_table=reference_bracket_table(2026),
        state_rule=reference_state_rule("PA"),
    )
    assert summary.recommended_by_year == res.sequence.recommended_by_year


def test_fixed_amount_rule() -> None:
    res = _run(
        _contract(intent={"target_rule": "fixed_amount", "fixed_amount": 50_000, "years": [2026]})
    )
    y = res.years[0]
    assert y.recommended_amount == pytest.approx(50_000.0, abs=2.0)
    assert y.binding_constraint == "fixed_amount"


def test_output_is_serializable_and_identity_free() -> None:
    res = _run(_contract())
    d = asdict(res)
    json.dumps(d, allow_nan=False)  # no NaN/Infinity, fully serializable
    assert find_identity_keys(d) == []  # no identity-shaped keys in the output


def test_employer_plan_balance_folds_into_rmd_drag() -> None:
    # contract v1.1.0: employer_plan_aggregate adds to the do-nothing RMD pool.
    without = _run(_contract()).do_nothing
    with_401k = _run(_contract(accounts={"employer_plan_aggregate": 600_000})).do_nothing
    assert with_401k.employer_plan_aggregate == 600_000.0
    assert with_401k.projected_trad_balance_at_rmd > without.projected_trad_balance_at_rmd
    assert with_401k.first_year_rmd > without.first_year_rmd


def test_survivor_compression_rate_for_mfj() -> None:
    # contract v1.1.0: mfj reports the surviving-spouse single-filing RMD rate.
    mfj = _run(_contract()).do_nothing
    assert mfj.survivor_first_year_rmd_marginal_rate is not None
    # single brackets are ~half-width → survivor rate >= the joint rate.
    assert mfj.survivor_first_year_rmd_marginal_rate >= mfj.first_year_rmd_marginal_rate
    single = _run(
        _contract(filing_status="single", birth_years=[1962], medicare_enrolled=1)
    ).do_nothing
    assert single.survivor_first_year_rmd_marginal_rate is None  # no joint→single transition


def test_do_nothing_rmd_start_age_by_birth_year() -> None:
    born_1962 = _run(_contract())  # born 1960+ → 75
    assert born_1962.do_nothing.rmd_start_age == 75
    born_1955 = _run(_contract(birth_years=[1955, 1956]))  # born before 1960 → 73
    assert born_1955.do_nothing.rmd_start_age == 73
    assert born_1955.do_nothing.first_year_rmd > 0.0


def test_state_treatment_pa_exempt_vs_flat_vs_unmodeled() -> None:
    pa = _run(_contract(state_code="PA")).years[0]
    assert (
        pa.state_tax.modeled is True and pa.state_tax.incremental_state_tax == 0.0
    )  # exempt past 59

    co = _run(_contract(state_code="CO")).years[0]
    assert co.state_tax.modeled is True and co.state_tax.incremental_state_tax > 0.0

    unmodeled = _run(_contract(), state=None).years[0]
    assert unmodeled.state_tax.modeled is False
    assert unmodeled.state_tax.incremental_state_tax == 0.0
