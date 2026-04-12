# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Confidence tier enumeration and classification logic.

A tier is a compressed summary of an N-check scoring result: rather than
exposing the raw pass count, users see an interpretable label. The default
thresholds target an 8-check framework but the ``classify_tier`` helper is
parametric.

The tier labels are deliberately probabilistic — "High Confidence" rather
than "Buy" — to keep language aligned with SEC Rule 206(4)-1 (the Marketing
Rule). A quantitative score is not advice.
"""

from __future__ import annotations

from enum import Enum


class ConfidenceTier(str, Enum):
    """Confidence tiers mapped from raw check counts.

    Defaults assume 8 checks. The ``classify_tier`` function takes total
    check count as an argument so other sizes work too.
    """

    HIGH = "HIGH CONFIDENCE"
    MODERATE = "MODERATE CONFIDENCE"
    LOW = "LOW CONFIDENCE"
    BELOW = "BELOW THRESHOLD"
    NOT_APPLICABLE = "NOT APPLICABLE"


def classify_tier(
    checks_passed: int,
    total_checks: int = 8,
    *,
    not_applicable: bool = False,
    high_fraction: float = 0.75,
    moderate_fraction: float = 0.5,
    low_fraction: float = 0.375,
) -> ConfidenceTier:
    """Map (passed, total) to a tier.

    Default cutoffs for 8 checks:
        - HIGH: 6-8 passed (>=75%)
        - MODERATE: 4-5 passed (>=50%)
        - LOW: 3 passed (>=37.5%)
        - BELOW: 0-2 passed

    Pass ``not_applicable=True`` for assets where the framework doesn't apply
    (e.g., cash, certain alternatives).
    """
    if not_applicable:
        return ConfidenceTier.NOT_APPLICABLE
    if total_checks <= 0:
        return ConfidenceTier.BELOW

    ratio = checks_passed / total_checks
    if ratio >= high_fraction:
        return ConfidenceTier.HIGH
    if ratio >= moderate_fraction:
        return ConfidenceTier.MODERATE
    if ratio >= low_fraction:
        return ConfidenceTier.LOW
    return ConfidenceTier.BELOW


__all__ = ["ConfidenceTier", "classify_tier"]
