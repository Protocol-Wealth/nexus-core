# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic tests for EMF Check 4 — Lambda (λ) decay constant."""

from __future__ import annotations

from nexus_core.engine.scoring import ScoringContext
from nexus_core.engine.scoring.emf.lambda_decay import (
    DEFAULT_LAYER_THRESHOLD,
    LAYER_DECAY_THRESHOLDS,
    LambdaCheck,
    compute_lambda,
)


def _ctx(ticker: str = "TEST", **fund: object) -> ScoringContext:
    extra = {}
    if "layer" in fund:
        # Allow tests to drive the layer via extra to exercise that path.
        extra["layer"] = fund.pop("layer")
    return ScoringContext(ticker=ticker, fundamentals=dict(fund), extra=extra)


# --------------------------- compute_lambda ---------------------------------


def test_compute_lambda_sector_base() -> None:
    # Regulated Utilities base = 0.04, no industry adjustments.
    assert compute_lambda(sector="Regulated Utilities", industry="") == 0.04


def test_compute_lambda_ticker_override_wins() -> None:
    # NVDA override = 0.12 regardless of sector.
    assert compute_lambda(sector="Unknown", industry="", ticker="NVDA") == 0.12


def test_compute_lambda_physical_infra_adjustment() -> None:
    # Nuclear Power base 0.02 minus physical-assets 0.03 -> clamp floor 0.01.
    val = compute_lambda(sector="Nuclear Power", industry="nuclear generation")
    assert val == 0.01


def test_compute_lambda_saas_trinity_penalty() -> None:
    # ASAN override base 0.30 + SaaS-trinity penalty 0.08 = 0.38.
    val = compute_lambda(sector="Enterprise SaaS", industry="software", ticker="ASAN")
    assert val == 0.38


def test_compute_lambda_clamped_high() -> None:
    # Quantum Computing base 0.50 stays clamped at 0.50.
    assert compute_lambda(sector="Quantum Computing", industry="") == 0.50


def test_compute_lambda_unknown_default() -> None:
    assert compute_lambda(sector=None, industry=None, ticker=None) == DEFAULT_LAYER_THRESHOLD


# ------------------------------ pass case -----------------------------------


def test_pass_low_lambda_layer_adjusted() -> None:
    # CEG override λ=0.02, layer L1 threshold 0.05 -> passes.
    res = LambdaCheck()(_ctx("CEG", sector="Regulated Utilities", layer="L1"))
    assert res.check_number == 4
    assert res.name == "Lambda (λ)"
    assert res.value == 0.02
    assert res.threshold == LAYER_DECAY_THRESHOLDS["L1"] == 0.05
    assert res.passed is True
    assert res.signal == "GREEN"
    assert res.details["decay_category"] == "Very Low"


def test_pass_precomputed_lambda() -> None:
    # decay_constant 0.06 < L3 threshold 0.20 (no "lambda" key present).
    res = LambdaCheck()(_ctx("XYZ", decay_constant=0.06, layer="L3"))
    assert res.value == 0.06
    assert res.threshold == 0.20
    assert res.passed is True
    assert res.details["computed"] is False


# ------------------------------ fail case -----------------------------------


def test_fail_high_lambda_against_strict_layer() -> None:
    # NVDA λ=0.12, but L1 threshold is 0.05 -> fails (high decay).
    res = LambdaCheck()(_ctx("NVDA", sector="Semiconductors", layer="L1"))
    assert res.value == 0.12
    assert res.threshold == 0.05
    assert res.passed is False
    assert res.signal == "RED"


def test_yellow_signal_moderate_decay() -> None:
    # Precomputed λ just above threshold but below 1.5x -> YELLOW, fail.
    # L4 threshold 0.15; λ=0.18 -> 0.18 >= 0.15 and < 0.225 -> YELLOW.
    res = LambdaCheck()(_ctx("ABC", decay_constant=0.18, layer="L4"))
    assert res.passed is False
    assert res.signal == "YELLOW"


def test_default_threshold_when_layer_absent() -> None:
    # No layer -> default 0.20. Enterprise SaaS base 0.22 (no industry kw) fails.
    res = LambdaCheck()(_ctx("FOO", sector="Enterprise SaaS"))
    assert res.threshold == DEFAULT_LAYER_THRESHOLD
    assert res.value == 0.22
    assert res.passed is False


# --------------------------- missing data -----------------------------------


def test_missing_data_returns_none() -> None:
    # No precomputed λ, no sector/industry, blank ticker -> cannot estimate.
    ctx = ScoringContext(ticker="", fundamentals={}, extra={})
    res = LambdaCheck()(ctx)
    assert res.value is None
    assert res.passed is None
    assert res.signal == "insufficient_data"
    assert res.check_number == 4


def test_garbage_precomputed_falls_through_to_compute() -> None:
    # Non-numeric precomputed value is ignored; estimation kicks in.
    res = LambdaCheck()(_ctx("CEG", **{"lambda": "n/a", "sector": "Regulated Utilities"}))
    assert res.value == 0.02
    assert res.details["computed"] is True
