# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Check primitives for the scoring framework.

A ``Check`` is any callable that takes a context object (e.g. a ticker plus
any supporting data) and returns a ``CheckResult``. The framework runs all
configured checks, aggregates results, and emits a ``ScoreResult``.

Users bring their own checks. This module provides the ``Check`` protocol,
the ``CheckResult`` dataclass, and a few small helpers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class CheckResult:
    """Outcome of a single check.

    Attributes:
        check_number: Ordinal (1..N) for consistent output ordering.
        name: Short internal name. See ``PUBLIC_CHECK_LABELS`` for display
            versions and ``CHECK_METADATA`` for academic source attribution.
        value: Numeric value that was evaluated (e.g., CROIC 0.12, F-Score 7).
            ``None`` when the check couldn't be evaluated (missing data).
        threshold: The threshold the value was compared against.
        passed: ``True`` if the check passed, ``False`` if it failed, ``None``
            if the check couldn't produce a verdict.
        signal: Short human-readable direction ("strong", "weak", etc.)
        interpretation: Longer human-readable explanation of the result.
        details: Arbitrary bag for check-specific metadata (sector, overrides, etc.).
    """

    check_number: int
    name: str
    value: float | None = None
    threshold: float | None = None
    passed: bool | None = None
    signal: str = ""
    interpretation: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_number": self.check_number,
            "name": self.name,
            "value": self.value,
            "threshold": self.threshold,
            "passed": self.passed,
            "signal": self.signal,
            "interpretation": self.interpretation,
            "details": self.details,
        }


@runtime_checkable
class Check(Protocol):
    """Single check in the framework.

    A check is a callable taking a context (arbitrary — typically a
    ``ScoringContext`` or ``dict``) and returning a ``CheckResult``.

    Implement as a class with ``__call__`` for checks that carry state
    (thresholds, cached lookups), or as a plain function for simple cases.

    Example::

        class CROICCheck:
            def __init__(self, threshold: float = 0.08):
                self.threshold = threshold

            def __call__(self, ctx) -> CheckResult:
                croic = ctx["fundamentals"]["croic"]
                return CheckResult(
                    check_number=1,
                    name="CROIC",
                    value=croic,
                    threshold=self.threshold,
                    passed=croic > self.threshold,
                    signal="strong" if croic > 0.15 else "weak",
                    interpretation=f"CROIC of {croic:.1%}",
                )
    """

    def __call__(self, ctx: Any) -> CheckResult:  # pragma: no cover - protocol
        ...


@dataclass
class ScoringContext:
    """Standard context bag passed to checks.

    Users can pass a plain dict instead if preferred — the Check protocol
    accepts ``Any``. This class exists to give a typed handle for the common
    case of "ticker + fundamentals + prices + regime".
    """

    ticker: str
    fundamentals: dict[str, Any] = field(default_factory=dict)
    prices: list[dict[str, Any]] = field(default_factory=list)
    regime: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


__all__ = ["Check", "CheckResult", "ScoringContext"]
