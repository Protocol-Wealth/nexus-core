# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Retirement / decumulation planning engine.

Pure, deterministic planning math — no I/O, no market data, no client context.
Each function takes plain numbers and returns plain data, so the same core is
reusable across the MCP tool gateway, the REST surface, and tests.

Educational scenario analysis only — not investment advice, not a projection of
any specific person's outcome.
"""

from .correlation import correlation_matrix
from .glide_path import GlidePathShape, compute_glide_path
from .monte_carlo import monte_carlo_decumulation
from .roth_conversion import roth_conversion
from .sequence_risk import sequence_of_returns_stress
from .tax import InfeasiblePlanError, tax_aware_withdrawal

__all__ = [
    "GlidePathShape",
    "InfeasiblePlanError",
    "compute_glide_path",
    "correlation_matrix",
    "monte_carlo_decumulation",
    "roth_conversion",
    "sequence_of_returns_stress",
    "tax_aware_withdrawal",
]
