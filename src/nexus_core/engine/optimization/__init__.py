# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Portfolio Optimization.

Wraps third-party optimization libraries with regime-aware parameter
selection and MCP tool exposure.

Third-party libraries:
    - PyPortfolioOpt (MIT) — https://github.com/robertmartin8/PyPortfolioOpt
    - Riskfolio-Lib (BSD-3) — https://github.com/dcajasn/Riskfolio-Lib
    - skfolio (BSD-3) — https://github.com/skfolio/skfolio

Install with: ``pip install nexus-core[optimization]``
"""

from __future__ import annotations

try:
    from .pypfopt_wrapper import (
        REGIME_OPTIMIZER_MAP,
        OptimizationResult,
        optimize,
        optimize_for_regime,
    )

    __all__ = [
        "REGIME_OPTIMIZER_MAP",
        "OptimizationResult",
        "optimize",
        "optimize_for_regime",
    ]
except ImportError:  # pragma: no cover
    __all__ = []
