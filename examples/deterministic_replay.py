# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Worked example: deterministic replay against frozen synthetic signals.

Runs the regime classifier twice against the SAME synthetic signals with the
SAME ``as_of`` date, then asserts the two results are byte-identical when
serialized. This is the property the public surface needs to satisfy for an
SEC exam workflow: classifying "as of" a date in the past should be
reproducible exactly from the frozen input snapshot.

Run it directly::

    python examples/deterministic_replay.py

Expected output: a JSON dump of the result plus the line
``replay OK: results are byte-identical``.

This example uses synthetic placeholder signal values so it has zero data
dependencies (no network, no API keys).
"""

from __future__ import annotations

import json
from datetime import date

from nexus_core.engine.regime.classifier import RegimeClassifier
from nexus_core.engine.regime.signals import RegimeSignals
from nexus_core.engine.scoring import (
    CheckResult,
    ScoringContext,
    ScoringFramework,
)


def synthetic_signals() -> RegimeSignals:
    """Hard-coded, regime-neutral synthetic signals — for example use only."""
    return RegimeSignals(
        gold_spx_ratio=4.0,
        gold_spx_200wma=3.8,
        gold_spx_vs_wma="above",
        real_rates=1.5,
        dxy=104.0,
        vix=15.0,
        credit_spreads=120.0,
    )


class _ToyCheck:
    """Minimal deterministic check; reads from ``ctx.fundamentals``."""

    def __init__(self, num: int, name: str, key: str) -> None:
        self.num = num
        self.name = name
        self.key = key

    def __call__(self, ctx: object) -> CheckResult:
        fundamentals = getattr(ctx, "fundamentals", {}) or {}
        v = float(fundamentals.get(self.key, 0.0))
        passed = v > 0.5
        return CheckResult(
            check_number=self.num,
            name=self.name,
            value=v,
            threshold=0.5,
            passed=passed,
            signal="strong" if passed else "weak",
            interpretation=f"{self.name}={v}",
        )


def replay_regime(as_of: date) -> None:
    classifier = RegimeClassifier()
    signals = synthetic_signals()
    first = classifier.classify(signals, as_of=as_of)
    second = classifier.classify(signals, as_of=as_of)

    first_json = json.dumps(first.to_dict(), sort_keys=True)
    second_json = json.dumps(second.to_dict(), sort_keys=True)

    print("--- Regime replay ---")
    print(json.dumps(first.to_dict(), indent=2, sort_keys=True))
    if first_json == second_json:
        print("replay OK: regime classification is byte-identical across calls\n")
    else:
        raise AssertionError("regime replay diverged — classifier is not pure on these inputs")


def replay_scoring(as_of: date) -> None:
    framework = ScoringFramework(
        checks=[
            _ToyCheck(1, "A", "a"),
            _ToyCheck(2, "B", "b"),
            _ToyCheck(3, "C", "c"),
        ]
    )
    ctx = ScoringContext(
        ticker="SYNTH",
        fundamentals={"a": 0.9, "b": 0.1, "c": 0.7},
    )
    first = framework.score(ctx, as_of=as_of)
    second = framework.score(ctx, as_of=as_of)

    first_json = json.dumps(first.to_dict(), sort_keys=True, default=str)
    second_json = json.dumps(second.to_dict(), sort_keys=True, default=str)

    print("--- Scoring replay ---")
    print(json.dumps(first.to_dict(), indent=2, sort_keys=True, default=str))
    if first_json == second_json:
        print("replay OK: scoring result is byte-identical across calls\n")
    else:
        raise AssertionError("scoring replay diverged")


if __name__ == "__main__":
    replay_regime(date(2025, 1, 15))
    replay_scoring(date(2025, 1, 15))
    print("All replay assertions passed.")
