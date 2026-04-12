# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""N-check scoring framework.

``ScoringFramework`` runs a configured set of checks against a context and
aggregates the results into a ``ScoreResult`` with:

    - Raw check results
    - Total passed / total evaluated
    - Confidence tier
    - Optional enhancements (consistency score, base rate anchor,
      adversarial brief) — plug in via the ``enhancements`` argument

The framework is deliberately composable. Each check is responsible for one
thing; enhancements are secondary passes over the results.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .checks import Check, CheckResult
from .tiers import ConfidenceTier, classify_tier


@dataclass
class ScoreResult:
    """Aggregated scoring output.

    Attributes:
        subject: Identifier of what was scored (typically a ticker).
        checks: Individual ``CheckResult`` entries.
        total_passed: How many checks returned ``passed=True``.
        total_evaluated: How many checks returned non-None ``passed``.
        total_checks: Configured check count.
        tier: Confidence tier.
        enhancements: Bag of enhancement outputs (consistency, base_rate, etc.)
        layer_assignment: Optional durability-layer assignment (domain-specific).
        metadata: Arbitrary key-value pairs from the caller.
    """

    subject: str
    checks: list[CheckResult]
    total_passed: int
    total_evaluated: int
    total_checks: int
    tier: ConfidenceTier
    enhancements: dict[str, Any] = field(default_factory=dict)
    layer_assignment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "checks": [c.to_dict() for c in self.checks],
            "total_passed": self.total_passed,
            "total_evaluated": self.total_evaluated,
            "total_checks": self.total_checks,
            "tier": self.tier.value,
            "enhancements": self.enhancements,
            "layer_assignment": self.layer_assignment,
            "metadata": self.metadata,
        }


# An enhancement is a function that inspects the raw results and returns
# (key, payload) to attach to the ScoreResult.
Enhancement = Callable[["ScoreResult", Any], tuple[str, Any] | None]


@dataclass
class ScoringFramework:
    """Runs configured checks + enhancements against a context.

    Usage::

        framework = ScoringFramework(
            checks=[CROICCheck(), FScoreCheck(), HurstCheck(), ...],
            enhancements=[consistency_enhancement, base_rate_enhancement],
        )
        result = framework.score(ctx)
    """

    checks: Sequence[Check]
    enhancements: Sequence[Enhancement] = field(default_factory=tuple)
    total_checks_override: int | None = None
    """If set, override the denominator used for tier classification.
    Useful when you have 10 checks but want tiers calibrated for an 8-check
    framework."""

    def score(self, ctx: Any, *, subject: str | None = None) -> ScoreResult:
        """Run all checks and enhancements over ``ctx`` and return a ``ScoreResult``."""
        results: list[CheckResult] = []
        for check in self.checks:
            try:
                results.append(check(ctx))
            except Exception as e:  # pragma: no cover — enforce no-throw contract
                check_name = type(check).__name__
                results.append(
                    CheckResult(
                        check_number=len(results) + 1,
                        name=check_name,
                        value=None,
                        threshold=None,
                        passed=None,
                        signal="error",
                        interpretation=f"Check failed: {e}",
                    )
                )

        total_checks = self.total_checks_override or len(results)
        total_evaluated = sum(1 for r in results if r.passed is not None)
        total_passed = sum(1 for r in results if r.passed is True)

        tier = classify_tier(total_passed, total_checks)

        result = ScoreResult(
            subject=subject or getattr(ctx, "ticker", str(ctx)),
            checks=results,
            total_passed=total_passed,
            total_evaluated=total_evaluated,
            total_checks=total_checks,
            tier=tier,
        )

        # Run enhancements sequentially, in order; skip any that raise.
        for enhancement in self.enhancements:
            try:
                payload = enhancement(result, ctx)
                if payload is not None:
                    key, value = payload
                    result.enhancements[key] = value
            except Exception:  # pragma: no cover
                continue

        return result


__all__ = ["Enhancement", "ScoreResult", "ScoringFramework"]
