# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Protocol Wealth's 8-check EMF durability framework.

Concrete :class:`~nexus_core.engine.scoring.checks.Check` implementations,
ported faithfully from the Protocol Wealth research engine. EMF is an openly
published framework (https://protocolwealthllc.com/framework), so these checks
and their thresholds are public.

The eight checks (in order):

1. :class:`CROICCheck` — Cash Return on Invested Capital > 8%.
2. :class:`FScoreCheck` — Piotroski F-Score >= 6/9.
3. :class:`HurstCheck` — Hurst exponent > 0.55 (trend persistence).
4. :class:`LambdaCheck` — entropic decay constant below a layer-adjusted bound.
5. :class:`PerezPhaseCheck` — techno-economic cycle in Installation/Deployment.
6. :class:`RegimeAlignmentCheck` — durability-layer weight >= 15% in the regime.
7. :class:`SectorTailwindCheck` — sector outperforming the broad market (~3mo).
8. :class:`ASANScreenCheck` — structural-advantage / AI-disruption resilience.

Checks 1-3 evaluate from ``fundamentals`` + ``prices`` already available in a
:class:`~nexus_core.engine.scoring.checks.ScoringContext`. Checks 4-8 require
additional upstream context (a durability-layer assignment, a Perez phase, the
regime code + layer-weight table, sector returns, ASAN inputs); each degrades to
``passed=None`` (``signal="insufficient_data"``) when that context is absent, so
the full set is safe to register today. Use ``total_checks_override=8`` on the
framework so tier classification is calibrated to all eight regardless of how
many evaluated.

ASAN (Check 8) classifies the subject into a scoring bucket — SaaS, or one of
the non-SaaS sector buckets (semiconductor, financial, healthcare, consumer,
industrial, energy, technology_hardware, communication, materials, utilities,
real_estate). A sector/industry that matches no bucket is **not evaluated**
(``passed=None``) — never auto-passed — so an unmapped name can never inflate
the pass count or earn a stronger confidence tier than its evaluable checks
support (fail-safe; "never silently default").

All outputs are for educational and research purposes only — not individualized
investment advice.
"""

from __future__ import annotations

from ..checks import Check
from .croic import CROICCheck, compute_croic
from .fscore import FScoreCheck, compute_fscore
from .hurst import HurstCheck, compute_hurst
from .lambda_decay import LambdaCheck, compute_lambda
from .perez import PerezPhaseCheck, compute_perez_phase
from .regime_alignment import RegimeAlignmentCheck, regime_layer_weight
from .sector_tailwind import SectorTailwindCheck, compute_period_return, sector_etf_for
from .structural_advantage import ASANScreenCheck, classify_sector


def protocol_wealth_checks() -> list[Check]:
    """Return the 8 EMF checks as fresh instances, in canonical order.

    Pair with ``ScoringFramework(checks=protocol_wealth_checks(),
    total_checks_override=8)`` so tier boundaries stay calibrated to the
    full 8-check framework even when some checks report ``insufficient_data``.
    """
    return [
        CROICCheck(),
        FScoreCheck(),
        HurstCheck(),
        LambdaCheck(),
        PerezPhaseCheck(),
        RegimeAlignmentCheck(),
        SectorTailwindCheck(),
        ASANScreenCheck(),
    ]


__all__ = [
    "ASANScreenCheck",
    "CROICCheck",
    "FScoreCheck",
    "HurstCheck",
    "LambdaCheck",
    "PerezPhaseCheck",
    "RegimeAlignmentCheck",
    "SectorTailwindCheck",
    "classify_sector",
    "compute_croic",
    "compute_fscore",
    "compute_hurst",
    "compute_lambda",
    "compute_perez_phase",
    "compute_period_return",
    "protocol_wealth_checks",
    "regime_layer_weight",
    "sector_etf_for",
]
