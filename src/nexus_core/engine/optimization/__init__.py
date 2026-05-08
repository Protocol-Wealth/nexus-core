# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Portfolio Optimization.

Wraps PyPortfolioOpt (MIT, primary) and Riskfolio-Lib (BSD-3,
supplementary) behind a unified surface. PyPortfolioOpt provides clean
ergonomics for the 80% case — MVO, max-Sharpe, min-volatility,
Black-Litterman, discrete allocation. Riskfolio-Lib handles the
long tail — risk parity with 24+ risk measures, hierarchical risk
parity with rich RMs, CVaR / CDaR / EVaR optimization, factor-RC
constraints, worst-case MVO.

Twelve entry points:

    optimize, max_sharpe, min_volatility, target_return, target_risk,
    hrp, risk_parity, hierarchical_risk_parity, min_cvar,
    black_litterman_posterior, discrete_allocate, optimize_for_regime

Each backend is lazily imported — calling a function that needs
PyPortfolioOpt or Riskfolio raises a clear ImportError with the install
hint if the optional ``[optimization]`` extra isn't installed. The
import of this module itself does not require either library.

Third-party libraries:
    - PyPortfolioOpt (MIT) — https://github.com/robertmartin8/PyPortfolioOpt
    - Riskfolio-Lib (BSD-3) — https://github.com/dcajasn/Riskfolio-Lib
    - skfolio (BSD-3) — https://github.com/skfolio/skfolio (planned)

Install with: ``pip install nexus-core[optimization]``
"""

from __future__ import annotations

# PyPortfolioOpt-backed primitives (existing wrapper)
from .pypfopt_wrapper import (
    REGIME_OPTIMIZER_MAP,
    OptimizationResult,
    optimize,
    optimize_for_regime,
)

# Black-Litterman view construction + posterior
from .black_litterman import (
    View,
    absolute_view,
    black_litterman_posterior,
    relative_view,
)

# Discrete allocation (whole-share)
from .discrete import DiscreteAllocationResult, discrete_allocate

# Riskfolio-backed primitives — risk parity, HRP-with-rich-RMs, CVaR
from .riskfolio_backend import (
    RiskfolioResult,
    hierarchical_risk_parity,
    min_cvar,
    risk_parity,
)


def max_sharpe(prices, **kwargs):  # type: ignore[no-untyped-def]
    """Convenience: run ``optimize(method='max_sharpe')``."""
    return optimize(prices, method="max_sharpe", **kwargs)


def min_volatility(prices, **kwargs):  # type: ignore[no-untyped-def]
    """Convenience: run ``optimize(method='min_volatility')``."""
    return optimize(prices, method="min_volatility", **kwargs)


def target_return(prices, target: float, **kwargs):  # type: ignore[no-untyped-def]
    """Convenience: efficient-frontier point at given target return."""
    return optimize(prices, method="efficient_return", target_return=target, **kwargs)


def target_risk(prices, target: float, **kwargs):  # type: ignore[no-untyped-def]
    """Convenience: efficient-frontier point at given target risk."""
    return optimize(prices, method="efficient_risk", target_volatility=target, **kwargs)


def hrp(prices, **kwargs):  # type: ignore[no-untyped-def]
    """Convenience: run ``optimize(method='hrp')`` (PyPortfolioOpt HRPOpt — variance only).

    For HRP with richer risk measures (CVaR, CDaR, MAD), use
    ``hierarchical_risk_parity`` (Riskfolio-backed).
    """
    return optimize(prices, method="hrp", **kwargs)


__all__ = [
    # Core surface
    "REGIME_OPTIMIZER_MAP",
    "OptimizationResult",
    "optimize",
    "optimize_for_regime",
    # Convenience entry points
    "max_sharpe",
    "min_volatility",
    "target_return",
    "target_risk",
    "hrp",
    # Riskfolio-backed
    "RiskfolioResult",
    "risk_parity",
    "hierarchical_risk_parity",
    "min_cvar",
    # Black-Litterman
    "View",
    "absolute_view",
    "relative_view",
    "black_litterman_posterior",
    # Discrete allocation
    "DiscreteAllocationResult",
    "discrete_allocate",
]
