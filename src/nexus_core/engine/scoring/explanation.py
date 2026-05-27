# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Score-result explainability.

The ``ScoreExplanation`` object exposes the *shape* of a scoring decision —
which checks passed, which failed, which regime signals voted, what the
confidence tier was — WITHOUT exposing the threshold values, the signal
weights, or the cutoffs that produced those classifications.

That distinction matters for the public surface: a downstream consumer that
renders the explanation in a client-facing view (PW estate or any adopter)
gets a stable contract on the structure, while the operator's production
threshold values stay in the operator's private configuration. Public-repo
defaults are reference values; adopters supplying their own cutoffs do not
have those cutoffs leak through the explanation.

Use ``build_score_explanation`` to assemble one from a ``ScoreResult`` plus
any optional regime ``SignalStatus`` collection that fed the scoring run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .checks import CheckResult
from .tiers import ConfidenceTier


@dataclass(frozen=True)
class CheckExplanation:
    """Sanitized per-check view.

    Only carries the SHAPE of the check decision: did it pass, what signal
    direction did it report, and what's the short summary. No threshold
    value, no numeric cutoff, no raw value.
    """

    name: str
    passed: bool | None
    signal: str
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "signal": self.signal,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class SignalContribution:
    """Sanitized per-signal view from the regime classification step.

    Records which signal voted for which regime, but NOT the threshold cutoff
    or the raw signal value. This is the load-bearing privacy boundary for
    the explanation surface: an operator's production cutoffs are not
    derivable from any ``SignalContribution``.
    """

    name: str
    status: str
    supports_regime: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "supports_regime": self.supports_regime,
        }


@dataclass
class ScoreExplanation:
    """Top-level shape-only view of a scoring decision.

    Attributes:
        pass_share: total_passed / total_checks, in 0..1. Derived; safe to
            expose because it's a ratio, not a raw value.
        checks_passed: names of checks that returned ``passed=True``.
        checks_failed: names of checks that returned ``passed=False``.
        checks_not_evaluated: names of checks that returned ``passed=None``
            (insufficient data / errored).
        per_check: sanitized per-check view (name, pass/fail, signal,
            summary). NO numeric values, NO thresholds.
        confidence_tier: string form of the confidence tier (e.g.
            "high_conviction"); the tier enum's ``.value``.
        regime_signal_contributions: sanitized per-regime-signal view, when
            regime ``signal_statuses`` were available to the framework via
            ``ctx.regime["signal_statuses"]``. Empty list otherwise.
        notes: free-form structured notes the framework can attach for
            downstream display.
    """

    pass_share: float
    checks_passed: list[str]
    checks_failed: list[str]
    checks_not_evaluated: list[str]
    per_check: list[CheckExplanation]
    confidence_tier: str
    regime_signal_contributions: list[SignalContribution] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pass_share": self.pass_share,
            "checks_passed": list(self.checks_passed),
            "checks_failed": list(self.checks_failed),
            "checks_not_evaluated": list(self.checks_not_evaluated),
            "per_check": [c.to_dict() for c in self.per_check],
            "confidence_tier": self.confidence_tier,
            "regime_signal_contributions": [
                s.to_dict() for s in self.regime_signal_contributions
            ],
            "notes": list(self.notes),
        }


def _summarize(interpretation: str, limit: int = 140) -> str:
    """Cap interpretation at ``limit`` chars, ellipsizing if needed.

    Long check interpretations sometimes embed numeric values; the per-check
    explanation summary is meant to be short and high-level. Operators that
    want richer detail should keep the full ``CheckResult`` alongside the
    sanitized explanation.
    """
    s = interpretation.strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1].rstrip() + "…"


def build_score_explanation(
    *,
    check_results: list[CheckResult],
    total_checks: int,
    total_passed: int,
    confidence_tier: ConfidenceTier,
    regime_signal_statuses: list[Any] | None = None,
    notes: list[str] | None = None,
) -> ScoreExplanation:
    """Assemble a ``ScoreExplanation`` from raw scoring outputs.

    Args:
        check_results: the per-check results from the scoring run.
        total_checks: configured check count (may be > len(check_results)
            when ``total_checks_override`` was set).
        total_passed: number of checks with ``passed=True``.
        confidence_tier: classified confidence tier.
        regime_signal_statuses: optional regime ``SignalStatus`` collection.
            When supplied, each entry is sanitized to a ``SignalContribution``
            (name + status + supports_regime; NO threshold or raw value).
        notes: optional free-form notes.
    """
    passed = [r.name for r in check_results if r.passed is True]
    failed = [r.name for r in check_results if r.passed is False]
    not_eval = [r.name for r in check_results if r.passed is None]

    per_check = [
        CheckExplanation(
            name=r.name,
            passed=r.passed,
            signal=r.signal,
            summary=_summarize(r.interpretation),
        )
        for r in check_results
    ]

    pass_share = (total_passed / total_checks) if total_checks > 0 else 0.0

    contributions: list[SignalContribution] = []
    if regime_signal_statuses is not None:
        for s in regime_signal_statuses:
            # Be lenient about shape — accept both ``SignalStatus`` instances
            # and plain dicts (e.g. when the regime result has been
            # serialized via ``to_dict()``).
            name = getattr(s, "name", None) or (s.get("name") if isinstance(s, dict) else None)
            status = getattr(s, "status", None) or (
                s.get("status") if isinstance(s, dict) else None
            )
            supports = getattr(s, "supports_regime", None) or (
                s.get("supports_regime") if isinstance(s, dict) else None
            )
            if name is None or status is None or supports is None:
                continue
            contributions.append(
                SignalContribution(
                    name=str(name),
                    status=str(status),
                    supports_regime=str(supports),
                )
            )

    return ScoreExplanation(
        pass_share=pass_share,
        checks_passed=passed,
        checks_failed=failed,
        checks_not_evaluated=not_eval,
        per_check=per_check,
        confidence_tier=confidence_tier.value,
        regime_signal_contributions=contributions,
        notes=list(notes or []),
    )


__all__ = [
    "CheckExplanation",
    "ScoreExplanation",
    "SignalContribution",
    "build_score_explanation",
]
