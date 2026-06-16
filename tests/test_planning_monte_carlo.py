# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the Monte Carlo decumulation engine."""

from __future__ import annotations

from typing import Any

from nexus_core.engine.planning import monte_carlo_decumulation
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
    assert set(r["depletionStats"]) == {
        "failedPathCount",
        "failedPathProbability",
        "depletionYearPercentiles",
    }
    assert r["firstDecadeReturnVsOutcome"]["years"] == 10


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


def test_determinism_same_seed_identical() -> None:
    assert _run(seed=99, regime_seed=99) == _run(seed=99, regime_seed=99)


def test_all_return_models_produce_valid_output() -> None:
    for model in _MODELS:
        r = _run(return_model=model)
        assert 0.0 <= r["successProbability"] <= 1.0
        assert len(r["medianBalanceByYear"]) == 50
        assert r["seedUsed"] == 12345


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
