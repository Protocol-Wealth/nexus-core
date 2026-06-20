# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the goal-based funding engine."""

from __future__ import annotations

from typing import Any

import pytest

from nexus_core.engine.planning import analyze_goals


def _goal(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "g1",
        "kind": "education",
        "target_amount": 100_000.0,
        "years_to_goal": 10,
        "current_assets": 0.0,
        "monthly_contribution": 0.0,
    }
    base.update(overrides)
    return base


def test_single_goal_valid_structure() -> None:
    r = analyze_goals(goals=[_goal()])
    assert len(r["goals"]) == 1
    g = r["goals"][0]
    assert g["id"] == "g1"
    assert g["kind"] == "education"
    assert set(g) >= {
        "futureCost",
        "projectedResources",
        "fundedRatio",
        "fundedPct",
        "status",
        "shortfallFuture",
        "shortfallPresent",
        "requiredMonthlyContribution",
        "additionalMonthlyNeeded",
    }
    assert 0.0 <= g["fundedPct"] <= 100.0
    assert r["aggregate"]["goalCount"] == 1
    assert r["onTrackThreshold"] == pytest.approx(0.85)


def test_future_cost_inflates_present_target() -> None:
    # 100k today at 5% inflation over 10y = 100k * 1.05^10.
    g = analyze_goals(goals=[_goal(inflation_rate=0.05)])["goals"][0]
    assert g["futureCost"] == pytest.approx(100_000 * 1.05**10, abs=0.01)


def test_assets_equal_target_with_matched_rates_is_exactly_funded() -> None:
    # When the expected return == inflation and the earmarked assets == the
    # present cost, the goal is exactly 100% funded (growth tracks the cost).
    g = analyze_goals(
        goals=[_goal(current_assets=100_000.0, inflation_rate=0.05, expected_return=0.05)]
    )["goals"][0]
    assert g["fundedRatio"] == pytest.approx(1.0, rel=1e-6)
    assert g["status"] == "funded"
    assert g["onTrack"] is True
    assert g["shortfallFuture"] == pytest.approx(0.0, abs=1.0)


def test_multi_year_funding_cost_with_matched_rates() -> None:
    # 200k total over 4 disbursement years; with inflation == return the
    # discount-back cancels the extra inflation, so the cost equals the total
    # inflated to the goal start year: 200k * 1.05^10.
    g = analyze_goals(
        goals=[
            _goal(
                target_amount=200_000.0,
                funding_years=4,
                inflation_rate=0.05,
                expected_return=0.05,
            )
        ]
    )["goals"][0]
    assert g["fundingYears"] == 4
    assert g["futureCost"] == pytest.approx(200_000 * 1.05**10, abs=0.01)


def test_multi_year_costs_more_than_single_when_return_below_inflation() -> None:
    # Spreading the spend into the future (4 years out) costs MORE than a single
    # disbursement when the discount rate is below inflation.
    single = analyze_goals(
        goals=[_goal(target_amount=200_000.0, inflation_rate=0.06, expected_return=0.03)]
    )["goals"][0]["futureCost"]
    multi = analyze_goals(
        goals=[
            _goal(
                target_amount=200_000.0,
                funding_years=4,
                inflation_rate=0.06,
                expected_return=0.03,
            )
        ]
    )["goals"][0]["futureCost"]
    assert multi > single


def test_required_monthly_contribution_actually_funds() -> None:
    # Plugging requiredMonthlyContribution back in must yield a ~100% funded goal.
    base = _goal(target_amount=300_000.0, years_to_goal=18, current_assets=20_000.0)
    first = analyze_goals(goals=[base])["goals"][0]
    required = first["requiredMonthlyContribution"]
    assert required is not None and required > 0
    refunded = analyze_goals(goals=[{**base, "monthly_contribution": required}])["goals"][0]
    assert refunded["fundedRatio"] == pytest.approx(1.0, rel=1e-4)
    assert refunded["status"] == "funded"


def test_additional_monthly_needed_nets_existing_contribution() -> None:
    base = _goal(target_amount=300_000.0, years_to_goal=18, current_assets=20_000.0)
    g = analyze_goals(goals=[{**base, "monthly_contribution": 200.0}])["goals"][0]
    assert g["additionalMonthlyNeeded"] == pytest.approx(
        max(g["requiredMonthlyContribution"] - 200.0, 0.0), rel=1e-6
    )


def test_status_bands() -> None:
    # underfunded (<85%): assets far below need
    under = analyze_goals(goals=[_goal(current_assets=10_000.0)])["goals"][0]
    assert under["status"] == "underfunded"
    assert under["onTrack"] is False
    # on-track (>=85% and <100%): above the exposed threshold but not fully funded
    on_track_result = analyze_goals(
        goals=[
            _goal(
                current_assets=25_000.0,
                monthly_contribution=500.0,
                inflation_rate=0.03,
                expected_return=0.06,
            )
        ]
    )
    on_track = on_track_result["goals"][0]
    assert on_track["fundedRatio"] > on_track_result["onTrackThreshold"]
    assert on_track["fundedRatio"] < 1.0
    assert on_track["status"] == "on_track"
    assert on_track["onTrack"] is True
    # overfunded (>100%): assets above need → funded + a surplus
    over = analyze_goals(
        goals=[_goal(current_assets=300_000.0, inflation_rate=0.02, expected_return=0.06)]
    )["goals"][0]
    assert over["status"] == "funded"
    assert over["onTrack"] is True
    assert over["fundedRatio"] > 1.0
    assert over["fundedPct"] == 100.0  # clamped for the bar
    assert over["surplusFuture"] > 0.0


def test_goal_due_now_has_no_required_contribution() -> None:
    # years_to_goal == 0: nothing can be contributed; required/additional are null.
    g = analyze_goals(goals=[_goal(years_to_goal=0, current_assets=50_000.0)])["goals"][0]
    assert g["requiredMonthlyContribution"] is None
    assert g["additionalMonthlyNeeded"] is None
    assert g["futureCost"] == pytest.approx(100_000.0)  # no inflation applied at year 0


def test_defaults_applied_when_rates_omitted() -> None:
    g = analyze_goals(
        goals=[_goal()],
        default_inflation_rate=0.03,
        default_expected_return=0.07,
    )["goals"][0]
    assert g["inflationRate"] == pytest.approx(0.03)
    assert g["expectedReturn"] == pytest.approx(0.07)


def test_aggregate_present_value_rollup() -> None:
    two = analyze_goals(goals=[_goal(id="a"), _goal(id="b")])
    one = analyze_goals(goals=[_goal(id="a")])
    agg = two["aggregate"]
    assert agg["goalCount"] == 2
    # Two identical goals: the overall ratio equals each goal's ratio.
    assert agg["overallFundedRatio"] == pytest.approx(two["goals"][0]["fundedRatio"], rel=1e-6)
    # PV totals double.
    assert agg["presentValueOfGoals"] == pytest.approx(
        2 * one["aggregate"]["presentValueOfGoals"], rel=1e-6
    )
    assert agg["underfundedCount"] == 2


def test_empty_goals_is_a_valid_noop() -> None:
    r = analyze_goals(goals=[])
    assert r["goals"] == []
    assert r["aggregate"]["goalCount"] == 0
    assert r["aggregate"]["overallFundedRatio"] == pytest.approx(1.0)


def test_determinism() -> None:
    goals = [_goal(id="a", current_assets=25_000.0, monthly_contribution=400.0)]
    assert analyze_goals(goals=goals) == analyze_goals(goals=goals)


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "g", "target_amount": -1.0, "years_to_goal": 5},
        {"id": "g", "target_amount": 100.0, "years_to_goal": -1},
        {"id": "g", "target_amount": 100.0, "years_to_goal": 5, "funding_years": 0},
        {"id": "", "target_amount": 100.0, "years_to_goal": 5},
        {"id": "g", "target_amount": 100.0, "years_to_goal": 5, "current_assets": -5.0},
        {"id": "g", "target_amount": 100.0, "years_to_goal": 5, "expected_return": -1.0},
    ],
)
def test_invalid_goal_raises(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        analyze_goals(goals=[bad])


def test_duplicate_id_raises() -> None:
    with pytest.raises(ValueError, match="duplicate goal id"):
        analyze_goals(goals=[_goal(id="dup"), _goal(id="dup")])
