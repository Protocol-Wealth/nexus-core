# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for deterministic replay via the ``as_of`` parameter (Tier-2 N3).

Three load-bearing properties:

1. Same ``signals`` + same ``as_of`` => identical ``RegimeResult`` (modulo
   ``days_in_regime`` which is computed from wall-clock at engine level —
   the classifier itself is fully pure).

2. The ``as_of`` value is echoed back onto the result so the call is
   reproducible from the result alone.

3. Same scoring ``ctx`` + same ``as_of`` => identical ``ScoreResult``
   (including the ``ScoreExplanation`` content, modulo any non-deterministic
   enhancement attached by the caller).
"""

from __future__ import annotations

from datetime import date

from nexus_core.engine.regime.classifier import RegimeClassifier
from nexus_core.engine.regime.signals import RegimeSignals
from nexus_core.engine.scoring import (
    CheckResult,
    ScoringContext,
    ScoringFramework,
)


def _signals() -> RegimeSignals:
    return RegimeSignals(
        gold_spx_ratio=4.0,
        gold_spx_200wma=3.8,
        gold_spx_vs_wma="above",
        real_rates=1.5,
        dxy=104.0,
        vix=15.0,
        credit_spreads=120.0,
    )


# ---------------- Regime classifier replay ----------------


def test_classifier_is_pure_on_signals() -> None:
    """Same signals => same regime + same confidence + same signal_statuses."""
    classifier = RegimeClassifier()
    signals = _signals()
    a = classifier.classify(signals, as_of=date(2025, 1, 15))
    b = classifier.classify(signals, as_of=date(2025, 1, 15))
    assert a.regime == b.regime
    assert a.confidence_score == b.confidence_score
    assert [s.to_dict() for s in a.signal_statuses] == [s.to_dict() for s in b.signal_statuses]


def test_classifier_echoes_as_of_onto_result() -> None:
    classifier = RegimeClassifier()
    result = classifier.classify(_signals(), as_of=date(2025, 6, 1))
    assert result.as_of == date(2025, 6, 1)


def test_classifier_as_of_default_is_none() -> None:
    """Backwards compat — omitted as_of is None."""
    classifier = RegimeClassifier()
    result = classifier.classify(_signals())
    assert result.as_of is None


def test_classifier_serializes_as_of_to_iso() -> None:
    classifier = RegimeClassifier()
    result = classifier.classify(_signals(), as_of=date(2024, 12, 31))
    d = result.to_dict()
    assert d["as_of"] == "2024-12-31"


def test_classifier_serializes_no_as_of_when_none() -> None:
    classifier = RegimeClassifier()
    result = classifier.classify(_signals())
    d = result.to_dict()
    assert "as_of" not in d


# ---------------- Scoring framework replay ----------------


class _DeterministicCheck:
    """Pure check used by the replay tests — return value is ctx-driven only."""

    def __init__(self, num: int, name: str, fundamentals_key: str) -> None:
        self.num = num
        self.name = name
        self.fundamentals_key = fundamentals_key

    def __call__(self, ctx: object) -> CheckResult:
        fundamentals = getattr(ctx, "fundamentals", {}) or {}
        value = fundamentals.get(self.fundamentals_key, 0.0)
        passed = value > 0.5
        return CheckResult(
            check_number=self.num,
            name=self.name,
            value=float(value),
            threshold=0.5,
            passed=passed,
            signal="strong" if passed else "weak",
            interpretation=f"{self.name} = {value}",
        )


def test_scoring_same_ctx_same_as_of_same_result() -> None:
    framework = ScoringFramework(
        checks=[
            _DeterministicCheck(1, "A", "a"),
            _DeterministicCheck(2, "B", "b"),
        ]
    )
    ctx = ScoringContext(ticker="TICK", fundamentals={"a": 0.9, "b": 0.1})
    as_of = date(2025, 1, 15)
    a = framework.score(ctx, as_of=as_of)
    b = framework.score(ctx, as_of=as_of)

    assert a.subject == b.subject
    assert a.total_passed == b.total_passed
    assert a.total_evaluated == b.total_evaluated
    assert a.total_checks == b.total_checks
    assert a.tier == b.tier
    assert [c.to_dict() for c in a.checks] == [c.to_dict() for c in b.checks]
    # Explanation should also be deterministic.
    assert a.explanation is not None and b.explanation is not None
    assert a.explanation.to_dict() == b.explanation.to_dict()


def test_scoring_echoes_as_of() -> None:
    framework = ScoringFramework(checks=[_DeterministicCheck(1, "A", "a")])
    ctx = ScoringContext(ticker="TICK", fundamentals={"a": 0.9})
    result = framework.score(ctx, as_of=date(2025, 1, 15))
    assert result.as_of == date(2025, 1, 15)


def test_scoring_as_of_default_is_none() -> None:
    framework = ScoringFramework(checks=[_DeterministicCheck(1, "A", "a")])
    ctx = ScoringContext(ticker="TICK", fundamentals={"a": 0.9})
    result = framework.score(ctx)
    assert result.as_of is None
