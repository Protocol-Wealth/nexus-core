# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""risk_based_guardrails: probability-of-success spending guardrails.

Cases, stated before the code:

- G1 same engine: today's success equals monte_carlo_decumulation's success for the
  same body and seed (no second simulation).
- G2 known answer: with near-zero volatility the plan is funded exactly when the
  starting value covers the present value of the spending, so both triggers sit at
  that present value and the target spend is the annuity the portfolio buys.
- G3 below the lower guardrail: a high spend lands in ``below_lower`` and the
  adjustment is a cut that brings success back near the target.
- G4 triggers bracket the thresholds: the upper trigger is above the lower one and
  each confirmed success sits near its threshold.
- G5 validation: thresholds out of order, or Guyton-Klinger ``guardrails`` in the
  body, are refused with 400.
- G6 deterministic: the same request returns the same answer.
"""

from __future__ import annotations

from typing import Any

from tests.test_planning_gateway import _client

_BASE: dict[str, Any] = {
    "contractVersion": "0.1.0",
    "currentAge": 68,
    "retirementAge": 68,
    "horizonAge": 95,
    "accounts": [
        {
            "type": "traditional",
            "balance": 1_500_000,
            "allocation": {"us_equity": 0.6, "us_bonds": 0.4},
        },
        {"type": "taxable", "balance": 500_000, "allocation": {"us_equity": 0.6, "us_bonds": 0.4}},
    ],
    "assetClasses": [
        {"id": "us_equity", "expectedReturn": 0.07, "volatility": 0.16, "lambda": 0.35},
        {"id": "us_bonds", "expectedReturn": 0.03, "volatility": 0.05, "lambda": 0.10},
    ],
    "correlations": {"us_equity": {"us_bonds": 0.1}, "us_bonds": {"us_equity": 0.1}},
    "annualSpend": 110_000,
    "spendColaRate": 0.025,
    "guaranteedIncome": [
        {"label": "Social Security", "annualAmount": 40_000, "startAge": 70, "colaRate": 0.02}
    ],
    "returnModel": "multivariate_normal",
    "paths": 800,
}


def _post(tool: str, body: dict[str, Any]) -> Any:
    return _client().post(f"/mcp/tools/{tool}", json=body)


def _guardrails(**overrides: Any) -> dict[str, Any]:
    r = _post("risk_based_guardrails", {**_BASE, **overrides})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_g1_current_success_is_the_engine_success() -> None:
    out = _guardrails()
    mc = _post("monte_carlo_decumulation", {**_BASE, "seed": out["seedUsed"]})
    assert mc.status_code == 200, mc.text
    assert out["currentSuccess"] == round(mc.json()["successProbability"], 4)
    assert out["thresholds"] == {"upper": 0.9, "target": 0.8, "lower": 0.7}
    assert out["method"] == "probability_of_success_guardrails"


def test_g2_known_answer_near_zero_volatility() -> None:
    # Retired, 5 years, 100k/yr flat, 5% certain return, withdraw-then-grow:
    # funded iff balance >= sum_{t=0..4} 100000 / 1.05**t.
    pv = sum(100_000 / 1.05**t for t in range(5))
    body = {
        "contractVersion": "0.1.0",
        "currentAge": 70,
        "retirementAge": 70,
        "horizonAge": 75,
        "accounts": [{"type": "taxable", "balance": 500_000, "allocation": {"cash": 1.0}}],
        "assetClasses": [{"id": "cash", "expectedReturn": 0.05, "volatility": 1e-9, "lambda": 0.0}],
        "correlations": {},
        "annualSpend": 100_000,
        "spendColaRate": 0.0,
        "guaranteedIncome": [],
        "returnModel": "multivariate_normal",
        "paths": 200,
    }
    r = _post("risk_based_guardrails", body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["currentSuccess"] == 1.0
    assert out["zone"] == "above_upper"
    for side in ("upper", "lower"):
        value = out["triggers"][side]["portfolioValue"]
        assert abs(value - pv) / pv < 0.005, (side, value, pv)
    annuity = 500_000 / (pv / 100_000)
    spend = out["spendingAdjustment"]["annualSpend"]
    assert abs(spend - annuity) / annuity < 0.005, (spend, annuity)
    assert abs(out["spendingAdjustment"]["annualChange"] - (annuity - 100_000)) < 600


def test_g3_below_lower_gets_a_cut_back_to_target() -> None:
    out = _guardrails(annualSpend=190_000)
    assert out["currentSuccess"] < 0.7
    assert out["zone"] == "below_lower"
    adj = out["spendingAdjustment"]
    assert adj["feasible"] is True
    assert adj["annualChange"] < 0
    assert abs(adj["achievedSuccess"] - 0.8) <= 0.05


def test_g4_triggers_bracket_the_thresholds() -> None:
    out = _guardrails(thresholds={"upper": 0.95, "target": 0.85, "lower": 0.75})
    upper = out["triggers"]["upper"]
    lower = out["triggers"]["lower"]
    assert upper["portfolioValue"] > lower["portfolioValue"] > 0
    assert abs(upper["achievedSuccess"] - 0.95) <= 0.05
    assert abs(lower["achievedSuccess"] - 0.75) <= 0.05
    # More money at the upper trigger buys more spend at target than at the lower one.
    assert upper["spendingAtTarget"]["annualSpend"] > lower["spendingAtTarget"]["annualSpend"]


def test_g5_refuses_bad_thresholds_and_gk_rules() -> None:
    bad = _post("risk_based_guardrails", {**_BASE, "thresholds": {"upper": 0.7, "lower": 0.9}})
    assert bad.status_code == 400
    gk = _post("risk_based_guardrails", {**_BASE, "guardrails": {"band": 0.2}})
    assert gk.status_code == 400


def test_g6_deterministic() -> None:
    assert _guardrails() == _guardrails()


# ── Review of ccdd246 (accepted findings 1-4) ────────────────────────────────
# Cases, stated first:
#  F1a the reviewer's short-horizon case (age 92→95, $1M, $100k spend) solves the
#      real target spend above the old 25%-draw ceiling, never 250k "feasible".
#  F1b a 3-year known answer: the target spend is the annuity $500k buys over 3
#      years at 5% (about 174k), above the old ceiling.
#  F1c when the target is still met at the final ceiling, the answer is boundHit
#      and NOT feasible.
#  F2  paths above the tool cap, or an over-budget body, are refused with a
#      too_expensive 400; paths default to the cap when omitted.
#  F3  upper >= 1.0 and unknown threshold keys are refused, naming the key.
#  F4  an ltcShock and goals are echoed (ltcShockImpact, goalFunding) and named
#      in basis / inputsApplied; a plain body names nothing.


def _short_horizon(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "contractVersion": "0.1.0",
        "currentAge": 92,
        "retirementAge": 92,
        "horizonAge": 95,
        "accounts": [
            {
                "type": "taxable",
                "balance": 1_000_000,
                "allocation": {"us_equity": 0.6, "us_bonds": 0.4},
            }
        ],
        "assetClasses": _BASE["assetClasses"],
        "correlations": _BASE["correlations"],
        "annualSpend": 100_000,
        "spendColaRate": 0.0,
        "guaranteedIncome": [],
        "returnModel": "multivariate_normal",
        "paths": 800,
    }
    body.update(overrides)
    return body


def test_f1a_short_horizon_finds_the_real_spend() -> None:
    r = _post("risk_based_guardrails", _short_horizon())
    assert r.status_code == 200, r.text
    adj = r.json()["spendingAdjustment"]
    assert adj["boundHit"] is False
    assert adj["feasible"] is True
    assert adj["annualSpend"] > 300_000
    assert abs(adj["achievedSuccess"] - 0.8) <= 0.05


def test_f1b_three_year_known_answer() -> None:
    pv = sum(100_000 / 1.05**t for t in range(3))
    body = {
        "contractVersion": "0.1.0",
        "currentAge": 70,
        "retirementAge": 70,
        "horizonAge": 73,
        "accounts": [{"type": "taxable", "balance": 500_000, "allocation": {"cash": 1.0}}],
        "assetClasses": [{"id": "cash", "expectedReturn": 0.05, "volatility": 1e-9, "lambda": 0.0}],
        "correlations": {},
        "annualSpend": 100_000,
        "spendColaRate": 0.0,
        "guaranteedIncome": [],
        "returnModel": "multivariate_normal",
        "paths": 200,
    }
    r = _post("risk_based_guardrails", body)
    assert r.status_code == 200, r.text
    annuity = 500_000 / (pv / 100_000)
    spend = r.json()["spendingAdjustment"]["annualSpend"]
    assert annuity > 125_000  # above the old 25%-draw ceiling
    assert abs(spend - annuity) / annuity < 0.005, (spend, annuity)


def test_f1c_bound_hit_is_not_feasible(monkeypatch: Any) -> None:
    from nexus_core.app.planning import tools

    monkeypatch.setattr(tools, "_GUARDRAIL_CEILING_PROBES", 0)
    r = _post("risk_based_guardrails", _short_horizon())
    assert r.status_code == 200, r.text
    adj = r.json()["spendingAdjustment"]
    assert adj["boundHit"] is True
    assert adj["feasible"] is False


def test_f2_refuses_too_expensive_requests() -> None:
    over_paths = _post("risk_based_guardrails", {**_BASE, "paths": 50_000})
    assert over_paths.status_code == 400
    assert "too_expensive" in over_paths.text
    wide = {
        **_BASE,
        "currentAge": 20,
        "retirementAge": 20,
        "horizonAge": 120,
        "paths": 5000,
        "accounts": [
            {
                "type": "taxable",
                "balance": 2_000_000,
                "allocation": {f"a{i}": 1 / 7 for i in range(7)},
            }
        ],
        "assetClasses": [
            {"id": f"a{i}", "expectedReturn": 0.05, "volatility": 0.1, "lambda": 0.1}
            for i in range(7)
        ],
        "correlations": {},
    }
    over_budget = _post("risk_based_guardrails", wide)
    assert over_budget.status_code == 400
    assert "too_expensive" in over_budget.text
    body = {k: v for k, v in _BASE.items() if k != "paths"}
    ok = _post("risk_based_guardrails", body)
    assert ok.status_code == 200, ok.text
    assert ok.json()["pathsConfirm"] == 5000


def test_f3_refuses_upper_one_and_unknown_keys() -> None:
    one = _post(
        "risk_based_guardrails",
        {**_BASE, "thresholds": {"upper": 1.0, "target": 0.8, "lower": 0.7}},
    )
    assert one.status_code == 400
    typo = _post("risk_based_guardrails", {**_BASE, "thresholds": {"uper": 0.95}})
    assert typo.status_code == 400
    assert "uper" in typo.text


def test_f4_echoes_ltc_shock_and_goals() -> None:
    plain = _guardrails()
    assert plain["inputsApplied"] == []
    assert plain["basis"] == "static_spend_schedule_same_seed_engine"
    assert "ltcShockImpact" not in plain

    shocked = _guardrails(
        ltcShock={"onsetAge": 84, "annualCost": 120_000, "durationYears": 4, "costInflation": 0.04},
        goals=[{"id": "need-1", "tier": "need", "targetAmount": 80_000, "yearsToGoal": 2}],
    )
    assert shocked["inputsApplied"] == ["ltc_shock", "goal_funding"]
    assert "ltc_shock" in shocked["basis"] and "goal_funding" in shocked["basis"]
    impact = shocked["ltcShockImpact"]
    assert impact["withShockSuccessProbability"] == shocked["currentSuccess"]
    assert impact["baselineSuccessProbability"] >= impact["withShockSuccessProbability"]
    assert shocked["goalFunding"] is not None
    assert shocked["goalFundingSchedule"]
