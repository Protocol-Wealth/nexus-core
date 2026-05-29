# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Financial-statement primitives and analysis.

Wraps and re-exposes calculations over financial statements: ratios,
valuation models (DCF / CAPM / WACC / DuPont / Altman Z), risk-adjusted
performance metrics, and tail-risk (VaR / CVaR / drawdown). The math is
license-clean Python — pure functions over ``StatementBundle`` value
objects with no third-party dep on the import path.

For the heavier statement-fetch + ratio-panel computation, install the
``[financials]`` extra::

    pip install nexus-core[financials]

That pulls in `JerBouma/FinanceToolkit` (MIT) — see
``adapter.from_finance_toolkit()`` to convert a ``Toolkit`` instance
into our ``StatementBundle`` shape.

Attribution:
    FinanceToolkit — Copyright (c) 2025 Jeroen Bouma (MIT).
    https://github.com/JerBouma/FinanceToolkit
"""

from __future__ import annotations

from .models import (
    altman_z_score,
    capm_expected_return,
    dcf_value,
    dupont_five_step,
    dupont_three_step,
    wacc,
)
from .performance import (
    PerformanceMetrics,
    alpha_beta,
    information_ratio,
    sharpe_ratio,
    treynor_ratio,
)
from .ratios import (
    EfficiencyRatios,
    LiquidityRatios,
    ProfitabilityRatios,
    RatioPanel,
    SolvencyRatios,
    ValuationRatios,
    efficiency,
    liquidity,
    profitability,
    solvency,
    valuation,
)
from .risk import (
    RiskMetrics,
    cornish_fisher_var,
    cvar_historical,
    downside_volatility,
    gaussian_var,
    historical_var,
    max_drawdown,
)
from .statements import (
    BalanceSheet,
    CashFlowStatement,
    IncomeStatement,
    Period,
    StatementBundle,
    StatisticsStatement,
)

__all__ = [
    # Statements
    "Period",
    "IncomeStatement",
    "BalanceSheet",
    "CashFlowStatement",
    "StatisticsStatement",
    "StatementBundle",
    # Ratios
    "RatioPanel",
    "LiquidityRatios",
    "SolvencyRatios",
    "EfficiencyRatios",
    "ProfitabilityRatios",
    "ValuationRatios",
    "liquidity",
    "solvency",
    "efficiency",
    "profitability",
    "valuation",
    # Models
    "altman_z_score",
    "capm_expected_return",
    "dcf_value",
    "dupont_three_step",
    "dupont_five_step",
    "wacc",
    # Performance
    "PerformanceMetrics",
    "alpha_beta",
    "information_ratio",
    "sharpe_ratio",
    "treynor_ratio",
    # Risk
    "RiskMetrics",
    "cornish_fisher_var",
    "cvar_historical",
    "downside_volatility",
    "gaussian_var",
    "historical_var",
    "max_drawdown",
]
