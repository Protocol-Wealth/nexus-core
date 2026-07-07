# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Education-funding planning math.

Pure, deterministic helpers for education cost inflation and savings needs.
Inputs are de-identified: ages, year offsets, costs, and opaque subject refs
only. No beneficiary identity, account metadata, storage, or provider I/O.

Educational planning illustration only, not tax, legal, investment, or
financial advice.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

_SUBJECT_REF_ALLOWED_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:-"
)


@dataclass(frozen=True, slots=True)
class EducationCostYear:
    """One education-funding year in the cost schedule."""

    year_index: int
    years_from_now: int
    cost: float
    cost_at_goal_start: float


@dataclass(frozen=True, slots=True)
class EducationCostResult:
    """Inflated education costs for one student case."""

    annual_cost: float
    tuition_inflation: float
    years_until_start: int
    funding_years: int
    first_year_cost: float
    total_future_cost: float
    total_cost_at_goal_start: float
    cost_schedule: tuple[EducationCostYear, ...]


@dataclass(frozen=True, slots=True)
class EducationSavingsProjection:
    """Future value of current savings plus level monthly contributions."""

    current_savings: float
    monthly_contribution: float
    after_tax_return: float
    years: int
    future_value: float


@dataclass(frozen=True, slots=True)
class EducationSavingsNeed:
    """Contribution/lump-sum need to reach a target future value."""

    target_fv: float
    current_savings: float
    after_tax_return: float
    years_until_start: int
    monthly: float
    annual: float
    lump_sum: float


@dataclass(frozen=True, slots=True)
class EducationStudentCase:
    """De-identified one-student input for the composite funding solver."""

    subject_ref: str
    annual_cost: float
    years_until_start: int
    funding_years: int
    current_savings: float = 0.0
    monthly_contribution: float = 0.0


@dataclass(frozen=True, slots=True)
class EducationStudentResult:
    """Per-student funding result."""

    subject_ref: str
    cost: EducationCostResult
    projected_savings_at_start: float
    savings_gap_at_start: float
    savings_need: EducationSavingsNeed


@dataclass(frozen=True, slots=True)
class EducationFundingResult:
    """Multi-student education funding result."""

    tuition_inflation: float
    after_tax_return: float
    students: tuple[EducationStudentResult, ...]
    household_totals: dict[str, float | dict[str, float]]


def _validate_money(value: float, field: str) -> None:
    if value < 0.0:
        raise ValueError(f"{field} must be non-negative")


def _validate_rate(value: float, field: str) -> None:
    if value <= -1.0:
        raise ValueError(f"{field} must be greater than -100%")


def _round_money(value: float) -> float:
    return round(value + 0.0, 2)


def _validate_subject_ref(value: str) -> None:
    if not value or len(value) > 80 or any(ch not in _SUBJECT_REF_ALLOWED_CHARS for ch in value):
        raise ValueError(
            "student subject_ref must be an opaque token of 1-80 letters, digits, '.', '_', ':', or '-'"
        )


def education_cost_fv(
    *,
    annual_cost: float,
    tuition_inflation: float,
    years_until_start: int,
    funding_years: int,
) -> EducationCostResult:
    """Inflate education costs through the funding years.

    ``annual_cost`` is today's annual cost basis. The first education year is
    inflated by ``years_until_start``. Later funding years are shown both as
    nominal future costs and as values discounted back to the goal-start year at
    the same tuition-inflation rate.
    """

    _validate_money(annual_cost, "annual_cost")
    _validate_rate(tuition_inflation, "tuition_inflation")
    if years_until_start < 0:
        raise ValueError("years_until_start must be non-negative")
    if funding_years < 1:
        raise ValueError("funding_years must be at least 1")

    growth = 1.0 + tuition_inflation
    schedule: list[EducationCostYear] = []
    total_future = 0.0
    total_at_start = 0.0
    for idx in range(funding_years):
        years_from_now = years_until_start + idx
        cost = annual_cost * (growth**years_from_now)
        cost_at_start = cost / (growth**idx)
        total_future += cost
        total_at_start += cost_at_start
        schedule.append(
            EducationCostYear(
                year_index=idx,
                years_from_now=years_from_now,
                cost=_round_money(cost),
                cost_at_goal_start=_round_money(cost_at_start),
            )
        )

    first_year = annual_cost * (growth**years_until_start)
    return EducationCostResult(
        annual_cost=_round_money(annual_cost),
        tuition_inflation=tuition_inflation,
        years_until_start=years_until_start,
        funding_years=funding_years,
        first_year_cost=_round_money(first_year),
        total_future_cost=_round_money(total_future),
        total_cost_at_goal_start=_round_money(total_at_start),
        cost_schedule=tuple(schedule),
    )


def education_savings_projection(
    *,
    current_savings: float,
    monthly_contribution: float,
    after_tax_return: float,
    years: int,
) -> EducationSavingsProjection:
    """Future value of current savings plus end-of-month contributions."""

    _validate_money(current_savings, "current_savings")
    _validate_money(monthly_contribution, "monthly_contribution")
    _validate_rate(after_tax_return, "after_tax_return")
    if years < 0:
        raise ValueError("years must be non-negative")

    months = years * 12
    monthly_rate = (1.0 + after_tax_return) ** (1.0 / 12.0) - 1.0
    if months == 0:
        fv = current_savings
    elif abs(monthly_rate) < 1e-12:
        fv = current_savings + monthly_contribution * months
    else:
        factor = (1.0 + monthly_rate) ** months
        fv = current_savings * factor + monthly_contribution * ((factor - 1.0) / monthly_rate)
    return EducationSavingsProjection(
        current_savings=_round_money(current_savings),
        monthly_contribution=_round_money(monthly_contribution),
        after_tax_return=after_tax_return,
        years=years,
        future_value=_round_money(fv),
    )


def education_savings_need(
    *,
    target_fv: float,
    current_savings: float,
    after_tax_return: float,
    years_until_start: int,
) -> EducationSavingsNeed:
    """Closed-form monthly/annual/lump-sum need to reach ``target_fv``."""

    _validate_money(target_fv, "target_fv")
    _validate_money(current_savings, "current_savings")
    _validate_rate(after_tax_return, "after_tax_return")
    if years_until_start < 0:
        raise ValueError("years_until_start must be non-negative")

    months = years_until_start * 12
    monthly_rate = (1.0 + after_tax_return) ** (1.0 / 12.0) - 1.0
    if months == 0:
        gap = max(0.0, target_fv - current_savings)
        monthly = gap
        annual = gap
        lump = gap
    elif abs(monthly_rate) < 1e-12:
        gap = max(0.0, target_fv - current_savings)
        monthly = gap / months
        lump = gap
    else:
        factor = (1.0 + monthly_rate) ** months
        future_gap = max(0.0, target_fv - current_savings * factor)
        monthly = future_gap * monthly_rate / (factor - 1.0)
        lump = max(0.0, target_fv / factor - current_savings)
    rounded_monthly = _round_money(monthly)
    rounded_annual = _round_money(annual if months == 0 else rounded_monthly * 12.0)
    return EducationSavingsNeed(
        target_fv=_round_money(target_fv),
        current_savings=_round_money(current_savings),
        after_tax_return=after_tax_return,
        years_until_start=years_until_start,
        monthly=rounded_monthly,
        annual=rounded_annual,
        lump_sum=_round_money(lump),
    )


def education_funding(
    *,
    students: list[EducationStudentCase],
    tuition_inflation: float,
    after_tax_return: float,
) -> EducationFundingResult:
    """Solve education-funding needs for one or more de-identified students."""

    if not students:
        raise ValueError("students must be non-empty")
    _validate_rate(tuition_inflation, "tuition_inflation")
    _validate_rate(after_tax_return, "after_tax_return")

    results: list[EducationStudentResult] = []
    for student in students:
        _validate_subject_ref(student.subject_ref)
        cost = education_cost_fv(
            annual_cost=student.annual_cost,
            tuition_inflation=tuition_inflation,
            years_until_start=student.years_until_start,
            funding_years=student.funding_years,
        )
        projection = education_savings_projection(
            current_savings=student.current_savings,
            monthly_contribution=student.monthly_contribution,
            after_tax_return=after_tax_return,
            years=student.years_until_start,
        )
        need = education_savings_need(
            target_fv=cost.total_cost_at_goal_start,
            current_savings=student.current_savings,
            after_tax_return=after_tax_return,
            years_until_start=student.years_until_start,
        )
        gap = max(0.0, cost.total_cost_at_goal_start - projection.future_value)
        results.append(
            EducationStudentResult(
                subject_ref=student.subject_ref,
                cost=cost,
                projected_savings_at_start=projection.future_value,
                savings_gap_at_start=_round_money(gap),
                savings_need=need,
            )
        )

    savings_need_totals: dict[str, float] = {
        "monthly": _round_money(sum(r.savings_need.monthly for r in results)),
        "annual": _round_money(sum(r.savings_need.annual for r in results)),
        "lumpSum": _round_money(sum(r.savings_need.lump_sum for r in results)),
    }
    totals: dict[str, float | dict[str, float]] = {
        "totalFutureCost": _round_money(sum(r.cost.total_future_cost for r in results)),
        "totalCostAtGoalStart": _round_money(sum(r.cost.total_cost_at_goal_start for r in results)),
        "projectedSavingsAtStart": _round_money(sum(r.projected_savings_at_start for r in results)),
        "savingsGapAtStart": _round_money(sum(r.savings_gap_at_start for r in results)),
        "savingsNeed": savings_need_totals,
    }
    return EducationFundingResult(
        tuition_inflation=tuition_inflation,
        after_tax_return=after_tax_return,
        students=tuple(results),
        household_totals=totals,
    )


def education_result_to_wire(result: EducationFundingResult) -> dict[str, object]:
    """Convert the dataclass tree to the public camelCase wire shape."""

    out = asdict(result)
    for student in out["students"]:
        student["subjectRef"] = student.pop("subject_ref")
        student["projectedSavingsAtStart"] = student.pop("projected_savings_at_start")
        student["savingsGapAtStart"] = student.pop("savings_gap_at_start")
        student["savingsNeed"] = student.pop("savings_need")
        student["cost"]["annualCost"] = student["cost"].pop("annual_cost")
        student["cost"]["tuitionInflation"] = student["cost"].pop("tuition_inflation")
        student["cost"]["yearsUntilStart"] = student["cost"].pop("years_until_start")
        student["cost"]["fundingYears"] = student["cost"].pop("funding_years")
        student["cost"]["firstYearCost"] = student["cost"].pop("first_year_cost")
        student["cost"]["totalFutureCost"] = student["cost"].pop("total_future_cost")
        student["cost"]["totalCostAtGoalStart"] = student["cost"].pop("total_cost_at_goal_start")
        student["cost"]["costSchedule"] = student["cost"].pop("cost_schedule")
        for row in student["cost"]["costSchedule"]:
            row["yearIndex"] = row.pop("year_index")
            row["yearsFromNow"] = row.pop("years_from_now")
            row["costAtGoalStart"] = row.pop("cost_at_goal_start")
        student["savingsNeed"]["targetFv"] = student["savingsNeed"].pop("target_fv")
        student["savingsNeed"]["currentSavings"] = student["savingsNeed"].pop("current_savings")
        student["savingsNeed"]["afterTaxReturn"] = student["savingsNeed"].pop("after_tax_return")
        student["savingsNeed"]["yearsUntilStart"] = student["savingsNeed"].pop("years_until_start")
        student["savingsNeed"]["lumpSum"] = student["savingsNeed"].pop("lump_sum")
    out["tuitionInflation"] = out.pop("tuition_inflation")
    out["afterTaxReturn"] = out.pop("after_tax_return")
    out["householdTotals"] = out.pop("household_totals")
    return out


__all__ = [
    "EducationCostResult",
    "EducationCostYear",
    "EducationFundingResult",
    "EducationSavingsNeed",
    "EducationSavingsProjection",
    "EducationStudentCase",
    "EducationStudentResult",
    "education_cost_fv",
    "education_funding",
    "education_result_to_wire",
    "education_savings_need",
    "education_savings_projection",
]
