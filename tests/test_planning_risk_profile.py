# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the risk-profile questionnaire scorer."""

from __future__ import annotations

import jsonschema
import pytest

from nexus_core.app.planning.contract import PlanningInputError, find_identity_keys
from nexus_core.app.planning.tools import risk_profile_score_tool
from nexus_core.engine.planning import (
    RISK_QUESTIONS,
    risk_profile_result_schema,
    risk_profile_score,
)


def _answers(answer_id: str) -> dict[str, str]:
    return {question.id: answer_id for question in RISK_QUESTIONS}


def _minimum_answers() -> dict[str, str]:
    return {
        "time_horizon": "under_3_years",
        "withdrawal_timing": "now",
        "drawdown_tolerance": "sell_at_5",
        "income_stability": "unstable",
        "liquidity_need": "high",
        "investing_experience": "none",
        "inflation_priority": "preserve_principal",
        "risk_capacity": "limited",
        "reaction_to_volatility": "sell",
        "goal_flexibility": "inflexible",
    }


def _maximum_answers() -> dict[str, str]:
    return {
        "time_horizon": "15_plus_years",
        "withdrawal_timing": "7_plus_years",
        "drawdown_tolerance": "add_at_30",
        "income_stability": "very_stable",
        "liquidity_need": "very_low",
        "investing_experience": "advanced",
        "inflation_priority": "high_growth",
        "risk_capacity": "high",
        "reaction_to_volatility": "buy",
        "goal_flexibility": "very_flexible",
    }


def test_risk_profile_minimum_and_maximum_profiles() -> None:
    conservative = risk_profile_score(_minimum_answers())
    aggressive = risk_profile_score(_maximum_answers())

    assert conservative["score"] == 0
    assert conservative["profile"] == "conservative"
    assert aggressive["score"] == aggressive["maxScore"] == 40
    assert aggressive["profile"] == "aggressive"
    assert sum(aggressive["suggestedWeights"].values()) == pytest.approx(1.0)
    assert aggressive["assumptions"]["optimizerField"] == "riskProfile"
    assert "illustrative model results" in aggressive["disclaimer"]


def test_risk_profile_band_edges() -> None:
    low = _minimum_answers()
    low.update(
        {
            "time_horizon": "15_plus_years",
            "withdrawal_timing": "7_plus_years",
            "drawdown_tolerance": "add_at_30",
            "income_stability": "very_stable",
        }
    )
    high = dict(low)
    high["liquidity_need"] = "moderate"

    assert risk_profile_score(low)["score"] == 16
    assert risk_profile_score(low)["profile"] == "moderate_conservative"
    assert risk_profile_score(high)["score"] == 17
    assert risk_profile_score(high)["profile"] == "moderate"


def test_risk_profile_rejects_missing_unknown_and_bad_answers() -> None:
    missing = _minimum_answers()
    missing.pop("time_horizon")
    with pytest.raises(ValueError, match="missing required"):
        risk_profile_score(missing)
    with pytest.raises(ValueError, match="unknown question"):
        risk_profile_score({**_minimum_answers(), "nickname": "test"})
    with pytest.raises(ValueError, match="answers.time_horizon"):
        risk_profile_score({**_minimum_answers(), "time_horizon": "forever"})


def test_risk_profile_tool_and_schema() -> None:
    body = risk_profile_score_tool({"contractVersion": "0.1.0", "answers": _maximum_answers()})
    wire_body = {"contractVersion": "0.1.0", **body}
    schema = risk_profile_result_schema()

    assert schema["$id"].endswith("risk-profile-result-0.1.0.json")
    assert body["profile"] == "aggressive"
    jsonschema.validate(instance=wire_body, schema=schema)


def test_risk_profile_tool_rejects_extra_fields_and_identity_keys_are_detectable() -> None:
    with pytest.raises(PlanningInputError, match="only accepts"):
        risk_profile_score_tool({"answers": _minimum_answers(), "notes": "too much"})
    assert find_identity_keys({"answers": {"name": "Jane"}}) == ["name"]
