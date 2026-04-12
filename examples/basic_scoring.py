# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Minimal scoring framework example.

Defines three toy checks to demonstrate the check/framework/enhancement
pattern. Real scoring systems will have 5-10 checks covering quality,
momentum, durability, and macro fit.
"""

from __future__ import annotations

from nexus_core.engine.scoring import (
    CheckResult,
    ScoringContext,
    ScoringFramework,
    adversarial_brief_enhancement,
    base_rate_enhancement,
    consistency_enhancement,
    format_advisor,
    format_structured,
)


class CROICCheck:
    """Cash Return on Invested Capital check."""

    def __init__(self, threshold: float = 0.08) -> None:
        self.threshold = threshold

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        croic = ctx.fundamentals.get("croic", 0.0)
        passed = croic > self.threshold
        return CheckResult(
            check_number=1,
            name="CROIC",
            value=croic,
            threshold=self.threshold,
            passed=passed,
            signal="strong" if croic > 0.15 else "solid" if passed else "weak",
            interpretation=f"CROIC of {croic:.1%}",
        )


class FScoreCheck:
    """Piotroski F-Score check (simplified)."""

    def __init__(self, threshold: int = 6) -> None:
        self.threshold = threshold

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        fscore = ctx.fundamentals.get("f_score", 0)
        passed = fscore >= self.threshold
        return CheckResult(
            check_number=2,
            name="F-Score",
            value=float(fscore),
            threshold=float(self.threshold),
            passed=passed,
            signal="improving" if passed else "weak",
            interpretation=f"F-Score {fscore}/9",
        )


class HurstCheck:
    """Hurst exponent — trend persistence > 0.55."""

    def __init__(self, threshold: float = 0.55) -> None:
        self.threshold = threshold

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        hurst = ctx.extra.get("hurst", 0.5)
        passed = hurst > self.threshold
        return CheckResult(
            check_number=3,
            name="Hurst",
            value=hurst,
            threshold=self.threshold,
            passed=passed,
            signal="persistent" if passed else "mean-reverting",
            interpretation=f"Hurst exponent {hurst:.3f}",
        )


def main() -> None:
    framework = ScoringFramework(
        checks=[CROICCheck(), FScoreCheck(), HurstCheck()],
        enhancements=[
            consistency_enhancement,
            base_rate_enhancement,
            adversarial_brief_enhancement,
        ],
        total_checks_override=8,  # pretend we have a full 8-check suite
    )

    # A high-quality asset that should score well.
    ctx = ScoringContext(
        ticker="DEMO",
        fundamentals={
            "croic": 0.18,
            "f_score": 7,
            "income_statements": [
                {"revenue": 1000.0, "eps": 2.0},
                {"revenue": 1020.0, "eps": 2.1},
                {"revenue": 1050.0, "eps": 2.2},
                {"revenue": 1080.0, "eps": 2.3},
            ],
        },
        extra={"hurst": 0.62},
    )

    result = framework.score(ctx)
    print(format_advisor(result))
    print()
    print("structured output keys:", list(format_structured(result).keys()))


if __name__ == "__main__":
    main()
