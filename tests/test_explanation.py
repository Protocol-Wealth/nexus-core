# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the score-explanation surface (Tier-2 N2).

Two load-bearing properties:

1. The explanation accurately mirrors which checks passed / failed / went
   unevaluated, and surfaces the confidence tier + the regime signals'
   votes when those are present on the context.

2. The explanation NEVER carries threshold values, raw signal values, or
   numeric cutoffs from the regime classification — the public-repo public
   contract is "shape only, not cutoffs". This is verified by asserting that
   serialized ``SignalContribution`` dicts contain ONLY the three sanitized
   keys (name / status / supports_regime).
"""

from __future__ import annotations

from nexus_core.engine.regime.signals import SignalStatus
from nexus_core.engine.scoring import (
    CheckResult,
    ConfidenceTier,
    ScoringContext,
    ScoringFramework,
    build_score_explanation,
)

# ---------------- Stub checks ----------------


def _pass(num: int, name: str) -> CheckResult:
    return CheckResult(
        check_number=num,
        name=name,
        value=1.0,
        threshold=0.5,
        passed=True,
        signal="strong",
        interpretation=f"{name} above threshold",
    )


def _fail(num: int, name: str) -> CheckResult:
    return CheckResult(
        check_number=num,
        name=name,
        value=0.1,
        threshold=0.5,
        passed=False,
        signal="weak",
        interpretation=f"{name} below threshold",
    )


def _missing(num: int, name: str) -> CheckResult:
    return CheckResult(
        check_number=num,
        name=name,
        value=None,
        threshold=None,
        passed=None,
        signal="missing",
        interpretation=f"{name} could not be evaluated",
    )


class PassCheck:
    def __init__(self, num: int, name: str) -> None:
        self.num = num
        self.name = name

    def __call__(self, ctx: object) -> CheckResult:
        return _pass(self.num, self.name)


class FailCheck:
    def __init__(self, num: int, name: str) -> None:
        self.num = num
        self.name = name

    def __call__(self, ctx: object) -> CheckResult:
        return _fail(self.num, self.name)


class MissingCheck:
    def __init__(self, num: int, name: str) -> None:
        self.num = num
        self.name = name

    def __call__(self, ctx: object) -> CheckResult:
        return _missing(self.num, self.name)


# ---------------- N2 — builder ----------------


def test_build_explanation_partitions_checks() -> None:
    """passed / failed / not_evaluated lists carry the right names."""
    results = [_pass(1, "CROIC"), _fail(2, "FScore"), _missing(3, "Hurst")]
    exp = build_score_explanation(
        check_results=results,
        total_checks=3,
        total_passed=1,
        confidence_tier=ConfidenceTier.BELOW,
    )
    assert exp.checks_passed == ["CROIC"]
    assert exp.checks_failed == ["FScore"]
    assert exp.checks_not_evaluated == ["Hurst"]
    assert exp.pass_share == 1 / 3
    assert exp.confidence_tier == ConfidenceTier.BELOW.value


def test_build_explanation_zero_checks_yields_zero_share() -> None:
    exp = build_score_explanation(
        check_results=[],
        total_checks=0,
        total_passed=0,
        confidence_tier=ConfidenceTier.BELOW,
    )
    assert exp.pass_share == 0.0


def test_per_check_summary_is_capped() -> None:
    """Long interpretations are truncated; per-check stays high-level."""
    long_text = "x" * 500
    results = [
        CheckResult(
            check_number=1,
            name="LongCheck",
            value=0.5,
            threshold=0.4,
            passed=True,
            signal="strong",
            interpretation=long_text,
        )
    ]
    exp = build_score_explanation(
        check_results=results,
        total_checks=1,
        total_passed=1,
        confidence_tier=ConfidenceTier.HIGH,
    )
    assert len(exp.per_check[0].summary) <= 200


def test_signal_contributions_strip_threshold_and_raw_value() -> None:
    """The sanitized contribution carries ONLY name + status + supports_regime."""
    statuses = [
        SignalStatus(
            name="Gold/SPX Ratio",
            current_value=42.123,  # MUST NOT appear in the explanation
            threshold_info="<3.5=Growth, >5.0=Hard Asset",  # MUST NOT appear
            status="bearish",
            supports_regime="hard_asset",
        ),
    ]
    exp = build_score_explanation(
        check_results=[_pass(1, "A")],
        total_checks=1,
        total_passed=1,
        confidence_tier=ConfidenceTier.HIGH,
        regime_signal_statuses=statuses,
    )
    assert len(exp.regime_signal_contributions) == 1
    c = exp.regime_signal_contributions[0]
    serialized = c.to_dict()
    assert set(serialized.keys()) == {"name", "status", "supports_regime"}
    # Defensive: also assert the values don't carry stray numeric content.
    assert "42.123" not in str(serialized)
    assert "3.5" not in str(serialized)
    assert "5.0" not in str(serialized)


def test_signal_contributions_accept_dict_shape() -> None:
    """Builder accepts plain dicts (from RegimeResult.to_dict())."""
    statuses_as_dicts = [
        {
            "name": "Real Rates",
            "current_value": 1.234,
            "threshold_info": ">2=Risk On",
            "status": "bullish",
            "supports_regime": "growth",
        }
    ]
    exp = build_score_explanation(
        check_results=[_pass(1, "A")],
        total_checks=1,
        total_passed=1,
        confidence_tier=ConfidenceTier.MODERATE,
        regime_signal_statuses=statuses_as_dicts,
    )
    assert len(exp.regime_signal_contributions) == 1
    assert exp.regime_signal_contributions[0].name == "Real Rates"
    assert exp.regime_signal_contributions[0].supports_regime == "growth"


# ---------------- N2 — framework integration ----------------


def test_framework_populates_explanation() -> None:
    """ScoringFramework.score automatically populates result.explanation."""
    framework = ScoringFramework(
        checks=[PassCheck(1, "A"), FailCheck(2, "B"), MissingCheck(3, "C")]
    )
    ctx = ScoringContext(ticker="TEST")
    result = framework.score(ctx)
    assert result.explanation is not None
    assert result.explanation.checks_passed == ["A"]
    assert result.explanation.checks_failed == ["B"]
    assert result.explanation.checks_not_evaluated == ["C"]
    assert abs(result.explanation.pass_share - 1 / 3) < 1e-9


def test_framework_surfaces_regime_signal_statuses_from_ctx() -> None:
    """When ctx.regime['signal_statuses'] is a list, it lands in the explanation."""
    statuses = [
        SignalStatus(
            name="VIX",
            current_value=18.5,
            threshold_info="<14=Complacent",
            status="neutral",
            supports_regime="transition",
        ),
    ]
    ctx = ScoringContext(
        ticker="TEST",
        regime={"signal_statuses": statuses},
    )
    framework = ScoringFramework(checks=[PassCheck(1, "A")])
    result = framework.score(ctx)
    assert result.explanation is not None
    assert len(result.explanation.regime_signal_contributions) == 1
    assert result.explanation.regime_signal_contributions[0].name == "VIX"


def test_score_result_to_dict_includes_explanation() -> None:
    """ScoreResult.to_dict() round-trips the explanation as a plain dict."""
    framework = ScoringFramework(checks=[PassCheck(1, "A")])
    ctx = ScoringContext(ticker="TEST")
    result = framework.score(ctx)
    d = result.to_dict()
    assert "explanation" in d
    assert d["explanation"] is not None
    assert d["explanation"]["checks_passed"] == ["A"]
    assert d["explanation"]["confidence_tier"] == result.tier.value
