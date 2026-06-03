# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the PlanningContract v1.0.0 case shape + its JSON-Schema.

Covers the three load-bearing invariants: round-trip parsing/validation, the
dataclass <-> JSON-Schema in-sync property, and PII-free-by-construction.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from nexus_core.app.planning.contract import find_identity_keys
from nexus_core.engine.planning.analysis import RothConversionAnalysis
from nexus_core.engine.planning.case import (
    PLANNING_CONTRACT_VERSION,
    AccountBalances,
    ConversionIntent,
    IncomeExConversion,
    PlanningContract,
    PlanningContractError,
    engine_filing_status,
    planning_contract_schema,
)
from nexus_core.engine.planning.result_schema import roth_conversion_analysis_schema


def _valid_payload() -> dict[str, object]:
    """A representative 60-something MFJ retiree converting over 2026+2027."""
    return {
        "case_id": "case-opaque-001",
        "tax_year": 2026,
        "filing_status": "mfj",
        "state_code": "PA",
        "birth_years": [1962, 1963],
        "medicare_enrolled": 0,
        "income_ex_conversion": {
            "pension": 30_000,
            "social_security_gross": 48_000,
            "taxable_interest": 5_000,
            "tax_exempt_interest": 8_000,
            "ordinary_dividends": 12_000,
            "qualified_dividends": 9_000,
            "long_term_gains": 10_000,
            "itemized_or_standard": "standard",
        },
        "accounts": {
            "trad_ira_aggregate": 1_400_000,
            "nondeductible_basis": 70_000,
            "roth_balance": 200_000,
            "first_roth_year": 2015,
            "taxable_liquidity": 250_000,
        },
        "intent": {
            "target_rule": "fill_to_irmaa_tier",
            "years": [2026, 2027],
            "purpose": "tax_smoothing",
        },
    }


def test_round_trip_valid_contract() -> None:
    contract = PlanningContract.from_dict(_valid_payload())
    assert contract.contract_version == PLANNING_CONTRACT_VERSION
    assert contract.engine_filing_status == "married_joint"
    assert contract.state_code == "PA"
    assert contract.ages_in(2026) == (64, 63)
    assert contract.intent.target_rule == "fill_to_irmaa_tier"
    assert isinstance(contract.income_ex_conversion, IncomeExConversion)
    assert isinstance(contract.accounts, AccountBalances)
    assert isinstance(contract.intent, ConversionIntent)


def test_state_code_is_uppercased_and_validated() -> None:
    payload = _valid_payload()
    payload["state_code"] = "tx"
    assert PlanningContract.from_dict(payload).state_code == "TX"
    payload["state_code"] = "Pennsylvania"
    with pytest.raises(PlanningContractError, match="state_code"):
        PlanningContract.from_dict(payload)


def test_filing_status_mapping() -> None:
    assert engine_filing_status("single") == "single"
    assert engine_filing_status("mfj") == "married_joint"
    assert engine_filing_status("mfs") == "married_separate"


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p.update(filing_status="hoh"), "filing_status"),
        (lambda p: p.update(unexpected="x"), "unknown contract field"),
        (lambda p: p.update(tax_year=1999), "tax_year"),
        (lambda p: p.__setitem__("birth_years", [1962, 1963, 1964]), "birth_years"),
        (lambda p: (p.update(filing_status="single"), p.__setitem__("birth_years", [1962, 1963])), "single"),
        (lambda p: p.update(medicare_enrolled=3), "medicare_enrolled"),
        (lambda p: p["accounts"].update(nondeductible_basis=2_000_000), "nondeductible_basis"),
        (lambda p: p["income_ex_conversion"].update(qualified_dividends=99_000), "qualified_dividends"),
        (lambda p: p["intent"].update(target_rule="fill_to_rate", target_rate=None), "target_rate"),
        (lambda p: p["intent"].__setitem__("years", [2027, 2028]), "tax_year"),
        # unknown nested keys are rejected (PII-smuggling hole + schema drift)
        (lambda p: p["accounts"].update(account_number="x123"), "unknown accounts field"),
        (lambda p: p["income_ex_conversion"].update(magi=1), "unknown income_ex_conversion field"),
        (lambda p: p["intent"].update(note="Bob"), "unknown intent field"),
        # non-finite numbers must not pass the < 0 checks
        (lambda p: p["accounts"].update(trad_ira_aggregate=float("nan")), "finite"),
        (lambda p: p["income_ex_conversion"].update(wages=float("inf")), "finite"),
        # tax_year must be the earliest year
        (lambda p: (p.__setitem__("tax_year", 2027), p["intent"].__setitem__("years", [2026, 2027])), "FIRST"),
        # mfj requires two birth years
        (lambda p: p.__setitem__("birth_years", [1962]), "mfj"),
        # conflicting target params are rejected, not silently ignored
        (lambda p: p["intent"].update(fixed_amount=50_000), "fixed_amount is not used"),
    ],
)
def test_validation_rejects_bad_input(mutate, match: str) -> None:
    payload = _valid_payload()
    mutate(payload)
    with pytest.raises(PlanningContractError, match=match):
        PlanningContract.from_dict(payload)


@pytest.mark.parametrize("bad", ["1.2.3.4", "1.0.0-rc1", "1.0.0 ", "1.0", "v1.0.0"])
def test_loose_version_strings_rejected(bad: str) -> None:
    payload = _valid_payload()
    payload["contract_version"] = bad
    with pytest.raises(PlanningContractError, match="semver|major"):
        PlanningContract.from_dict(payload)


def test_major_version_mismatch_is_rejected() -> None:
    payload = _valid_payload()
    payload["contract_version"] = "2.0.0"
    with pytest.raises(PlanningContractError, match="major"):
        PlanningContract.from_dict(payload)


def test_itemized_deduction_accepted() -> None:
    payload = _valid_payload()
    payload["income_ex_conversion"]["itemized_or_standard"] = 41_000
    contract = PlanningContract.from_dict(payload)
    assert contract.income_ex_conversion.itemized_or_standard == 41_000.0


def test_fixed_amount_rule_requires_amount() -> None:
    payload = _valid_payload()
    payload["intent"] = {"target_rule": "fixed_amount", "years": [2026]}
    with pytest.raises(PlanningContractError, match="fixed_amount"):
        PlanningContract.from_dict(payload)


# --- dataclass <-> JSON-Schema in-sync ------------------------------------


def test_schema_matches_dataclass_fields() -> None:
    schema = planning_contract_schema()
    assert schema["title"] == "PlanningContract"
    top = set(schema["properties"])
    assert top == {f.name for f in fields(PlanningContract)}

    income = set(schema["properties"]["income_ex_conversion"]["properties"])
    assert income == {f.name for f in fields(IncomeExConversion)}

    accounts = set(schema["properties"]["accounts"]["properties"])
    assert accounts == {f.name for f in fields(AccountBalances)}

    intent = set(schema["properties"]["intent"]["properties"])
    assert intent == {f.name for f in fields(ConversionIntent)}


def test_schema_required_is_a_subset_of_properties() -> None:
    schema = planning_contract_schema()
    assert set(schema["required"]) <= set(schema["properties"])
    accounts = schema["properties"]["accounts"]
    assert set(accounts["required"]) <= set(accounts["properties"])


# --- PII-free by construction ---------------------------------------------

_FORBIDDEN = ("name", "firstname", "lastname", "dob", "dateofbirth", "ssn", "email", "phone", "address")


def _all_field_names() -> set[str]:
    names: set[str] = set()
    for dc in (PlanningContract, IncomeExConversion, AccountBalances, ConversionIntent):
        names |= {f.name for f in fields(dc)}
    return names


def test_no_identity_field_names_in_contract() -> None:
    for fname in _all_field_names():
        normalized = fname.replace("_", "")
        assert normalized not in _FORBIDDEN, f"identity-shaped field name: {fname}"


def test_valid_contract_passes_the_gateway_pii_tripwire() -> None:
    # The same fail-closed scanner the planning gateway runs must not trip on a
    # well-formed contract (it would, on any identity-shaped key).
    assert find_identity_keys(_valid_payload()) == []


# --- output shape: generated schema is well-formed + identity-free ---------


def _property_names(schema: dict[str, object]) -> set[str]:
    """All property names anywhere in a JSON-Schema (recursive)."""
    names: set[str] = set()
    props = schema.get("properties")
    if isinstance(props, dict):
        for key, sub in props.items():
            names.add(key)
            if isinstance(sub, dict):
                names |= _property_names(sub)
    for nested_key in ("items", "anyOf"):
        node = schema.get(nested_key)
        if isinstance(node, dict):
            names |= _property_names(node)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, dict):
                    names |= _property_names(item)
    return names


def test_output_schema_matches_top_level_dataclass() -> None:
    schema = roth_conversion_analysis_schema()
    assert schema["title"] == "RothConversionAnalysis"
    assert set(schema["properties"]) == {f.name for f in fields(RothConversionAnalysis)}


def test_output_schema_has_no_identity_property_names() -> None:
    names = _property_names(roth_conversion_analysis_schema())
    assert names, "generator produced an empty schema"
    for name in names:
        normalized = name.replace("_", "")
        assert normalized not in _FORBIDDEN, f"identity-shaped output field: {name}"
