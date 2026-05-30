# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Retirement / decumulation planning engine.

Pure, deterministic planning math — no I/O, no market data, no client context.
Each function takes plain numbers and returns plain data, so the same core is
reusable across the MCP tool gateway, the REST surface, and tests.

Educational scenario analysis only — not investment advice, not a projection of
any specific person's outcome.
"""

from .glide_path import GlidePathShape, compute_glide_path

__all__ = ["GlidePathShape", "compute_glide_path"]
