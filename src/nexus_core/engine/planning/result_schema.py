# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""JSON-Schema helpers for planning outputs.

The output half of the planning ABI is as load-bearing as the input. Rather than
hand-maintain a second JSON file that could silently drift from
:mod:`.analysis`, this module *generates* the Draft-2020-12 schema directly from
the result dataclasses — so the dataclasses remain the single source of truth and
drift is structurally impossible. ``pw-api`` (and any adopter) can validate engine
responses against :func:`roth_conversion_analysis_schema`.

Handles exactly the type vocabulary the result dataclasses use: nested
dataclasses, the JSON primitives (``int``/``float``/``str``/``bool``),
``tuple[T, ...]`` homogeneous arrays, and ``T | None`` optionals. It deliberately
does not implement a general type→schema mapping.
"""

from __future__ import annotations

import dataclasses
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

from .analysis import RothConversionAnalysis

_PRIMITIVES: dict[type, str] = {
    bool: "boolean",  # before int: bool is a subclass of int
    int: "integer",
    float: "number",
    str: "string",
}


def _is_optional(annotation: Any) -> tuple[bool, Any]:
    """If ``annotation`` is ``X | None``, return ``(True, X)``; else ``(False, ann)``."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1 and len(get_args(annotation)) == 2:
            return True, args[0]
    return False, annotation


def _allow_null(schema: dict[str, Any]) -> dict[str, Any]:
    """Widen a generated schema to also permit ``null``."""
    t = schema.get("type")
    if isinstance(t, str):
        return {**schema, "type": [t, "null"]}
    return {"anyOf": [schema, {"type": "null"}]}


def _type_to_schema(annotation: Any) -> dict[str, Any]:
    optional, inner = _is_optional(annotation)
    if optional:
        return _allow_null(_type_to_schema(inner))

    if dataclasses.is_dataclass(inner) and isinstance(inner, type):
        return _dataclass_to_schema(inner)

    origin = get_origin(inner)
    if origin is tuple:
        args = get_args(inner)
        if len(args) == 2 and args[1] is Ellipsis:
            return {"type": "array", "items": _type_to_schema(args[0])}
        raise TypeError(f"only homogeneous tuple[T, ...] is supported, got {inner!r}")

    if inner in _PRIMITIVES:
        return {"type": _PRIMITIVES[inner]}

    raise TypeError(f"unsupported annotation in result schema: {inner!r}")


def _dataclass_to_schema(cls: type) -> dict[str, Any]:
    hints = get_type_hints(cls)
    properties = {f.name: _type_to_schema(hints[f.name]) for f in dataclasses.fields(cls)}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def roth_conversion_analysis_schema() -> dict[str, Any]:
    """Draft-2020-12 JSON-Schema for :class:`RothConversionAnalysis`."""
    schema = _dataclass_to_schema(RothConversionAnalysis)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://nexusmcp.site/schemas/roth-conversion-analysis-1.1.0.json"
    schema["title"] = "RothConversionAnalysis"
    schema["description"] = (
        "PII-free output of analyze_roth_conversion / sequence_conversions. "
        "Generated from the nexus-core result dataclasses (single source of truth)."
    )
    return schema


_MONEY = {"type": "number"}
_NULLABLE_MONEY = {"type": ["number", "null"]}
_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}
_SUBJECT_REF_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": 80,
    "pattern": "^[A-Za-z0-9._:-]+$",
}


def education_funding_result_schema() -> dict[str, Any]:
    """Draft-2020-12 JSON-Schema for the ``education_funding`` wire result."""

    money_need = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "targetFv",
            "currentSavings",
            "afterTaxReturn",
            "yearsUntilStart",
            "monthly",
            "annual",
            "lumpSum",
        ],
        "properties": {
            "targetFv": _MONEY,
            "currentSavings": _MONEY,
            "afterTaxReturn": _MONEY,
            "yearsUntilStart": {"type": "integer"},
            "monthly": _MONEY,
            "annual": _MONEY,
            "lumpSum": _MONEY,
        },
    }
    cost_schedule_row = {
        "type": "object",
        "additionalProperties": False,
        "required": ["yearIndex", "yearsFromNow", "cost", "costAtGoalStart"],
        "properties": {
            "yearIndex": {"type": "integer"},
            "yearsFromNow": {"type": "integer"},
            "cost": _MONEY,
            "costAtGoalStart": _MONEY,
        },
    }
    cost = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "annualCost",
            "tuitionInflation",
            "yearsUntilStart",
            "fundingYears",
            "firstYearCost",
            "totalFutureCost",
            "totalCostAtGoalStart",
            "costSchedule",
        ],
        "properties": {
            "annualCost": _MONEY,
            "tuitionInflation": _MONEY,
            "yearsUntilStart": {"type": "integer"},
            "fundingYears": {"type": "integer"},
            "firstYearCost": _MONEY,
            "totalFutureCost": _MONEY,
            "totalCostAtGoalStart": _MONEY,
            "costSchedule": {"type": "array", "items": cost_schedule_row},
        },
    }
    student = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "subjectRef",
            "cost",
            "projectedSavingsAtStart",
            "savingsGapAtStart",
            "savingsNeed",
        ],
        "properties": {
            "subjectRef": _SUBJECT_REF_SCHEMA,
            "cost": cost,
            "projectedSavingsAtStart": _MONEY,
            "savingsGapAtStart": _MONEY,
            "savingsNeed": money_need,
        },
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://nexusmcp.site/schemas/education-funding-result-0.1.0.json",
        "title": "EducationFundingResult",
        "description": "PII-free output of the education_funding planning tool.",
        "type": "object",
        "additionalProperties": False,
        "required": ["tuitionInflation", "afterTaxReturn", "students", "householdTotals"],
        "properties": {
            "tuitionInflation": _MONEY,
            "afterTaxReturn": _MONEY,
            "students": {"type": "array", "items": student},
            "householdTotals": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "totalFutureCost",
                    "totalCostAtGoalStart",
                    "projectedSavingsAtStart",
                    "savingsGapAtStart",
                    "savingsNeed",
                ],
                "properties": {
                    "totalFutureCost": _MONEY,
                    "totalCostAtGoalStart": _MONEY,
                    "projectedSavingsAtStart": _MONEY,
                    "savingsGapAtStart": _MONEY,
                    "savingsNeed": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["monthly", "annual", "lumpSum"],
                        "properties": {
                            "monthly": _MONEY,
                            "annual": _MONEY,
                            "lumpSum": _MONEY,
                        },
                    },
                },
            },
        },
    }
    return schema


def education_vehicle_rules_result_schema() -> dict[str, Any]:
    """Draft-2020-12 JSON-Schema for the ``education_vehicle_rules`` wire result."""

    rule = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "taxYear",
            "vehicle",
            "label",
            "contributionLimit",
            "annualGiftExclusion",
            "fiveYearSuperfundingSingle",
            "fiveYearSuperfundingMarriedJoint",
            "magiPhaseoutSingle",
            "magiPhaseoutMarriedJoint",
            "qualifiedDistributionTreatment",
            "nonqualifiedDistributionPenaltyRate",
            "notes",
            "tableVersion",
        ],
        "properties": {
            "taxYear": {"type": "integer"},
            "vehicle": {"type": "string"},
            "label": {"type": "string"},
            "contributionLimit": _NULLABLE_MONEY,
            "annualGiftExclusion": _NULLABLE_MONEY,
            "fiveYearSuperfundingSingle": _NULLABLE_MONEY,
            "fiveYearSuperfundingMarriedJoint": _NULLABLE_MONEY,
            "magiPhaseoutSingle": {
                "type": ["array", "null"],
                "prefixItems": [_MONEY, _MONEY],
                "minItems": 2,
                "maxItems": 2,
            },
            "magiPhaseoutMarriedJoint": {
                "type": ["array", "null"],
                "prefixItems": [_MONEY, _MONEY],
                "minItems": 2,
                "maxItems": 2,
            },
            "qualifiedDistributionTreatment": {"type": "string"},
            "nonqualifiedDistributionPenaltyRate": _NULLABLE_MONEY,
            "notes": _STRING_ARRAY,
            "tableVersion": {"type": "string"},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://nexusmcp.site/schemas/education-vehicle-rules-result-0.1.0.json",
        "title": "EducationVehicleRulesResult",
        "description": "PII-free output of the education_vehicle_rules planning tool.",
        "type": "object",
        "additionalProperties": False,
        "required": ["taxYear", "tableVersion", "rules"],
        "properties": {
            "taxYear": {"type": "integer"},
            "tableVersion": {"type": "string"},
            "rules": {"type": "array", "items": rule},
        },
    }


def income_layering_result_schema() -> dict[str, Any]:
    """Draft-2020-12 JSON-Schema for the ``income_layering`` wire result."""

    account_balances = {
        "type": "object",
        "additionalProperties": False,
        "required": ["taxable", "traditional", "roth"],
        "properties": {"taxable": _MONEY, "traditional": _MONEY, "roth": _MONEY},
    }
    layer = {
        "type": "object",
        "additionalProperties": False,
        "required": ["source", "gross", "tax", "net"],
        "properties": {
            "source": {"type": "string"},
            "gross": _MONEY,
            "tax": _MONEY,
            "net": _MONEY,
        },
    }
    year = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "age",
            "year",
            "spendingTarget",
            "layers",
            "totalGross",
            "totalTax",
            "netIncome",
            "gap",
            "surplusAfterTax",
            "effectiveTaxRate",
            "endingAccountBalances",
        ],
        "properties": {
            "age": {"type": "integer"},
            "year": {"type": "integer"},
            "spendingTarget": _MONEY,
            "layers": {"type": "array", "items": layer},
            "totalGross": _MONEY,
            "totalTax": _MONEY,
            "netIncome": _MONEY,
            "gap": _MONEY,
            "surplusAfterTax": _MONEY,
            "effectiveTaxRate": _MONEY,
            "endingAccountBalances": account_balances,
            "bracketHeadroom": {"type": "object"},
        },
    }
    source_total = {
        "type": "object",
        "additionalProperties": False,
        "required": ["gross", "tax", "net"],
        "properties": {"gross": _MONEY, "tax": _MONEY, "net": _MONEY},
    }
    rollups = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "projectionYears",
            "currentAge",
            "terminalAge",
            "retirementAge",
            "totalSpendingTarget",
            "totalGrossIncome",
            "totalTax",
            "totalNetIncome",
            "totalGap",
            "totalSurplusAfterTax",
            "firstGapAge",
            "startingAccountBalances",
            "endingAccountBalances",
            "sourceTotals",
            "rmdStartAge",
            "rmdStartAgePolicyVersion",
        ],
        "properties": {
            "projectionYears": {"type": "integer"},
            "currentAge": {"type": "integer"},
            "terminalAge": {"type": "integer"},
            "retirementAge": {"type": "integer"},
            "totalSpendingTarget": _MONEY,
            "totalGrossIncome": _MONEY,
            "totalTax": _MONEY,
            "totalNetIncome": _MONEY,
            "totalGap": _MONEY,
            "totalSurplusAfterTax": _MONEY,
            "firstGapAge": {"type": ["integer", "null"]},
            "startingAccountBalances": account_balances,
            "endingAccountBalances": account_balances,
            "sourceTotals": {"type": "object", "additionalProperties": source_total},
            "rmdStartAge": _MONEY,
            "rmdStartAgePolicyVersion": {"type": "string"},
        },
    }
    assumptions = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "filingStatus",
            "taxTableYear",
            "taxTableVersion",
            "spendingInflationRate",
            "wageGrowthRate",
            "expectedReturn",
            "accountReturns",
            "withdrawalOrder",
            "socialSecurityClaimAge",
            "socialSecurityFraAge",
            "bracketFillTargetRate",
        ],
        "properties": {
            "filingStatus": {"type": "string"},
            "taxTableYear": {"type": "integer"},
            "taxTableVersion": {"type": "string"},
            "spendingInflationRate": _MONEY,
            "wageGrowthRate": _MONEY,
            "expectedReturn": _MONEY,
            "accountReturns": account_balances,
            "withdrawalOrder": _STRING_ARRAY,
            "socialSecurityClaimAge": {"type": ["integer", "null"]},
            "socialSecurityFraAge": {"type": ["integer", "null"]},
            "bracketFillTargetRate": {"type": ["number", "null"]},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://nexusmcp.site/schemas/income-layering-result-0.1.0.json",
        "title": "IncomeLayeringResult",
        "description": "PII-free output of the income_layering planning tool.",
        "type": "object",
        "additionalProperties": False,
        "required": ["years", "rollups", "assumptions"],
        "properties": {
            "years": {"type": "array", "items": year},
            "rollups": rollups,
            "assumptions": assumptions,
        },
    }


__all__ = [
    "education_funding_result_schema",
    "education_vehicle_rules_result_schema",
    "income_layering_result_schema",
    "roth_conversion_analysis_schema",
]
