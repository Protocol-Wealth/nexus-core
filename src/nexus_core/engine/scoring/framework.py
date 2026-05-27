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
from datetime import date
from typing import Any

from .checks import Check, CheckResult
from .explanation import ScoreExplanation, build_score_explanation
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
        as_of: Date the scoring was performed against. When ``None``, the
            scoring used the latest data available to ``ctx``. When set, the
            scoring is reproducible from frozen inputs — same ``ctx`` + same
            ``as_of`` always produces the same ``ScoreResult``.
        explanation: Shape-only view of the scoring decision (which checks
            passed, which regime signals voted, confidence tier). Sanitized:
            no threshold values or numeric cutoffs are exposed via this
            field. Populated by ``ScoringFramework.score`` automatically;
            consumers may also call ``build_score_explanation`` directly.
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
    as_of: date | None = None
    explanation: ScoreExplanation | None = None

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
            "as_of": self.as_of.isoformat() if self.as_of is not None else None,
            "explanation": self.explanation.to_dict() if self.explanation is not None else None,
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

    def score(
        self,
        ctx: Any,
        *,
        subject: str | None = None,
        as_of: date | None = None,
    ) -> ScoreResult:
        """Run all checks and enhancements over ``ctx`` and return a ``ScoreResult``.

        Args:
            ctx: Scoring context. The checks read from this; the framework
                only inspects ``ctx.ticker`` (or falls back to ``str(ctx)``)
                for the result subject and ``ctx.regime["signal_statuses"]``
                (if present) to populate the explanation's regime contributions.
            subject: Override for the result's ``subject`` field.
            as_of: Date the scoring is "as of". Echoed onto
                ``ScoreResult.as_of`` so the result is reproducible: given
                identical ``ctx`` + identical ``as_of``, the framework
                returns an identical ``ScoreResult``. Pass ``None`` (the
                default) when scoring against live data.
        """
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

        # Pull regime signal_statuses off the context if it carries them.
        regime_attr = getattr(ctx, "regime", None)
        regime_signal_statuses: list[Any] | None = None
        if isinstance(regime_attr, dict):
            ss = regime_attr.get("signal_statuses")
            if isinstance(ss, list):
                regime_signal_statuses = ss

        explanation = build_score_explanation(
            check_results=results,
            total_checks=total_checks,
            total_passed=total_passed,
            confidence_tier=tier,
            regime_signal_statuses=regime_signal_statuses,
        )

        result = ScoreResult(
            subject=subject or getattr(ctx, "ticker", str(ctx)),
            checks=results,
            total_passed=total_passed,
            total_evaluated=total_evaluated,
            total_checks=total_checks,
            tier=tier,
            as_of=as_of,
            explanation=explanation,
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
