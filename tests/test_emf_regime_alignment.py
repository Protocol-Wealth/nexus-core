# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic tests for EMF Check 6 — Regime Alignment.

No network. Builds ScoringContext objects from fixture dicts and asserts the
pass / fail / missing-data behaviour against the ported pw-nexus thresholds.
"""

from __future__ import annotations

from nexus_core.engine.scoring.checks import ScoringContext
from nexus_core.engine.scoring.emf.regime_alignment import (
    LAYER_WEIGHTS_BY_REGIME,
    RegimeAlignmentCheck,
    normalize_layer,
    normalize_regime,
    regime_layer_weight,
)


def _ctx(regime: object, layer: object) -> ScoringContext:
    return ScoringContext(
        ticker="TEST",
        fundamentals={"layer": layer},
        regime={"code": regime},
    )


def test_pass_layer_at_or_above_threshold() -> None:
    # GROWTH regime: L3_engine carries 25% weight -> pass, GREEN, favored.
    result = RegimeAlignmentCheck()(_ctx("G", "L3_engine"))
    assert result.check_number == 6
    assert result.name == "Regime Alignment"
    assert result.value == 25.0
    assert result.threshold == 15.0
    assert result.passed is True
    assert result.signal == "GREEN"
    assert result.details["current_regime"] == "G"
    assert result.details["layer"] == "L3_engine"


def test_pass_exactly_at_threshold() -> None:
    # GROWTH regime: L2_backbone carries exactly 15% -> pass (>= 15).
    result = RegimeAlignmentCheck()(_ctx("GROWTH", "L2_backbone"))
    assert result.value == 15.0
    assert result.passed is True
    assert result.signal == "GREEN"


def test_fail_layer_below_threshold() -> None:
    # HARD_ASSET regime: L5_interface carries only 5% weight -> fail, RED.
    result = RegimeAlignmentCheck()(_ctx("Hard Asset", "L5_interface"))
    assert result.value == 5.0
    assert result.passed is False
    assert result.signal == "RED"


def test_fail_marginal_yellow_band() -> None:
    # GROWTH regime: L1_foundation carries 10% -> fail but YELLOW (10 <= w < 15).
    result = RegimeAlignmentCheck()(_ctx("G", "L1_foundation"))
    assert result.value == 10.0
    assert result.passed is False
    assert result.signal == "YELLOW"


def test_zero_weight_is_a_real_fail_not_missing() -> None:
    # DEFLATION: L6_frontier carries 0% -> a real "unfavored" verdict, passed False.
    result = RegimeAlignmentCheck()(_ctx("DEFLATION", "L6_frontier"))
    assert result.value == 0.0
    assert result.passed is False
    assert result.signal == "RED"


def test_missing_regime_degrades_to_none() -> None:
    ctx = ScoringContext(ticker="TEST", fundamentals={"layer": "L3_engine"}, regime={})
    result = RegimeAlignmentCheck()(ctx)
    assert result.value is None
    assert result.passed is None
    assert result.signal == "insufficient_data"


def test_missing_layer_degrades_to_none() -> None:
    ctx = ScoringContext(ticker="TEST", fundamentals={}, regime={"code": "G"})
    result = RegimeAlignmentCheck()(ctx)
    assert result.value is None
    assert result.passed is None
    assert result.signal == "insufficient_data"


def test_unrecognized_regime_degrades_to_none() -> None:
    result = RegimeAlignmentCheck()(_ctx("NONSENSE", "L3_engine"))
    assert result.passed is None
    assert result.signal == "insufficient_data"


def test_unrecognized_layer_degrades_to_none() -> None:
    result = RegimeAlignmentCheck()(_ctx("G", "L99_nope"))
    assert result.passed is None
    assert result.signal == "insufficient_data"


def test_layer_read_from_extra_fallback() -> None:
    # No layer in fundamentals; falls back to extra["layer_assignment"].
    ctx = ScoringContext(
        ticker="TEST",
        fundamentals={},
        regime={"code": "G"},
        extra={"layer_assignment": "L3_engine"},
    )
    result = RegimeAlignmentCheck()(ctx)
    assert result.value == 25.0
    assert result.passed is True


def test_short_layer_code_normalizes() -> None:
    # "L3" short code resolves to L3_engine.
    result = RegimeAlignmentCheck()(_ctx("G", "L3"))
    assert result.value == 25.0
    assert result.passed is True


def test_never_throws_on_garbage() -> None:
    # Non-string junk in the context must not raise.
    ctx = ScoringContext(
        ticker="TEST",
        fundamentals={"layer": object()},
        regime={"code": 12345},
    )
    result = RegimeAlignmentCheck()(ctx)
    assert result.passed is None
    assert result.signal == "insufficient_data"


def test_helpers_match_table() -> None:
    assert normalize_regime("Hard Asset") == "H"
    assert normalize_regime("growth") == "G"
    assert normalize_regime(None) is None
    assert normalize_layer("L7") == "L7_catalyst"
    assert normalize_layer("L4_datatoll") == "L4_datatoll"
    assert regime_layer_weight("R", "L1_foundation") == 30
    assert regime_layer_weight("G", "L6_frontier") == 10
    assert regime_layer_weight("bad", "L1_foundation") is None
    assert regime_layer_weight("G", "bad") is None


def test_table_shape_is_canonical() -> None:
    # Five regimes, each with all seven layers.
    assert set(LAYER_WEIGHTS_BY_REGIME) == {"G", "T", "H", "D", "R"}
    for weights in LAYER_WEIGHTS_BY_REGIME.values():
        assert len(weights) == 7
        assert sum(weights.values()) == 100
