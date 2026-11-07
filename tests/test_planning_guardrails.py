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
