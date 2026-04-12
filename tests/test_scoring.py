# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Unit tests for the scoring framework."""

from __future__ import annotations

import pytest

from nexus_core.engine.scoring import (
    CheckResult,
    ConfidenceTier,
    ScoreResult,
    ScoringContext,
    ScoringFramework,
    adversarial_brief_enhancement,
    base_rate_enhancement,
    classify_tier,
    consistency_enhancement,
    format_advisor,
    format_public,
    format_structured,
)


# ---------------- Fixture checks ----------------


class AlwaysPassCheck:
    def __init__(self, number: int, name: str) -> None:
        self.number = number
        self.name = name

    def __call__(self, ctx) -> CheckResult:  # noqa: ANN001
        return CheckResult(
            check_number=self.number,
            name=self.name,
            value=1.0,
            threshold=0.5,
            passed=True,
            signal="strong",
            interpretation=f"{self.name} strong",
        )


class AlwaysFailCheck:
    def __init__(self, number: int, name: str) -> None:
        self.number = number
        self.name = name

    def __call__(self, ctx) -> CheckResult:  # noqa: ANN001
        return CheckResult(
            check_number=self.number,
            name=self.name,
            value=0.0,
            threshold=0.5,
            passed=False,
            signal="weak",
            interpretation=f"{self.name} weak",
        )


# ---------------- Tiers ----------------


@pytest.mark.unit
class TestTiers:
    def test_high_tier(self) -> None:
        assert classify_tier(7, 8) == ConfidenceTier.HIGH
        assert classify_tier(8, 8) == ConfidenceTier.HIGH

    def test_moderate_tier(self) -> None:
        assert classify_tier(4, 8) == ConfidenceTier.MODERATE
        assert classify_tier(5, 8) == ConfidenceTier.MODERATE

    def test_low_tier(self) -> None:
        assert classify_tier(3, 8) == ConfidenceTier.LOW

    def test_below_tier(self) -> None:
        assert classify_tier(0, 8) == ConfidenceTier.BELOW
        assert classify_tier(2, 8) == ConfidenceTier.BELOW

    def test_not_applicable(self) -> None:
        assert classify_tier(0, 8, not_applicable=True) == ConfidenceTier.NOT_APPLICABLE


# ---------------- Framework ----------------


@pytest.mark.unit
class TestScoringFramework:
    def test_all_pass_yields_high(self) -> None:
        framework = ScoringFramework(checks=[AlwaysPassCheck(i, f"check_{i}") for i in range(1, 9)])
        ctx = ScoringContext(ticker="AAPL")
        result = framework.score(ctx)
        assert result.total_passed == 8
        assert result.tier == ConfidenceTier.HIGH

    def test_all_fail_yields_below(self) -> None:
        framework = ScoringFramework(checks=[AlwaysFailCheck(i, f"check_{i}") for i in range(1, 9)])
        ctx = ScoringContext(ticker="XYZ")
        result = framework.score(ctx)
        assert result.total_passed == 0
        assert result.tier == ConfidenceTier.BELOW

    def test_mixed(self) -> None:
        framework = ScoringFramework(
            checks=[
                *[AlwaysPassCheck(i, f"pass_{i}") for i in range(1, 5)],
                *[AlwaysFailCheck(i, f"fail_{i}") for i in range(5, 9)],
            ]
        )
        result = framework.score(ScoringContext(ticker="MID"))
        assert result.total_passed == 4
        assert result.tier == ConfidenceTier.MODERATE

    def test_check_failure_is_captured(self) -> None:
        class BrokenCheck:
            def __call__(self, ctx):  # noqa: ANN001, ANN202
                raise ValueError("synthetic error")

        framework = ScoringFramework(checks=[BrokenCheck()])
        result = framework.score(ScoringContext(ticker="X"))
        assert len(result.checks) == 1
        assert result.checks[0].passed is None
        assert result.checks[0].signal == "error"


# ---------------- Enhancements ----------------


@pytest.mark.unit
class TestEnhancements:
    def _mk_result(self, tier: ConfidenceTier, passed: int) -> ScoreResult:
        return ScoreResult(
            subject="ABC",
            checks=[
                CheckResult(
                    check_number=i,
                    name=f"c{i}",
                    value=1.0 if i <= passed else 0.0,
                    passed=i <= passed,
                )
                for i in range(1, 9)
            ],
            total_passed=passed,
            total_evaluated=8,
            total_checks=8,
            tier=tier,
        )

    def test_base_rate_detects_divergent_on_high(self) -> None:
        result = self._mk_result(ConfidenceTier.HIGH, passed=6)
        ret = base_rate_enhancement(result, None)
        assert ret is not None
        key, payload = ret
        assert key == "base_rate"
        assert payload["narrative_override_warning"] is True
        assert len(payload["divergent_checks"]) == 2

    def test_adversarial_only_for_high(self) -> None:
        high_result = self._mk_result(ConfidenceTier.HIGH, passed=7)
        low_result = self._mk_result(ConfidenceTier.LOW, passed=3)
        assert adversarial_brief_enhancement(high_result, None) is not None
        assert adversarial_brief_enhancement(low_result, None) is None

    def test_consistency_with_steady_revenue(self) -> None:
        result = self._mk_result(ConfidenceTier.HIGH, passed=7)
        ctx = ScoringContext(
            ticker="ABC",
            fundamentals={
                "income_statements": [
                    {"revenue": 1000.0, "eps": 2.0},
                    {"revenue": 1010.0, "eps": 2.02},
                    {"revenue": 1020.0, "eps": 2.04},
                    {"revenue": 1030.0, "eps": 2.06},
                ],
            },
        )
        ret = consistency_enhancement(result, ctx)
        assert ret is not None
        key, payload = ret
        assert key == "consistency"
        assert payload["interpretation"] == "Low variance"


# ---------------- Formatters ----------------


@pytest.mark.unit
class TestFormatters:
    def _result(self) -> ScoreResult:
        framework = ScoringFramework(
            checks=[
                AlwaysPassCheck(1, "CROIC"),
                AlwaysPassCheck(2, "F-Score"),
                AlwaysFailCheck(3, "Hurst"),
            ],
            total_checks_override=8,
        )
        return framework.score(ScoringContext(ticker="DEMO"))

    def test_public(self) -> None:
        text = format_public(self._result())
        assert "Quality Score" in text
        assert "Cash Generation Quality" in text  # public label for CROIC
        assert "Financial Health Score" in text  # public label for F-Score

    def test_advisor(self) -> None:
        text = format_advisor(self._result())
        assert "DEMO" in text
        assert "CROIC:" in text
        assert "Hurst:" in text

    def test_structured(self) -> None:
        payload = format_structured(self._result())
        assert payload["subject"] == "DEMO"
        assert "checks" in payload
        assert len(payload["checks"]) == 3
        # Attribution present on CROIC
        croic = next(c for c in payload["checks"] if c["name"] == "CROIC")
        assert croic["method"]
        assert croic["source"]
