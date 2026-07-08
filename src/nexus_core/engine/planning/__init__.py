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
from .healthcare import (
    LongTermCareShock,
    ltc_shock_cost_by_age,
    ltc_shock_schedule,
    ltc_shock_summary,
    make_ltc_shock,
)
from .historical_blend import HISTORICAL_BLEND_DISCLAIMER, historical_blend
from .income_layering import IncomeStream, SocialSecurityIncome, income_layering
from .inherited_ira import (
    BENEFICIARY_TYPES,
    STRATEGIES,
    BeneficiaryType,
    InheritedIraStrategy,
    classify_inherited_ira_beneficiary,
    inherited_ira_analysis,
    inherited_ira_beneficiary_carveouts,
)
from .irmaa import irmaa_headroom
from .monte_carlo import GuardrailParams, monte_carlo_decumulation
from .performance import (
    FlowTiming,
    MwrCashFlow,
    TwrPeriod,
    benchmark_relative,
    fee_drag,
    money_weighted_return,
    performance_analysis,
    time_weighted_return,
)
from .rebalance import rebalance
from .regime_swr import regime_conditioned_swr
from .result_schema import (
    education_funding_result_schema,
    education_vehicle_rules_result_schema,
    historical_blend_result_schema,
    income_layering_result_schema,
    inherited_ira_analysis_result_schema,
    performance_analysis_result_schema,
    risk_profile_result_schema,
    roth_conversion_analysis_schema,
)
from .risk_metrics import risk_metrics
from .risk_profile import (
    RISK_BANDS,
    RISK_QUESTIONS,
    RiskAnswer,
    RiskBand,
    RiskProfile,
    RiskQuestion,
    risk_profile_score,
)
from .rmd import rmd
from .roth_analysis import analyze_roth_conversion, sequence_conversions
from .roth_conversion import roth_conversion
from .sequence_risk import sequence_of_returns_stress
from .social_security import household_social_security_benefits, social_security_claiming
from .state_tax import (
    StateResidencyChange,
    StateRetirementExclusion,
    StateRetirementExclusionBand,
    StateTaxEstimate,
    StateTaxRule,
    estimate_state_income_tax,
    estimate_state_income_tax_components,
    reference_state_tax_rule,
    retirement_exclusion_amount,
    state_code_for_year,
    state_tax_notes,
)
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
    "BENEFICIARY_TYPES",
    "BracketTable",
    "BeneficiaryType",
    "Direction",
    "EducationCostResult",
    "EducationCostYear",
    "EducationFundingResult",
    "EducationSavingsNeed",
    "EducationSavingsProjection",
    "EducationStudentCase",
    "EducationStudentResult",
    "EducationVehicleRule",
    "FlowTiming",
    "GlidePathShape",
    "HISTORICAL_BLEND_DISCLAIMER",
    "InfeasiblePlanError",
    "IncomeStream",
    "InheritedIraStrategy",
    "IrmaaTable",
    "IrmaaTier",
    "MwrCashFlow",
    "PlanningContract",
    "PlanningContractError",
    "RISK_BANDS",
    "RISK_QUESTIONS",
    "RiskAnswer",
    "RiskBand",
    "RiskProfile",
    "RiskQuestion",
    "RothConversionAnalysis",
    "SolvePoint",
    "SolveResult",
    "SocialSecurityIncome",
    "STRATEGIES",
    "StateConversionRule",
    "StateResidencyChange",
    "StateRetirementExclusion",
    "StateRetirementExclusionBand",
    "StateTaxEstimate",
    "StateTaxRule",
    "TwrPeriod",
    "analyze_goals",
    "analyze_roth_conversion",
    "benchmark_relative",
    "bracket_headroom",
    "budget_pacing_projection",
    "compute_glide_path",
    "GuardrailParams",
    "cash_reserve_analysis",
    "cashflow_planning_bridge",
    "classify_inherited_ira_beneficiary",
    "correlation_matrix",
    "education_cost_fv",
    "education_funding",
    "education_result_to_wire",
    "education_funding_result_schema",
    "education_savings_need",
    "education_savings_projection",
    "education_vehicle_rules_result_schema",
    "fire",
    "estimate_state_income_tax",
    "estimate_state_income_tax_components",
    "fee_drag",
    "historical_blend",
    "historical_blend_result_schema",
    "household_social_security_benefits",
    "LongTermCareShock",
    "inherited_ira_analysis",
    "inherited_ira_analysis_result_schema",
    "inherited_ira_beneficiary_carveouts",
    "irmaa_headroom",
    "income_layering",
    "income_layering_result_schema",
    "ltc_shock_cost_by_age",
    "ltc_shock_schedule",
    "ltc_shock_summary",
    "make_ltc_shock",
    "money_weighted_return",
    "monte_carlo_decumulation",
    "performance_analysis",
    "performance_analysis_result_schema",
    "planning_contract_schema",
    "portfolio_xray",
    "project_cash_flow",
    "rebalance",
    "reference_aca_situation",
    "reference_bracket_table",
    "reference_education_vehicle_rules",
    "reference_irmaa_table",
    "reference_state_tax_rule",
    "reference_state_rule",
    "retirement_exclusion_amount",
    "regime_conditioned_swr",
    "risk_metrics",
    "risk_profile_result_schema",
    "risk_profile_score",
    "rmd",
    "rmd_start_age",
    "roth_conversion",
    "roth_conversion_analysis_schema",
    "sequence_conversions",
    "sequence_of_returns_stress",
    "social_security_claiming",
    "solve_integer_monotone",
    "solve_monotone",
    "state_code_for_year",
    "state_tax_notes",
    "tax_aware_withdrawal",
    "time_weighted_return",
]
