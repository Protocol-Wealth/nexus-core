# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the Monte Carlo decumulation engine."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from nexus_core.engine.planning import GuardrailParams, monte_carlo_decumulation
from nexus_core.engine.planning.monte_carlo import _T_DOF, _portfolio_returns, _wilson_interval
from nexus_core.engine.planning.regime import GENERIC_REGIMES

_MODELS = (
    "multivariate_normal",
    "student_t",
    "block_bootstrap",
    "markov_regime",
    "emf_regime",
)


def _net_spend(years: int = 50) -> list[float]:
    # §5.2 default: $120k @ 2.5% COLA, less Social Security $42k @ 67 (2% COLA).
    out = []
    for y in range(years):
        age = 45 + y
        spend = 120_000 * (1.025**y)
        ss = 42_000 * (1.02 ** (age - 67)) if age >= 67 else 0.0
        out.append(spend - ss)
    return out


def _run(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "years": 50,
        "weights": [0.64, 0.36],
        "means": [0.07, 0.03],
        "vols": [0.16, 0.05],
        "lambdas": [0.35, 0.10],
        "correlation": [[1.0, 0.2], [0.2, 1.0]],
        "initial_balance": 1_500_000.0,
        "net_spend_by_year": _net_spend(),
        "return_model": "emf_regime",
        "paths": 3000,
        "seed": 12345,
        "regime_seed": 12345,
        "current_regime": "expansion",
    }
    base.update(overrides)
    return monte_carlo_decumulation(**base)


def test_default_scenario_valid_structure() -> None:
    # The §5.2 default is an 8% withdrawal from age 45 — aggressive; here we only
    # assert a valid distribution shape (its "plausibility" is a flagged spec
    # question re: retirementAge). See test_sustainable_scenario_non_degenerate.
    r = _run()
    assert 0.0 <= r["successProbability"] <= 1.0
    tv = r["terminalValues"]
    assert set(tv) == {"p10", "p25", "p50", "p75", "p90"}
    assert tv["p10"] <= tv["p25"] <= tv["p50"] <= tv["p75"] <= tv["p90"]  # monotone
    assert r["worstPathTerminal"] >= 0.0
    ci = r["successProbabilityConfidenceInterval"]
    assert ci["method"] == "wilson"
    assert ci["paths"] == 3000
    assert ci["lower"] <= r["successProbability"] <= ci["upper"]
    assert set(r["depletionStats"]) == {
        "failedPathCount",
        "failedPathProbability",
        "depletionYearPercentiles",
    }
    assert r["firstDecadeReturnVsOutcome"]["years"] == 10
    assert r["runManifest"]["paths"] == 3000
    assert r["runManifest"]["seed"] == 12345
    assert r["runManifest"]["manifestVersion"] == "monte_carlo_run_manifest_0.1.0"
    assert r["runManifest"]["engineVersion"] == "0.1.0"
    assert len(r["runManifest"]["assumptionsHash"]) == 64
    assert r["runManifest"]["successProbabilityCiMaxReportHalfWidth"] == 0.015
    assert isinstance(r["runManifest"]["successProbabilityCiWithinReportTolerance"], bool)


def test_wilson_interval_stays_well_behaved_near_boundary() -> None:
    ci = _wilson_interval(successes=9, total=10)
    assert ci["lower"] == pytest.approx(0.5958, abs=0.0001)
    assert ci["upper"] == pytest.approx(0.9821, abs=0.0001)
    assert ci["lower"] < 0.9 < ci["upper"]


def test_sustainable_scenario_non_degenerate() -> None:
    # A ~4% withdrawal is sustainable: the engine must yield surviving upside paths.
    r = _run(
        net_spend_by_year=[60_000 * (1.025**y) for y in range(50)],
        return_model="multivariate_normal",
    )
    assert r["successProbability"] > 0.0
    assert r["terminalValues"]["p90"] > 0.0


def test_depletion_age_stats_when_current_age_supplied() -> None:
    r = _run(
        current_age=60,
        years=35,
        initial_balance=425_287.0,
        net_spend_by_year=[100_000 * (1.025**y) for y in range(35)],
        return_model="multivariate_normal",
    )
    stats = r["depletionStats"]
    assert stats["failedPathCount"] > 0
    assert 0.0 < stats["failedPathProbability"] <= 1.0
    assert set(stats["depletionYearPercentiles"]) == {"p10", "p50", "p90"}
    assert set(stats["depletionAgePercentiles"]) == {"p10", "p50", "p90"}
    assert stats["depletionAgePercentiles"]["p50"] >= 60
    assert r["firstDecadeReturnVsOutcome"]["failedMedianAnnualReturn"] is not None
    curve = r["depletionCurve"]
    assert len(curve) == 35
    assert curve[0]["age"] == 60
    assert [row["depletionProbability"] for row in curve] == sorted(
        row["depletionProbability"] for row in curve
    )
    assert curve[-1]["depletionProbability"] == stats["failedPathProbability"]
    shortfall = r["conditionalShortfall"]
    assert shortfall["failedPathCount"] == stats["failedPathCount"]
    assert shortfall["p90"] >= shortfall["p50"] >= 0.0


def test_success_probability_stays_failed_after_depletion_revival() -> None:
    r = _run(
        years=3,
        weights=[1.0],
        means=[0.0],
        vols=[0.0],
        lambdas=[0.0],
        correlation=[[1.0]],
        initial_balance=100.0,
        net_spend_by_year=[150.0, -200.0, 0.0],
        return_model="multivariate_normal",
        paths=100,
        seed=20260707,
        regime_seed=20260707,
        current_regime="expansion",
        current_age=70,
    )
    assert r["terminalValues"]["p50"] == 200.0
    assert r["successProbability"] == 0.0
    assert r["successProbabilityConfidenceInterval"]["successes"] == 0
    assert r["depletionStats"]["failedPathProbability"] == 1.0
    assert [row["depletionProbability"] for row in r["depletionCurve"]] == [1.0, 1.0, 1.0]
    assert all(
        row["successProbability"] == 0.0 for row in r["firstDecadeReturnVsOutcome"]["deciles"]
    )


def test_median_balance_length_equals_horizon_minus_current() -> None:
    assert len(_run(years=50)["medianBalanceByYear"]) == 50
    assert len(_run(years=30, net_spend_by_year=_net_spend(30))["medianBalanceByYear"]) == 30


def test_balance_percentiles_by_year_is_a_valid_fan() -> None:
    # The projection fan: p10..p90 balance bands at each year, monotone per year,
    # one value per horizon year, and the p50 band == medianBalanceByYear.
    r = _run(years=30, net_spend_by_year=_net_spend(30))
    bands = r["balancePercentilesByYear"]
    assert set(bands) == {"p10", "p25", "p50", "p75", "p90"}
    for key in bands:
        assert len(bands[key]) == 30
    for y in range(30):
        assert (
            bands["p10"][y]
            <= bands["p25"][y]
            <= bands["p50"][y]
            <= bands["p75"][y]
            <= bands["p90"][y]
        )
    assert bands["p50"] == r["medianBalanceByYear"]


def test_first_decade_deciles_cover_all_paths_in_return_order() -> None:
    r = _run(return_model="multivariate_normal")
    deciles = r["firstDecadeReturnVsOutcome"]["deciles"]
    assert len(deciles) == 10
    assert sum(row["pathCount"] for row in deciles) == 3000
    assert deciles[0]["medianAnnualReturn"] <= deciles[-1]["medianAnnualReturn"]
    for row in deciles:
        assert 0.0 <= row["successProbability"] <= 1.0


def test_conditional_shortfall_is_empty_when_no_paths_fail() -> None:
    r = _run(
        initial_balance=10_000_000.0,
        net_spend_by_year=[10_000.0] * 20,
        years=20,
        return_model="multivariate_normal",
    )
    assert r["depletionStats"]["failedPathCount"] == 0
    assert r["conditionalShortfall"] == {
        "basis": "cumulative_unmet_portfolio_withdrawal_nominal",
        "failedPathCount": 0,
        "p50": None,
        "p90": None,
        "mean": 0.0,
    }


def test_determinism_same_seed_identical() -> None:
    assert _run(seed=99, regime_seed=99) == _run(seed=99, regime_seed=99)


def test_all_return_models_produce_valid_output() -> None:
    for model in _MODELS:
        r = _run(return_model=model)
        assert 0.0 <= r["successProbability"] <= 1.0
        assert len(r["medianBalanceByYear"]) == 50
        assert r["seedUsed"] == 12345


def test_student_t_model_matches_target_covariance() -> None:
    means = np.array([0.07, 0.03])
    vols = np.array([0.16, 0.05])
    correlation = np.array([[1.0, 0.2], [0.2, 1.0]])
    cov = np.outer(vols, vols) * correlation
    paths = 200_000
    years = 1
    seed = 20260707

    asset_0 = _portfolio_returns(
        model="student_t",
        means=means,
        cov=cov,
        weights=np.array([1.0, 0.0]),
        paths=paths,
        years=years,
        rng=np.random.default_rng(seed),
    ).reshape(paths)
    asset_1 = _portfolio_returns(
        model="student_t",
        means=means,
        cov=cov,
        weights=np.array([0.0, 1.0]),
        paths=paths,
        years=years,
        rng=np.random.default_rng(seed),
    ).reshape(paths)

    empirical = np.cov(np.column_stack([asset_0, asset_1]), rowvar=False, ddof=1)
    assert empirical[0, 0] == pytest.approx(cov[0, 0], rel=0.06)
    assert empirical[1, 1] == pytest.approx(cov[1, 1], rel=0.06)
    assert empirical[0, 1] == pytest.approx(cov[0, 1], rel=0.10, abs=0.0001)


def test_unscaled_student_t_shape_matrix_would_inflate_variance() -> None:
    target_var = 0.16**2
    paths = 200_000
    rng = np.random.default_rng(20260707)
    normal = rng.multivariate_normal(np.zeros(1), np.array([[target_var]]), size=(paths, 1))
    chi2 = rng.chisquare(_T_DOF, size=(paths, 1, 1)) / _T_DOF
    old_unscaled = normal[:, 0, 0] / np.sqrt(chi2[:, 0, 0])

    inflation = float(np.var(old_unscaled, ddof=1) / target_var)
    assert inflation == pytest.approx(_T_DOF / (_T_DOF - 2.0), rel=0.08)


def test_regime_summary_only_for_regime_aware_models() -> None:
    for model in ("emf_regime", "markov_regime"):
        summary = _run(return_model=model)["regimePathSummary"]
        assert len(summary) == 50
        assert all(r in GENERIC_REGIMES for r in summary)
    for model in ("multivariate_normal", "student_t", "block_bootstrap"):
        assert _run(return_model=model)["regimePathSummary"] == []


def test_emf_starts_path_at_current_regime() -> None:
    summary = _run(return_model="emf_regime", current_regime="crisis")["regimePathSummary"]
    assert summary[0] == "crisis"


# ── Guyton-Klinger dynamic withdrawals (guardrails) ──────────────────────────


def _stressed(**overrides: Any) -> dict[str, Any]:
    # A stressed 6% initial withdrawal, no accumulation, deterministic MVN model:
    # static spending runs the portfolio down; guardrails should cut to preserve it.
    base: dict[str, Any] = {
        "years": 30,
        "current_age": 65,
        "initial_balance": 1_000_000.0,
        "net_spend_by_year": [60_000 * (1.025**y) for y in range(30)],
        "means": [0.05, 0.03],
        "vols": [0.16, 0.05],
        "return_model": "multivariate_normal",
        "paths": 4000,
        "seed": 4242,
        "regime_seed": 4242,
    }
    base.update(overrides)
    return _run(**base)


def test_guardrails_absent_is_unchanged() -> None:
    # Omitting guardrails (or passing None) is byte-identical + carries no GK fields.
    static = _stressed()
    explicit_none = _stressed(guardrails=None)
    assert static == explicit_none
    assert "withdrawalRule" not in static
    assert "spendingByYear" not in static
    assert "guardrailActivity" not in static
    assert "guardrailStats" not in static


def test_guardrails_add_spending_and_activity_fields() -> None:
    r = _stressed(guardrails=GuardrailParams())
    assert r["withdrawalRule"] == "guyton_klinger"
    spend = r["spendingByYear"]
    assert set(spend) == {"p10", "p50", "p90"}
    assert len(spend["p10"]) == 30
    activity = r["guardrailActivity"]
    assert set(activity) == {"pathsWithCut", "pathsWithRaise", "band", "cut", "raise"}
    assert 0.0 <= activity["pathsWithCut"] <= 1.0
    assert 0.0 <= activity["pathsWithRaise"] <= 1.0
    stats = r["guardrailStats"]
    assert set(stats) == {
        "cutCountPercentiles",
        "raiseCountPercentiles",
        "pathsWithMultipleCuts",
        "firstCutProjectionYearPercentiles",
        "firstCutAgePercentiles",
    }
    assert 0.0 <= stats["pathsWithMultipleCuts"] <= 1.0
    assert stats["cutCountPercentiles"]["p50"] >= 0.0
    if stats["firstCutProjectionYearPercentiles"]:
        assert stats["firstCutProjectionYearPercentiles"]["p10"] >= 1.0


def test_guardrails_cut_spending_in_a_stressed_plan() -> None:
    # Under a stressed 6% draw, the capital-preservation rail binds on many paths,
    # and the low-spend (p10) band falls below the year-0 net draw of $60k.
    r = _stressed(guardrails=GuardrailParams())
    assert r["guardrailActivity"]["pathsWithCut"] > 0.0
    assert min(r["spendingByYear"]["p10"]) < 60_000.0


def test_guardrails_improve_success_vs_static_plan() -> None:
    # The headline of GK: cutting spending in bad markets preserves the portfolio,
    # so dynamic withdrawals fail less often than the same base spend held static.
    static = _stressed()
    dynamic = _stressed(guardrails=GuardrailParams())
    assert dynamic["successProbability"] > static["successProbability"]


def test_prosperity_rule_raises_spending_when_the_plan_is_flush() -> None:
    # A conservative 3% draw with strong returns trips the prosperity rail upward,
    # so the high-spend (p90) band rises above the year-0 net draw of $30k.
    flush = _stressed(
        net_spend_by_year=[30_000 * (1.025**y) for y in range(30)],
        means=[0.09, 0.04],
        guardrails=GuardrailParams(),
    )
    assert flush["guardrailActivity"]["pathsWithRaise"] > 0.0
    assert max(flush["spendingByYear"]["p90"]) > 30_000.0


def test_guardrails_determinism_same_seed() -> None:
    assert _stressed(guardrails=GuardrailParams()) == _stressed(guardrails=GuardrailParams())


def test_guardrails_freeze_after_loss_toggle_changes_spending() -> None:
    # The post-loss inflation freeze is load-bearing: toggling it produces a
    # materially different median spend path (freeze-off spends faster early,
    # which trips more capital-preservation cuts later — a real GK dynamic).
    frozen = _stressed(guardrails=GuardrailParams(freeze_after_loss=True))
    unfrozen = _stressed(guardrails=GuardrailParams(freeze_after_loss=False))
    assert frozen["spendingByYear"]["p50"] != unfrozen["spendingByYear"]["p50"]


def test_guardrails_credit_pre_decumulation_income_surplus() -> None:
    # A guaranteed-income SURPLUS before the spend ramp is a negative net draw
    # (a portfolio inflow). Enabling guardrails must NOT drop it: the static and
    # guardrail runs match through the surplus years (the rails only engage at
    # the first positive draw). Here years 0-2 are a -$50k/yr surplus inflow.
    surplus = [-50_000.0, -50_000.0, -50_000.0] + [80_000 * (1.025**y) for y in range(17)]
    kw: dict[str, Any] = {
        "years": 20,
        "current_age": 65,
        "initial_balance": 1_000_000.0,
        "net_spend_by_year": surplus,
        "return_model": "multivariate_normal",
        "means": [0.06, 0.03],
        "paths": 3000,
        "seed": 909,
        "regime_seed": 909,
    }
    static = _run(**kw)
    dynamic = _run(**kw, guardrails=GuardrailParams())
    # The surplus inflow is credited under guardrails (median balance climbs over
    # the inflow years), not dropped — and the surplus years show zero withdrawal.
    assert dynamic["medianBalanceByYear"][2] > dynamic["medianBalanceByYear"][0]
    assert dynamic["spendingByYear"]["p50"][0] == 0.0
    # The guardrail run isn't penalized vs static for the surplus phase (the bug
    # was guardrails zeroing the inflow → a spurious terminal shortfall).
    assert dynamic["medianBalanceByYear"][2] == static["medianBalanceByYear"][2]


def test_guardrails_no_positive_draw_ever_is_pure_inflow() -> None:
    # Income always exceeds spend ⇒ every net draw is negative ⇒ gk_start < 0 ⇒
    # no withdrawal rule ever engages; guardrails == static (pure inflow growth).
    inflow_only = [-20_000.0] * 15
    kw: dict[str, Any] = {
        "years": 15,
        "current_age": 70,
        "initial_balance": 800_000.0,
        "net_spend_by_year": inflow_only,
        "return_model": "multivariate_normal",
        "means": [0.05, 0.03],
        "paths": 2000,
        "seed": 313,
        "regime_seed": 313,
    }
    assert (
        _run(**kw)["medianBalanceByYear"]
        == _run(**kw, guardrails=GuardrailParams())["medianBalanceByYear"]
    )


def test_guardrails_respect_an_accumulation_phase() -> None:
    # retirementAge > currentAge ⇒ leading zero net-spend years; the guardrails
    # start at the first positive draw, and accumulation years spend nothing.
    r = _run(
        years=20,
        current_age=55,
        initial_balance=1_000_000.0,
        net_spend_by_year=[0.0] * 5 + [70_000 * (1.025**y) for y in range(15)],
        return_model="multivariate_normal",
        means=[0.06, 0.03],
        paths=2000,
        seed=77,
        regime_seed=77,
        guardrails=GuardrailParams(),
    )
    assert r["spendingByYear"]["p50"][0] == 0.0  # accumulation: no withdrawal
    assert r["spendingByYear"]["p50"][5] > 0.0  # decumulation has begun
