# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Inherited IRA beneficiary distribution illustrations.

Pure, deterministic 10-year-rule planning math for inherited traditional IRA
distributions. Inputs are de-identified numeric assumptions only: balances,
ages, year counts, ordinary income, filing status, tax year, and rate
assumptions. The module deliberately accepts no beneficiary names, account
numbers, account nicknames, transactions, notes, approvals, release state, or
audit records.

The rule framing is based on IRS Publication 590-B and IRS beneficiary/RMD topic
pages as reviewed on 2026-07-08. It is an educational planning illustration, not
tax, legal, investment, or financial advice.
"""

from __future__ import annotations

from typing import Any, Literal

from ...disclaimers import MC_DISCLAIMER
from .bracket_headroom import bracket_headroom
from .tables import reference_bracket_table
from .tax import FilingStatus, ordinary_tax

BeneficiaryType = Literal[
    "spouse",
    "minor_child_of_decedent",
    "disabled",
    "chronically_ill",
    "not_more_than_10_years_younger",
    "other_designated_beneficiary",
    "non_designated_beneficiary",
]
InheritedIraStrategy = Literal["lump_sum", "equal_annual", "bracket_smoothed"]

BENEFICIARY_TYPES: tuple[BeneficiaryType, ...] = (
    "spouse",
    "minor_child_of_decedent",
    "disabled",
    "chronically_ill",
    "not_more_than_10_years_younger",
    "other_designated_beneficiary",
    "non_designated_beneficiary",
)
STRATEGIES: tuple[InheritedIraStrategy, ...] = (
    "lump_sum",
    "equal_annual",
    "bracket_smoothed",
)
_ROUND = 2
_RATE_ROUND = 6
_MAX_YEARS = 10


def _money(value: float) -> float:
    return round(value + 0.0, _ROUND)


def _rate(value: float) -> float:
    return round(value + 0.0, _RATE_ROUND)


def _ensure_non_negative(value: float, field: str) -> None:
    if value < 0.0:
        raise ValueError(f"{field} must be non-negative")


def _ensure_rate(value: float, field: str, *, minimum: float = -0.99, maximum: float = 1.0) -> None:
    if value < minimum or value > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")


def _amortizing_distribution(balance: float, annual_return: float, years: int) -> float:
    """End-of-year level payment that depletes ``balance`` after ``years``."""
    if years <= 1:
        return balance * (1.0 + annual_return)
    if abs(annual_return) < 1e-12:
        return balance / years
    growth = (1.0 + annual_return) ** years
    return balance * annual_return * growth / (growth - 1.0)


def inherited_ira_beneficiary_carveouts() -> tuple[dict[str, Any], ...]:
    """Reference EDB carve-out table for display/assumption stamping."""
    return (
        {
            "beneficiaryType": "spouse",
            "eligibleDesignatedBeneficiary": True,
            "summary": "Surviving spouse carve-out; spousal rollover / own-IRA treatment may be available.",
        },
        {
            "beneficiaryType": "minor_child_of_decedent",
            "eligibleDesignatedBeneficiary": True,
            "summary": (
                "Minor child of the decedent carve-out while a minor; the 10-year "
                "clock generally applies once the child reaches majority."
            ),
        },
        {
            "beneficiaryType": "disabled",
            "eligibleDesignatedBeneficiary": True,
            "summary": "Disabled beneficiary carve-out.",
        },
        {
            "beneficiaryType": "chronically_ill",
            "eligibleDesignatedBeneficiary": True,
            "summary": "Chronically ill beneficiary carve-out.",
        },
        {
            "beneficiaryType": "not_more_than_10_years_younger",
            "eligibleDesignatedBeneficiary": True,
            "summary": "Individual beneficiary not more than 10 years younger than the decedent.",
        },
        {
            "beneficiaryType": "other_designated_beneficiary",
            "eligibleDesignatedBeneficiary": False,
            "summary": "Designated beneficiary generally modeled under the post-SECURE 10-year rule.",
        },
        {
            "beneficiaryType": "non_designated_beneficiary",
            "eligibleDesignatedBeneficiary": False,
            "summary": (
                "Estate, charity, or other non-designated beneficiary; this v1 "
                "10-year strategy comparison may not be the governing rule."
            ),
        },
    )


def classify_inherited_ira_beneficiary(
    *,
    beneficiary_type: BeneficiaryType,
    beneficiary_age: int | None = None,
    decedent_age: int | None = None,
) -> dict[str, Any]:
    """Classify the beneficiary under the EDB carve-out categories."""
    if beneficiary_type not in BENEFICIARY_TYPES:
        raise ValueError(f"beneficiary_type must be one of {', '.join(BENEFICIARY_TYPES)}")
    if beneficiary_age is not None:
        _ensure_non_negative(float(beneficiary_age), "beneficiary_age")
    if decedent_age is not None:
        _ensure_non_negative(float(decedent_age), "decedent_age")

    edb_types = {
        "spouse",
        "minor_child_of_decedent",
        "disabled",
        "chronically_ill",
        "not_more_than_10_years_younger",
    }
    edb = beneficiary_type in edb_types
    notes: list[str] = []
    if (
        beneficiary_type == "other_designated_beneficiary"
        and beneficiary_age is not None
        and decedent_age is not None
        and decedent_age - beneficiary_age <= 10
    ):
        beneficiary_type = "not_more_than_10_years_younger"
        edb = True
        notes.append("Ages imply the not-more-than-10-years-younger EDB carve-out.")
    if beneficiary_type == "minor_child_of_decedent":
        notes.append("Model the post-majority switch separately before client-facing use.")
    if beneficiary_type == "non_designated_beneficiary":
        notes.append("Non-designated beneficiaries can follow different payout rules; v1 does not rank them.")
    elif not edb:
        notes.append("Modeled as subject to the 10-year distribution comparison.")
    else:
        notes.append("Eligible designated beneficiary carve-out identified; 10-year comparison is optional context.")

    label = beneficiary_type.replace("_", " ")
    return {
        "beneficiaryType": beneficiary_type,
        "label": label,
        "eligibleDesignatedBeneficiary": edb,
        "notes": notes,
    }


def _income_for_year(values: list[float], index: int) -> float:
    return values[index] if index < len(values) else values[-1]


def _year_row(
    *,
    year_index: int,
    beginning_balance: float,
    growth: float,
    distribution: float,
    ending_balance: float,
    ordinary_income: float,
    taxable_distribution: float,
    filing_status: FilingStatus,
    tax_year: int,
) -> dict[str, Any]:
    before_tax = ordinary_tax(ordinary_income, filing_status, year=tax_year)
    after_tax = ordinary_tax(ordinary_income + taxable_distribution, filing_status, year=tax_year)
    incremental_tax = max(0.0, after_tax - before_tax)
    headroom = bracket_headroom(
        taxable_income=ordinary_income + taxable_distribution,
        filing_status=filing_status,
        year=tax_year,
    )
    return {
        "yearIndex": year_index,
        "beginningBalance": _money(beginning_balance),
        "growth": _money(growth),
        "distribution": _money(distribution),
        "taxableDistribution": _money(taxable_distribution),
        "endingBalance": _money(ending_balance),
        "beneficiaryOrdinaryIncome": _money(ordinary_income),
        "ordinaryIncomeWithDistribution": _money(ordinary_income + taxable_distribution),
        "incrementalFederalTax": _money(incremental_tax),
        "marginalOrdinaryRate": _rate(float(headroom["marginalRate"])),
        "effectiveTaxRateOnDistribution": (
            None if distribution <= 0.0 else _rate(incremental_tax / distribution)
        ),
    }


def _simulate_strategy(
    *,
    strategy: InheritedIraStrategy,
    inherited_balance: float,
    annual_return: float,
    years_remaining: int,
    beneficiary_income_by_year: list[float],
    filing_status: FilingStatus,
    tax_year: int,
    taxable_distribution_ratio: float,
    target_rate: float,
) -> dict[str, Any]:
    balance = inherited_balance
    rows: list[dict[str, Any]] = []
    peak_rate = 0.0

    for year_index in range(1, years_remaining + 1):
        beginning = balance
        if strategy == "lump_sum":
            growth = 0.0
            distribution = beginning if year_index == 1 else 0.0
            ending = 0.0
        else:
            growth = beginning * annual_return
            available = max(0.0, beginning + growth)
            remaining_years = years_remaining - year_index + 1
            required_floor = min(available, _amortizing_distribution(beginning, annual_return, remaining_years))
            if strategy == "equal_annual":
                distribution = required_floor
            else:
                ordinary_income = _income_for_year(beneficiary_income_by_year, year_index - 1)
                room = bracket_headroom(
                    taxable_income=ordinary_income,
                    filing_status=filing_status,
                    target_rate=target_rate,
                    year=tax_year,
                ).get("roomToTargetRate")
                if room is None or taxable_distribution_ratio == 0.0:
                    target_distribution = available
                else:
                    target_distribution = max(0.0, float(room)) / taxable_distribution_ratio
                distribution = min(available, max(required_floor, target_distribution))
            if year_index == years_remaining:
                distribution = available
            ending = max(0.0, available - distribution)

        taxable_distribution = distribution * taxable_distribution_ratio
        ordinary_income = _income_for_year(beneficiary_income_by_year, year_index - 1)
        row = _year_row(
            year_index=year_index,
            beginning_balance=beginning,
            growth=growth,
            distribution=distribution,
            ending_balance=ending,
            ordinary_income=ordinary_income,
            taxable_distribution=taxable_distribution,
            filing_status=filing_status,
            tax_year=tax_year,
        )
        peak_rate = max(peak_rate, float(row["marginalOrdinaryRate"]))
        rows.append(row)
        balance = ending

    total_distributed = sum(float(row["distribution"]) for row in rows)
    total_taxable = sum(float(row["taxableDistribution"]) for row in rows)
    total_tax = sum(float(row["incrementalFederalTax"]) for row in rows)
    total_growth = sum(float(row["growth"]) for row in rows)
    return {
        "strategy": strategy,
        "label": strategy.replace("_", " ").title(),
        "years": rows,
        "totals": {
            "totalDistributed": _money(total_distributed),
            "totalTaxableDistributed": _money(total_taxable),
            "totalGrowth": _money(total_growth),
            "totalIncrementalFederalTax": _money(total_tax),
            "netAfterTaxReceived": _money(total_distributed - total_tax),
            "endingBalance": _money(float(rows[-1]["endingBalance"])),
            "peakMarginalOrdinaryRate": _rate(peak_rate),
        },
    }


def inherited_ira_analysis(
    *,
    inherited_balance: float,
    beneficiary_ordinary_income: float,
    filing_status: FilingStatus,
    tax_year: int = 2026,
    years_remaining: int = 10,
    annual_return: float = 0.0,
    taxable_distribution_ratio: float = 1.0,
    beneficiary_ordinary_income_by_year: list[float] | None = None,
    beneficiary_type: BeneficiaryType = "other_designated_beneficiary",
    beneficiary_age: int | None = None,
    decedent_age: int | None = None,
    target_rate: float = 0.24,
) -> dict[str, Any]:
    """Compare inherited IRA distribution strategies under a 10-year frame."""
    _ensure_non_negative(inherited_balance, "inherited_balance")
    _ensure_non_negative(beneficiary_ordinary_income, "beneficiary_ordinary_income")
    if years_remaining < 1 or years_remaining > _MAX_YEARS:
        raise ValueError("years_remaining must be between 1 and 10")
    _ensure_rate(annual_return, "annual_return")
    _ensure_rate(taxable_distribution_ratio, "taxable_distribution_ratio", minimum=0.0)
    _ensure_rate(target_rate, "target_rate", minimum=0.0)
    if beneficiary_type == "non_designated_beneficiary":
        raise ValueError(
            "inherited_ira_analysis does not rank non_designated_beneficiary cases; "
            "use the carve-out notes and model non-individual payout rules separately"
        )
    table = reference_bracket_table(tax_year)

    income_by_year = beneficiary_ordinary_income_by_year or [beneficiary_ordinary_income]
    if len(income_by_year) > _MAX_YEARS:
        raise ValueError("beneficiary_ordinary_income_by_year must have at most 10 entries")
    for i, income in enumerate(income_by_year):
        _ensure_non_negative(income, f"beneficiary_ordinary_income_by_year[{i}]")

    classification = classify_inherited_ira_beneficiary(
        beneficiary_type=beneficiary_type,
        beneficiary_age=beneficiary_age,
        decedent_age=decedent_age,
    )
    strategies = [
        _simulate_strategy(
            strategy=strategy,
            inherited_balance=inherited_balance,
            annual_return=annual_return,
            years_remaining=years_remaining,
            beneficiary_income_by_year=income_by_year,
            filing_status=filing_status,
            tax_year=tax_year,
            taxable_distribution_ratio=taxable_distribution_ratio,
            target_rate=target_rate,
        )
        for strategy in STRATEGIES
    ]
    ranked = sorted(
        strategies,
        key=lambda item: (
            -float(item["totals"]["netAfterTaxReceived"]),
            float(item["totals"]["totalIncrementalFederalTax"]),
        ),
    )
    for rank, strategy in enumerate(ranked, start=1):
        strategy["rank"] = rank

    return {
        "taxYear": tax_year,
        "taxTableVersion": table.table_version,
        "taxTableSource": table.source,
        "taxTableLastVerified": table.last_verified,
        "yearsRemaining": years_remaining,
        "beneficiaryClassification": classification,
        "carveOuts": list(inherited_ira_beneficiary_carveouts()),
        "strategyRankings": [
            {
                "rank": strategy["rank"],
                "strategy": strategy["strategy"],
                "netAfterTaxReceived": strategy["totals"]["netAfterTaxReceived"],
                "totalIncrementalFederalTax": strategy["totals"]["totalIncrementalFederalTax"],
                "peakMarginalOrdinaryRate": strategy["totals"]["peakMarginalOrdinaryRate"],
            }
            for strategy in ranked
        ],
        "strategies": ranked,
        "assumptions": {
            "annualReturn": _rate(annual_return),
            "taxableDistributionRatio": _rate(taxable_distribution_ratio),
            "targetRate": _rate(target_rate),
            "distributionTiming": "end_of_year_for_equal_and_smoothed; immediate_year_1_for_lump_sum",
            "taxScope": "federal_ordinary_income_only",
            "taxTableSource": table.source,
            "taxTableLastVerified": table.last_verified,
            "annualRmdScope": (
                "strategy comparison only; this v1 does not calculate separate "
                "beneficiary life-expectancy annual RMD compliance amounts for "
                "owner-after-required-beginning-date cases"
            ),
            "sourceBasis": (
                "IRS Publication 590-B and IRS beneficiary/RMD topic pages reviewed "
                "2026-07-08; verify current law before client-facing tax use."
            ),
        },
        "disclaimer": MC_DISCLAIMER,
    }


__all__ = [
    "BENEFICIARY_TYPES",
    "STRATEGIES",
    "BeneficiaryType",
    "InheritedIraStrategy",
    "classify_inherited_ira_beneficiary",
    "inherited_ira_analysis",
    "inherited_ira_beneficiary_carveouts",
]
