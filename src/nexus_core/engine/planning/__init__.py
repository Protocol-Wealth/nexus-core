# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Retirement / decumulation planning engine.

Pure, deterministic planning math — no I/O, no market data, no client context.
Each function takes plain numbers and returns plain data, so the same core is
reusable across the MCP tool gateway, the REST surface, and tests.

Educational scenario analysis only — not investment advice, not a projection of
any specific person's outcome.
"""

from .analysis import RothConversionAnalysis
from .bracket_headroom import bracket_headroom
from .case import (
    PLANNING_CONTRACT_VERSION,
    PlanningContract,
    PlanningContractError,
    planning_contract_schema,
)
from .cash_flow_projection import project_cash_flow
from .cashflow_bridge import (
    budget_pacing_projection,
    cash_reserve_analysis,
    cashflow_planning_bridge,
)
from .correlation import correlation_matrix
from .education import (
    EducationCostResult,
    EducationCostYear,
    EducationFundingResult,
    EducationSavingsNeed,
    EducationSavingsProjection,
    EducationStudentCase,
    EducationStudentResult,
    education_cost_fv,
    education_funding,
    education_result_to_wire,
    education_savings_need,
    education_savings_projection,
)
from .fire import fire
from .glide_path import GlidePathShape, compute_glide_path
from .goal_solve import (
    Direction,
    SolvePoint,
    SolveResult,
    solve_integer_monotone,
    solve_monotone,
)
from .goals import GOAL_KINDS, analyze_goals
from .historical_blend import HISTORICAL_BLEND_DISCLAIMER, historical_blend
from .income_layering import IncomeStream, SocialSecurityIncome, income_layering
from .irmaa import irmaa_headroom
from .monte_carlo import GuardrailParams, monte_carlo_decumulation
from .rebalance import rebalance
from .regime_swr import regime_conditioned_swr
from .result_schema import (
    education_funding_result_schema,
    education_vehicle_rules_result_schema,
    historical_blend_result_schema,
    income_layering_result_schema,
    roth_conversion_analysis_schema,
)
from .risk_metrics import risk_metrics
from .rmd import rmd
from .roth_analysis import analyze_roth_conversion, sequence_conversions
from .roth_conversion import roth_conversion
from .sequence_risk import sequence_of_returns_stress
from .social_security import social_security_claiming
from .tables import (
    AcaSituation,
    BracketTable,
    EducationVehicleRule,
    IrmaaTable,
    IrmaaTier,
    StateConversionRule,
    reference_aca_situation,
    reference_bracket_table,
    reference_education_vehicle_rules,
    reference_irmaa_table,
    reference_state_rule,
)
from .tax import InfeasiblePlanError, rmd_start_age, tax_aware_withdrawal
from .xray import portfolio_xray

__all__ = [
    "GOAL_KINDS",
    "PLANNING_CONTRACT_VERSION",
    "AcaSituation",
    "BracketTable",
    "Direction",
    "EducationCostResult",
    "EducationCostYear",
    "EducationFundingResult",
    "EducationSavingsNeed",
    "EducationSavingsProjection",
    "EducationStudentCase",
    "EducationStudentResult",
    "EducationVehicleRule",
    "GlidePathShape",
    "HISTORICAL_BLEND_DISCLAIMER",
    "InfeasiblePlanError",
    "IncomeStream",
    "IrmaaTable",
    "IrmaaTier",
    "PlanningContract",
    "PlanningContractError",
    "RothConversionAnalysis",
    "SolvePoint",
    "SolveResult",
    "SocialSecurityIncome",
    "StateConversionRule",
    "analyze_goals",
    "analyze_roth_conversion",
    "bracket_headroom",
    "budget_pacing_projection",
    "compute_glide_path",
    "GuardrailParams",
    "cash_reserve_analysis",
    "cashflow_planning_bridge",
    "correlation_matrix",
    "education_cost_fv",
    "education_funding",
    "education_result_to_wire",
    "education_funding_result_schema",
    "education_savings_need",
    "education_savings_projection",
    "education_vehicle_rules_result_schema",
    "fire",
    "historical_blend",
    "historical_blend_result_schema",
    "irmaa_headroom",
    "income_layering",
    "income_layering_result_schema",
    "monte_carlo_decumulation",
    "planning_contract_schema",
    "portfolio_xray",
    "project_cash_flow",
    "rebalance",
    "reference_aca_situation",
    "reference_bracket_table",
    "reference_education_vehicle_rules",
    "reference_irmaa_table",
    "reference_state_rule",
    "regime_conditioned_swr",
    "risk_metrics",
    "rmd",
    "rmd_start_age",
    "roth_conversion",
    "roth_conversion_analysis_schema",
    "sequence_conversions",
    "sequence_of_returns_stress",
    "social_security_claiming",
    "solve_integer_monotone",
    "solve_monotone",
    "tax_aware_withdrawal",
]
