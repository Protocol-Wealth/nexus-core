# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Scoring Framework.

Multi-dimensional scoring with confidence tiers, pluggable checks, and
post-processing enhancements (consistency, base rate anchor, adversarial
brief). Methodology rooted in the durability-scoring literature: see
``attribution.py`` for full citations. Defensive patent: USPTO #64/034,229.

Quick start — the classic 8-check pattern::

    from nexus_core.engine.scoring import (
        ScoringFramework,
        consistency_enhancement,
        base_rate_enhancement,
        adversarial_brief_enhancement,
        format_structured,
    )

    framework = ScoringFramework(
        checks=[CROICCheck(), FScoreCheck(), HurstCheck(), LambdaCheck(),
                PerezCheck(), RegimeCheck(), SectorCheck(), StructuralCheck()],
        enhancements=[
            consistency_enhancement,
            base_rate_enhancement,
            adversarial_brief_enhancement,
        ],
    )

    result = framework.score(ctx)
    print(format_structured(result))

You bring the check implementations; the framework handles the orchestration,
tier classification, and output formatting.
"""

from __future__ import annotations

from .attribution import CHECK_METADATA, CheckMetadata, get_metadata, register_metadata
from .checks import Check, CheckResult, ScoringContext
from .enhancements import (
    DEFAULT_BASE_RATE_MAINTENANCE,
    adversarial_brief_enhancement,
    base_rate_enhancement,
    consistency_enhancement,
)
from .formatter import format_advisor, format_public, format_structured
from .framework import Enhancement, ScoreResult, ScoringFramework
from .tiers import ConfidenceTier, classify_tier

__all__ = [
    # Attribution
    "CHECK_METADATA",
    "CheckMetadata",
    "get_metadata",
    "register_metadata",
    # Checks
    "Check",
    "CheckResult",
    "ScoringContext",
    # Framework
    "Enhancement",
    "ScoreResult",
    "ScoringFramework",
    # Tiers
    "ConfidenceTier",
    "classify_tier",
    # Enhancements
    "DEFAULT_BASE_RATE_MAINTENANCE",
    "adversarial_brief_enhancement",
    "base_rate_enhancement",
    "consistency_enhancement",
    # Formatters
    "format_advisor",
    "format_public",
    "format_structured",
]
