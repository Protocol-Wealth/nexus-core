# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Goal-based funding analysis (educational).

For each financial goal — education, a home down payment, a legacy/bequest, a
major purchase — answer the question an advisor's goal page asks: *given the
assets earmarked for this goal today, the ongoing contributions to it, and an
expected growth rate, what fraction of the goal's inflation-grown cost is on
track to be funded by its target date — and what monthly contribution would
fully fund it?*

Pure and deterministic — plain numbers in, plain data out; no simulation, no
market data, no client context. Each goal is funded independently from its own
earmarked assets and contribution stream (a shared-pool, priority-ordered
allocation across goals is a future enhancement). It is a planning illustration,
not a projection of any specific person's outcome, and not investment advice.

Math per goal (valued at the goal's start date, ``yearsToGoal`` from now):

* **Future cost** — ``targetAmount`` is the goal's TOTAL cost in today's dollars.
  A single-disbursement goal (``fundingYears == 1``) inflates it to the target
  date: ``targetAmount * (1 + i) ** yearsToGoal``. A multi-year goal (e.g. four
  years of college) spreads ``targetAmount`` evenly across ``fundingYears``
  disbursements, inflates each to its own calendar year, and discounts the later
  ones back to the goal-start year at the expected return — the lump needed at
  matriculation to fund the whole stream.
* **Projected resources** — the earmarked assets grown to the target date plus
  the future value of the (monthly) contribution stream (an ordinary annuity,
  monthly compounding).
* **Funded ratio** — ``projectedResources / futureCost`` (can exceed 1 =
  overfunded). ``fundedPct`` clamps it to [0, 100] for a progress bar.
* **Required monthly contribution** — the level monthly contribution that, with
  the earmarked assets, exactly funds the goal; ``additionalMonthlyNeeded`` is
  the gap above what's already being contributed.

The aggregate rolls the goals up in PRESENT-value terms (each goal discounted to
today at its own expected return), so a single "overall funded %" combines goals
at different horizons coherently.
"""

from __future__ import annotations

from typing import Any

#: DoS / sanity bounds for the public, unauthenticated surface.
_MAX_GOALS = 100
_MAX_YEARS_TO_GOAL = 100
_MAX_FUNDING_YEARS = 60

#: Funded-status bands (deterministic; not a probability). A goal at/above the
#: cost is ``funded``; within the on-track band it is ``on_track``; below it is
#: ``underfunded``. The threshold is exposed in the result so a consumer can
#: relabel without re-deriving it.
_ON_TRACK_RATIO = 0.85

#: Recognized goal kinds (free-form ``custom`` is always allowed). The engine
#: does not branch on kind — it is passed through for the consumer's grouping
#: and to keep the de-identified contract free of free-text labels.
GOAL_KINDS = (
    "retirement",
    "education",
    "home",
    "legacy",
    "major_purchase",
    "emergency_fund",
    "custom",
)


def _monthly_rate(annual_return: float) -> float:
    """Effective monthly rate equivalent to ``annual_return`` compounded yearly."""
    # float ** float is typed Any in typeshed (negative-base/complex overload);
    # the caller guarantees 1 + annual_return > 0, so coerce to a real float.
    return float((1.0 + annual_return) ** (1.0 / 12.0)) - 1.0


def _annuity_future_value_factor(monthly_rate: float, months: int) -> float:
    """FV factor of $1/month for ``months`` (ordinary annuity)."""
    if months <= 0:
        return 0.0
    if monthly_rate == 0.0:
        return float(months)
    return ((1.0 + monthly_rate) ** months - 1.0) / monthly_rate


def _future_cost(
    *,
    target_amount: float,
    years_to_goal: int,
    inflation_rate: float,
    expected_return: float,
    funding_years: int,
) -> float:
    """Inflation-grown cost of the goal valued at its start year.

    Single disbursement: the present cost inflated to ``years_to_goal``.
    Multi-year: ``target_amount`` split evenly across ``funding_years``, each
    slice inflated to its own calendar year then discounted back to the
    goal-start year at ``expected_return``.
    """
    if funding_years <= 1:
        return target_amount * (1.0 + inflation_rate) ** years_to_goal
    per_year = target_amount / funding_years
    total = 0.0
    for k in range(funding_years):
        inflated = per_year * (1.0 + inflation_rate) ** (years_to_goal + k)
        # Discount the slice back to the goal-start year (k years early).
        total += inflated / (1.0 + expected_return) ** k
    return total


def _analyze_one_goal(
    goal: dict[str, Any],
    *,
    default_inflation_rate: float,
    default_expected_return: float,
) -> dict[str, Any]:
    goal_id = goal["id"]
    kind = goal.get("kind", "custom")
    target_amount = float(goal["target_amount"])
    years_to_goal = int(goal["years_to_goal"])
    current_assets = float(goal.get("current_assets", 0.0))
    monthly_contribution = float(goal.get("monthly_contribution", 0.0))
    funding_years = int(goal.get("funding_years", 1))
    inflation_rate = (
        float(goal["inflation_rate"])
        if goal.get("inflation_rate") is not None
        else default_inflation_rate
    )
    expected_return = (
        float(goal["expected_return"])
        if goal.get("expected_return") is not None
        else default_expected_return
    )

    future_cost = _future_cost(
        target_amount=target_amount,
        years_to_goal=years_to_goal,
        inflation_rate=inflation_rate,
        expected_return=expected_return,
        funding_years=funding_years,
    )

    growth_factor = (1.0 + expected_return) ** years_to_goal
    months = years_to_goal * 12
    monthly_rate = _monthly_rate(expected_return)
    annuity_factor = _annuity_future_value_factor(monthly_rate, months)

    fv_current = current_assets * growth_factor
    fv_contributions = monthly_contribution * annuity_factor
    projected_resources = fv_current + fv_contributions

    # Funded ratio (can exceed 1.0 = overfunded). A zero-cost goal is fully funded.
    funded_ratio = projected_resources / future_cost if future_cost > 0 else 1.0
    funded_pct = max(0.0, min(funded_ratio, 1.0)) * 100.0

    shortfall_future = max(future_cost - projected_resources, 0.0)
    surplus_future = max(projected_resources - future_cost, 0.0)
    # Present value of the gap (discounted to today at the goal's expected return).
    shortfall_present = shortfall_future / growth_factor if growth_factor > 0 else shortfall_future

    if funded_ratio >= 1.0:
        status = "funded"
    elif funded_ratio >= _ON_TRACK_RATIO:
        status = "on_track"
    else:
        status = "underfunded"

    # Level monthly contribution that, with the earmarked assets already growing,
    # exactly funds the goal. None when there is no time to contribute (goal due
    # now) — the gap can only be closed by assets, not future contributions.
    needed_from_contributions = max(future_cost - fv_current, 0.0)
    required_monthly: float | None
    additional_monthly: float | None
    if annuity_factor > 0:
        required_monthly = needed_from_contributions / annuity_factor
        additional_monthly = max(required_monthly - monthly_contribution, 0.0)
    else:
        required_monthly = None
        additional_monthly = None

    return {
        "id": goal_id,
        "kind": kind,
        "yearsToGoal": years_to_goal,
        "fundingYears": funding_years,
        "inflationRate": round(inflation_rate, 6),
        "expectedReturn": round(expected_return, 6),
        "targetAmountToday": round(target_amount, 2),
        "futureCost": round(future_cost, 2),
        "projectedResources": round(projected_resources, 2),
        "projectedFromAssets": round(fv_current, 2),
        "projectedFromContributions": round(fv_contributions, 2),
        "fundedRatio": round(funded_ratio, 4),
        "fundedPct": round(funded_pct, 1),
        "status": status,
        "onTrack": funded_ratio >= 1.0,
        "shortfallFuture": round(shortfall_future, 2),
        "surplusFuture": round(surplus_future, 2),
        "shortfallPresent": round(shortfall_present, 2),
        "requiredMonthlyContribution": (
            round(required_monthly, 2) if required_monthly is not None else None
        ),
        "currentMonthlyContribution": round(monthly_contribution, 2),
        "additionalMonthlyNeeded": (
            round(additional_monthly, 2) if additional_monthly is not None else None
        ),
    }


def analyze_goals(
    *,
    goals: list[dict[str, Any]],
    default_inflation_rate: float = 0.025,
    default_expected_return: float = 0.05,
) -> dict[str, Any]:
    """Per-goal funding status + a present-value aggregate.

    Args:
        goals: De-identified goals. Each is a dict with an opaque ``id`` (str),
            ``target_amount`` (> 0, today's dollars), ``years_to_goal`` (int,
            >= 0), and optional ``kind`` (str), ``current_assets`` (>= 0),
            ``monthly_contribution`` (>= 0), ``funding_years`` (int >= 1),
            ``inflation_rate``, ``expected_return``. NO free-text label — the
            engine is identity-free; the consumer re-attaches labels by id.
        default_inflation_rate: Inflation for goals without an explicit rate.
        default_expected_return: Pre-goal growth rate for goals without one.

    Returns:
        ``goals`` (per-goal analysis, input order) + ``aggregate``
        (PV-weighted overall funded ratio, totals, status counts) +
        ``onTrackThreshold``.

    Raises:
        ValueError: on a malformed/out-of-range input (the gateway maps it to 400).
    """
    if not isinstance(goals, list):
        raise ValueError("goals must be a list")
    if len(goals) > _MAX_GOALS:
        raise ValueError(f"at most {_MAX_GOALS} goals are supported")
    if default_inflation_rate <= -1:
        raise ValueError("default_inflation_rate must be > -1")
    if default_expected_return <= -1:
        raise ValueError("default_expected_return must be > -1")

    seen_ids: set[str] = set()
    for index, goal in enumerate(goals):
        if not isinstance(goal, dict):
            raise ValueError(f"goals[{index}] must be an object")
        goal_id = goal.get("id")
        if not isinstance(goal_id, str) or not goal_id:
            raise ValueError(f"goals[{index}].id must be a non-empty string")
        if goal_id in seen_ids:
            raise ValueError(f"duplicate goal id '{goal_id}'")
        seen_ids.add(goal_id)
        target_amount = goal.get("target_amount")
        if (
            isinstance(target_amount, bool)
            or not isinstance(target_amount, (int, float))
            or target_amount < 0
        ):
            raise ValueError(f"goals[{index}].target_amount must be a non-negative number")
        years = goal.get("years_to_goal")
        if isinstance(years, bool) or not isinstance(years, int) or not 0 <= years <= _MAX_YEARS_TO_GOAL:
            raise ValueError(
                f"goals[{index}].years_to_goal must be an integer in [0, {_MAX_YEARS_TO_GOAL}]"
            )
        for opt_key in ("current_assets", "monthly_contribution"):
            value = goal.get(opt_key)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0
            ):
                raise ValueError(f"goals[{index}].{opt_key} must be a non-negative number")
        funding_years = goal.get("funding_years", 1)
        if (
            isinstance(funding_years, bool)
            or not isinstance(funding_years, int)
            or not 1 <= funding_years <= _MAX_FUNDING_YEARS
        ):
            raise ValueError(
                f"goals[{index}].funding_years must be an integer in [1, {_MAX_FUNDING_YEARS}]"
            )
        for rate_key in ("inflation_rate", "expected_return"):
            value = goal.get(rate_key)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float)) or value <= -1
            ):
                raise ValueError(f"goals[{index}].{rate_key} must be a number > -1")

    analyses = [
        _analyze_one_goal(
            goal,
            default_inflation_rate=default_inflation_rate,
            default_expected_return=default_expected_return,
        )
        for goal in goals
    ]

    # Aggregate in present-value terms so goals at different horizons combine
    # coherently into one "overall funded %".
    pv_cost_total = 0.0
    pv_resources_total = 0.0
    shortfall_present_total = 0.0
    status_counts = {"funded": 0, "on_track": 0, "underfunded": 0}
    for analysis, goal in zip(analyses, goals, strict=True):
        expected_return = (
            float(goal["expected_return"])
            if goal.get("expected_return") is not None
            else default_expected_return
        )
        years = int(goal["years_to_goal"])
        discount = (1.0 + expected_return) ** years
        pv_cost_total += analysis["futureCost"] / discount if discount > 0 else analysis["futureCost"]
        pv_resources_total += (
            analysis["projectedResources"] / discount if discount > 0 else analysis["projectedResources"]
        )
        shortfall_present_total += analysis["shortfallPresent"]
        status_counts[analysis["status"]] += 1

    overall_ratio = pv_resources_total / pv_cost_total if pv_cost_total > 0 else 1.0

    aggregate = {
        "goalCount": len(analyses),
        "overallFundedRatio": round(overall_ratio, 4),
        "overallFundedPct": round(max(0.0, min(overall_ratio, 1.0)) * 100.0, 1),
        "presentValueOfGoals": round(pv_cost_total, 2),
        "presentValueOfResources": round(pv_resources_total, 2),
        "totalShortfallPresent": round(shortfall_present_total, 2),
        "fundedCount": status_counts["funded"],
        "onTrackCount": status_counts["on_track"],
        "underfundedCount": status_counts["underfunded"],
    }

    return {
        "goals": analyses,
        "aggregate": aggregate,
        "onTrackThreshold": _ON_TRACK_RATIO,
    }


__all__ = ["GOAL_KINDS", "analyze_goals"]
