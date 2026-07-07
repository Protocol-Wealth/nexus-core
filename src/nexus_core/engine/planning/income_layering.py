# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Deterministic income-layering timeline (educational).

This module composes existing public-safe planning kernels into a year-by-year
income stack: earned income, Social Security, pension/annuity income, forced RMDs,
and gap-fill portfolio withdrawals. It intentionally accepts only de-identified
numeric inputs and account-type buckets. No account identifiers, household names,
notes, transactions, or storage hooks belong here.

The tax model is a planning illustration, not advice: US federal ordinary brackets
plus the existing simplified withdrawal kernel, with Social Security taxable
benefits computed through the shared provisional-income helper. Optional state
tax uses the reference table in ``state_tax.py``; account-specific cost basis and
local tax hooks remain outside this slice.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .bracket_headroom import bracket_headroom
from .income_model import ss_taxable
from .social_security import social_security_claiming
from .state_tax import (
    IncomeSource,
    StateResidencyChange,
    StateTaxRule,
    estimate_state_income_tax_components,
    reference_state_tax_rule,
    state_code_for_year,
    state_tax_notes,
)
from .tables import reference_bracket_table
from .tax import (
    RMD_START_AGE_POLICY_VERSION,
    TAXABLE_WITHDRAWAL_GAIN_FRACTION,
    FilingStatus,
    ltcg_tax,
    ordinary_tax,
    rmd_factor,
    rmd_start_age,
    tax_aware_withdrawal,
)

AccountType = Literal["taxable", "traditional", "roth"]
IncomeStreamKind = Literal["pension", "annuity"]

_ACCOUNT_TYPES: tuple[AccountType, ...] = ("taxable", "traditional", "roth")
_FILING_STATUSES: tuple[FilingStatus, ...] = (
    "single",
    "married_joint",
    "married_separate",
    "head_of_household",
)
_MAX_AGE = 130
_MAX_YEARS = 100


@dataclass(frozen=True, slots=True)
class IncomeStream:
    """Public-safe guaranteed-income stream.

    ``kind`` is intentionally categorical. The public engine does not accept
    labels or identifiers for a pension/annuity provider.
    """

    kind: IncomeStreamKind
    annual_amount: float
    start_age: int
    end_age: int | None = None
    cola_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class SocialSecurityIncome:
    """Social Security benefit parameters for the timeline."""

    pia_monthly: float
    claim_age: int
    fra_age: int = 67
    cola_rate: float = 0.0


@dataclass(frozen=True, slots=True)
class _YearTaxPicture:
    taxable_ss: float
    ordinary_tax: float
    taxable_withdrawal_tax: float

    @property
    def total_tax(self) -> float:
        return self.ordinary_tax + self.taxable_withdrawal_tax


@dataclass(frozen=True, slots=True)
class _CombinedTaxPicture:
    taxable_ss: float
    federal_tax: float
    state_tax: float

    @property
    def total_tax(self) -> float:
        return self.federal_tax + self.state_tax


def _check_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")


def _check_non_negative(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite non-negative number")
    if value < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number")


def _check_rate(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number > -1")
    if value <= -1.0:
        raise ValueError(f"{name} must be a finite number > -1")


def _validate_accounts(
    account_balances: dict[str, float] | None,
    *,
    expected_return: float,
    account_returns: dict[str, float] | None,
) -> tuple[dict[AccountType, float], dict[AccountType, float]]:
    balances: dict[AccountType, float] = {"taxable": 0.0, "traditional": 0.0, "roth": 0.0}
    returns: dict[AccountType, float] = {
        "taxable": expected_return,
        "traditional": expected_return,
        "roth": expected_return,
    }
    if account_balances is not None:
        extra = set(account_balances) - set(_ACCOUNT_TYPES)
        if extra:
            raise ValueError(
                f"account_balances only supports taxable/traditional/roth; got {extra}"
            )
        for account_type in _ACCOUNT_TYPES:
            value = account_balances.get(account_type, 0.0)
            _check_non_negative(f"account_balances.{account_type}", value)
            balances[account_type] = float(value)
    if account_returns is not None:
        extra = set(account_returns) - set(_ACCOUNT_TYPES)
        if extra:
            raise ValueError(f"account_returns only supports taxable/traditional/roth; got {extra}")
        for account_type in _ACCOUNT_TYPES:
            if account_type in account_returns:
                value = account_returns[account_type]
                _check_rate(f"account_returns.{account_type}", value)
                returns[account_type] = float(value)
    return balances, returns


def _ss_annual_benefit(ss: SocialSecurityIncome | None) -> float:
    if ss is None:
        return 0.0
    result = social_security_claiming(pia_monthly=ss.pia_monthly, fra_age=ss.fra_age)
    for row in result["byClaimAge"]:
        if row["claimAge"] == ss.claim_age:
            return float(row["annualBenefit"])
    raise ValueError("social_security.claim_age must be between 62 and 70")


def _stream_amount(stream: IncomeStream, age: int) -> float:
    if age < stream.start_age:
        return 0.0
    if stream.end_age is not None and age > stream.end_age:
        return 0.0
    years = age - stream.start_age
    return stream.annual_amount * (1.0 + stream.cola_rate) ** years


def _add_layer(
    layers: list[dict[str, Any]],
    source: str,
    gross: float,
    tax: float,
) -> None:
    if gross <= 0.004 and tax <= 0.004:
        return
    layers.append(
        {
            "source": source,
            "gross": round(gross, 2),
            "tax": round(tax, 2),
            "net": round(gross - tax, 2),
        }
    )


def _allocate_ordinary_tax(
    components: list[tuple[str, float, float]], ordinary_tax_amount: float
) -> dict[str, float]:
    taxable_total = sum(taxable for _, _, taxable in components)
    return {
        source: ordinary_tax_amount * taxable / taxable_total if taxable_total > 0.0 else 0.0
        for source, _, taxable in components
    }


def _withdrawal_rows_by_type(rows: list[dict[str, Any]]) -> dict[AccountType, tuple[float, float]]:
    by_type = dict.fromkeys(_ACCOUNT_TYPES, (0.0, 0.0))
    for row in rows:
        account_type = row.get("type")
        if account_type in by_type:
            by_type[account_type] = (float(row.get("gross", 0.0)), float(row.get("tax", 0.0)))
    return by_type


def _tax_aware_plan(
    *,
    balances: dict[AccountType, float],
    gross_need: float,
    age: int,
    taxable_ordinary: float,
    filing_status: FilingStatus,
    tax_year: int,
    birth_year: int | None,
    state: str | None,
    residency_change: StateResidencyChange | None,
    projection_year: int,
) -> dict[str, Any]:
    available = sum(balances.values())
    bounded_need = min(max(0.0, gross_need), available)
    if available <= 0.004 and bounded_need <= 0.004:
        return {
            "withdrawals": [],
            "totalTax": 0.0,
            "effectiveRate": 0.0,
            "rmdStartAge": rmd_start_age(birth_year),
            "rmdStartAgePolicyVersion": RMD_START_AGE_POLICY_VERSION,
            "rmdSatisfied": True,
        }
    return tax_aware_withdrawal(
        year=tax_year,
        filing_status=filing_status,
        accounts=[
            {"type": account_type, "balance": balances[account_type]}
            for account_type in _ACCOUNT_TYPES
        ],
        gross_need=bounded_need,
        age=age,
        other_taxable_income=taxable_ordinary,
        birth_year=birth_year,
        state=state,
        residency_change=residency_change,
        projection_year=projection_year,
    )


def _state_rule_for_year(
    *,
    state: str | None,
    residency_change: StateResidencyChange | None,
    projection_year: int,
    tax_year: int,
) -> tuple[str | None, StateTaxRule | None]:
    state_code = state_code_for_year(
        base_state=state,
        residency_change=residency_change,
        year=projection_year,
    )
    if state_code is None:
        return None, None
    return state_code, reference_state_tax_rule(state_code, tax_year)


def _state_tax_by_source(
    *,
    state_rule: StateTaxRule | None,
    age: int,
    filing_status: FilingStatus,
    earned: float,
    ss_gross: float,
    pension_gross: float,
    annuity_gross: float,
    forced_rmd: float,
    discretionary_trad: float,
    bracket_fill_gross: float,
    taxable_gross: float,
    roth_gross: float,
) -> tuple[dict[str, float], tuple[str, ...], str | None]:
    if state_rule is None:
        return {}, (), None
    taxable_gain = taxable_gross * TAXABLE_WITHDRAWAL_GAIN_FRACTION
    components: list[tuple[str, IncomeSource, float]] = [
        ("earned_income", "earned_income", earned),
        ("social_security", "social_security", ss_gross),
        ("pension", "pension", pension_gross),
        ("annuity", "annuity", annuity_gross),
        ("rmd", "traditional_distribution", forced_rmd),
        ("traditional_withdrawal", "traditional_distribution", discretionary_trad),
        ("bracket_fill", "traditional_distribution", bracket_fill_gross),
        ("taxable_withdrawal", "taxable_gain", taxable_gain),
        ("roth_withdrawal", "roth_distribution", roth_gross),
    ]
    total_income = (
        earned
        + ss_gross
        + pension_gross
        + annuity_gross
        + forced_rmd
        + discretionary_trad
        + bracket_fill_gross
        + taxable_gain
    )
    estimates = estimate_state_income_tax_components(
        state_rule,
        components,
        age=age,
        filing_status=filing_status,
        total_income=total_income,
    )
    return (
        {source: estimate.tax for source, estimate in estimates.items()},
        state_tax_notes(state_rule, tuple(estimates.values())),
        state_rule.table_version,
    )


def _taxable_social_security(
    *,
    ss_gross: float,
    non_ss_ordinary: float,
    traditional_withdrawals: float,
    taxable_withdrawals: float,
    filing_status: FilingStatus,
    tax_year: int,
) -> float:
    table = reference_bracket_table(tax_year)
    base, additional = table.ss_provisional_thresholds[filing_status]
    taxable_gain = taxable_withdrawals * TAXABLE_WITHDRAWAL_GAIN_FRACTION
    provisional = non_ss_ordinary + traditional_withdrawals + taxable_gain + 0.5 * ss_gross
    return ss_taxable(ss_gross, provisional, base, additional)


def _year_tax_picture(
    *,
    ss_gross: float,
    non_ss_ordinary: float,
    withdrawals: Mapping[str, float],
    filing_status: FilingStatus,
    tax_year: int,
) -> _YearTaxPicture:
    traditional = withdrawals.get("traditional", 0.0)
    taxable = withdrawals.get("taxable", 0.0)
    taxable_ss = _taxable_social_security(
        ss_gross=ss_gross,
        non_ss_ordinary=non_ss_ordinary,
        traditional_withdrawals=traditional,
        taxable_withdrawals=taxable,
        filing_status=filing_status,
        tax_year=tax_year,
    )
    ordinary_income = non_ss_ordinary + taxable_ss + traditional
    taxable_gain = taxable * TAXABLE_WITHDRAWAL_GAIN_FRACTION
    return _YearTaxPicture(
        taxable_ss=taxable_ss,
        ordinary_tax=ordinary_tax(ordinary_income, filing_status, year=tax_year),
        taxable_withdrawal_tax=ltcg_tax(
            taxable_gain,
            ordinary_income,
            filing_status,
            year=tax_year,
        ),
    )


def _combined_tax_picture(
    *,
    ss_gross: float,
    earned: float,
    pension_gross: float,
    annuity_gross: float,
    withdrawals: Mapping[str, float],
    filing_status: FilingStatus,
    tax_year: int,
    age: int,
    state_rule: StateTaxRule | None,
) -> _CombinedTaxPicture:
    non_ss_ordinary = earned + pension_gross + annuity_gross
    federal = _year_tax_picture(
        ss_gross=ss_gross,
        non_ss_ordinary=non_ss_ordinary,
        withdrawals=withdrawals,
        filing_status=filing_status,
        tax_year=tax_year,
    )
    state_tax_by_source, _, _ = _state_tax_by_source(
        state_rule=state_rule,
        age=age,
        filing_status=filing_status,
        earned=earned,
        ss_gross=ss_gross,
        pension_gross=pension_gross,
        annuity_gross=annuity_gross,
        forced_rmd=0.0,
        discretionary_trad=withdrawals.get("traditional", 0.0),
        bracket_fill_gross=0.0,
        taxable_gross=withdrawals.get("taxable", 0.0),
        roth_gross=withdrawals.get("roth", 0.0),
    )
    return _CombinedTaxPicture(
        taxable_ss=federal.taxable_ss,
        federal_tax=federal.total_tax,
        state_tax=sum(state_tax_by_source.values()),
    )


def _gross_up_withdrawal_need(
    *,
    balances: dict[AccountType, float],
    spending_target: float,
    base_gross: float,
    earned: float,
    pension_gross: float,
    annuity_gross: float,
    ss_gross: float,
    age: int,
    filing_status: FilingStatus,
    tax_year: int,
    birth_year: int | None,
    state: str | None,
    residency_change: StateResidencyChange | None,
    projection_year: int,
) -> dict[str, Any]:
    non_ss_ordinary = earned + pension_gross + annuity_gross
    _, state_rule = _state_rule_for_year(
        state=state,
        residency_change=residency_change,
        projection_year=projection_year,
        tax_year=tax_year,
    )
    base_picture = _combined_tax_picture(
        ss_gross=ss_gross,
        earned=earned,
        pension_gross=pension_gross,
        annuity_gross=annuity_gross,
        withdrawals={"taxable": 0.0, "traditional": 0.0, "roth": 0.0},
        filing_status=filing_status,
        tax_year=tax_year,
        age=age,
        state_rule=state_rule,
    )
    target = max(0.0, spending_target - base_gross + base_picture.total_tax)
    plan = _tax_aware_plan(
        balances=balances,
        gross_need=target,
        age=age,
        taxable_ordinary=non_ss_ordinary + base_picture.taxable_ss,
        filing_status=filing_status,
        tax_year=tax_year,
        birth_year=birth_year,
        state=state,
        residency_change=residency_change,
        projection_year=projection_year,
    )
    for _ in range(6):
        withdrawals: dict[str, float] = {
            account_type: gross
            for account_type, (gross, _) in _withdrawal_rows_by_type(plan["withdrawals"]).items()
        }
        picture = _combined_tax_picture(
            ss_gross=ss_gross,
            earned=earned,
            pension_gross=pension_gross,
            annuity_gross=annuity_gross,
            withdrawals=withdrawals,
            filing_status=filing_status,
            tax_year=tax_year,
            age=age,
            state_rule=state_rule,
        )
        next_target = max(0.0, spending_target - base_gross + picture.total_tax)
        if abs(next_target - target) < 0.005:
            break
        target = next_target
        plan = _tax_aware_plan(
            balances=balances,
            gross_need=target,
            age=age,
            taxable_ordinary=non_ss_ordinary + picture.taxable_ss,
            filing_status=filing_status,
            tax_year=tax_year,
            birth_year=birth_year,
            state=state,
            residency_change=residency_change,
            projection_year=projection_year,
        )
    return plan


def _forced_rmd_for_year(
    *,
    balances: dict[AccountType, float],
    age: int,
    birth_year: int | None,
) -> float:
    start_age = rmd_start_age(birth_year)
    if age < start_age:
        return 0.0
    return min(balances["traditional"] / rmd_factor(age), balances["traditional"])


def _bracket_fill(
    *,
    balances: dict[AccountType, float],
    traditional_withdrawn: float,
    taxable_withdrawn: float,
    ss_gross: float,
    non_ss_ordinary: float,
    target_rate: float | None,
    filing_status: FilingStatus,
    tax_year: int,
) -> tuple[float, float, dict[str, Any] | None]:
    if target_rate is None:
        return 0.0, 0.0, None
    if not 0.0 <= target_rate < 1.0:
        raise ValueError("bracket_fill_target_rate must be in [0, 1)")
    remaining_traditional = max(0.0, balances["traditional"] - traditional_withdrawn)
    if remaining_traditional <= 0.004:
        return 0.0, 0.0, None
    current_picture = _year_tax_picture(
        ss_gross=ss_gross,
        non_ss_ordinary=non_ss_ordinary,
        withdrawals={
            "taxable": taxable_withdrawn,
            "traditional": traditional_withdrawn,
            "roth": 0.0,
        },
        filing_status=filing_status,
        tax_year=tax_year,
    )
    current_ordinary = non_ss_ordinary + current_picture.taxable_ss + traditional_withdrawn
    headroom = bracket_headroom(
        taxable_income=current_ordinary,
        filing_status=filing_status,
        target_rate=target_rate,
        year=tax_year,
    )
    room = headroom.get("roomToTargetRate")
    if room is None:
        return 0.0, 0.0, headroom
    fill_ceiling = min(float(room), remaining_traditional)
    low = 0.0
    high = fill_ceiling
    for _ in range(30):
        mid = (low + high) / 2.0
        mid_picture = _year_tax_picture(
            ss_gross=ss_gross,
            non_ss_ordinary=non_ss_ordinary,
            withdrawals={
                "taxable": taxable_withdrawn,
                "traditional": traditional_withdrawn + mid,
                "roth": 0.0,
            },
            filing_status=filing_status,
            tax_year=tax_year,
        )
        mid_ordinary = non_ss_ordinary + mid_picture.taxable_ss + traditional_withdrawn + mid
        if mid_ordinary - current_ordinary <= float(room):
            low = mid
        else:
            high = mid
    fill = low
    if fill <= 0.004:
        return 0.0, 0.0, headroom
    after_picture = _year_tax_picture(
        ss_gross=ss_gross,
        non_ss_ordinary=non_ss_ordinary,
        withdrawals={
            "taxable": taxable_withdrawn,
            "traditional": traditional_withdrawn + fill,
            "roth": 0.0,
        },
        filing_status=filing_status,
        tax_year=tax_year,
    )
    return fill, after_picture.total_tax - current_picture.total_tax, headroom


def income_layering(
    *,
    current_age: int,
    terminal_age: int,
    spending_target: float,
    retirement_age: int | None = None,
    earned_income: float = 0.0,
    wage_growth_rate: float = 0.03,
    spending_inflation_rate: float = 0.025,
    filing_status: FilingStatus = "married_joint",
    tax_year: int = 2026,
    base_year: int | None = None,
    social_security: SocialSecurityIncome | None = None,
    income_streams: tuple[IncomeStream, ...] = (),
    account_balances: dict[str, float] | None = None,
    account_returns: dict[str, float] | None = None,
    expected_return: float = 0.05,
    bracket_fill_target_rate: float | None = None,
    birth_year: int | None = None,
    state: str | None = None,
    residency_change: StateResidencyChange | None = None,
) -> dict[str, Any]:
    """Return a deterministic stacked-income timeline.

    The account waterfall uses the existing ``tax_aware_withdrawal`` kernel:
    RMDs first, then taxable -> traditional -> Roth. Optional bracket fill draws
    additional traditional dollars up to a requested federal marginal rate.
    """
    _check_int("current_age", current_age)
    _check_int("terminal_age", terminal_age)
    if retirement_age is None:
        retirement_age = current_age
    _check_int("retirement_age", retirement_age)
    if not 0 <= current_age <= _MAX_AGE:
        raise ValueError("current_age must be in [0, 130]")
    if not 0 <= retirement_age <= _MAX_AGE:
        raise ValueError("retirement_age must be in [0, 130]")
    if terminal_age <= current_age:
        raise ValueError("terminal_age must be greater than current_age")
    if terminal_age - current_age + 1 > _MAX_YEARS:
        raise ValueError(f"income layering spans at most {_MAX_YEARS} years")
    if filing_status not in _FILING_STATUSES:
        raise ValueError(f"filing_status must be one of {', '.join(_FILING_STATUSES)}")
    if base_year is not None:
        _check_int("base_year", base_year)
    _check_int("tax_year", tax_year)
    _check_non_negative("spending_target", spending_target)
    _check_non_negative("earned_income", earned_income)
    _check_rate("wage_growth_rate", wage_growth_rate)
    _check_rate("spending_inflation_rate", spending_inflation_rate)
    _check_rate("expected_return", expected_return)
    if birth_year is not None:
        _check_int("birth_year", birth_year)
        rmd_start_age(birth_year)
    if social_security is not None:
        _check_non_negative("social_security.pia_monthly", social_security.pia_monthly)
        _check_int("social_security.claim_age", social_security.claim_age)
        _check_int("social_security.fra_age", social_security.fra_age)
        _check_rate("social_security.cola_rate", social_security.cola_rate)
    for index, stream in enumerate(income_streams):
        if stream.kind not in ("pension", "annuity"):
            raise ValueError(f"income_streams[{index}].kind must be pension or annuity")
        _check_non_negative(f"income_streams[{index}].annual_amount", stream.annual_amount)
        _check_int(f"income_streams[{index}].start_age", stream.start_age)
        if stream.end_age is not None:
            _check_int(f"income_streams[{index}].end_age", stream.end_age)
            if stream.end_age < stream.start_age:
                raise ValueError(f"income_streams[{index}].end_age must be >= start_age")
        _check_rate(f"income_streams[{index}].cola_rate", stream.cola_rate)

    tax_table = reference_bracket_table(tax_year)
    balances, returns = _validate_accounts(
        account_balances,
        expected_return=expected_return,
        account_returns=account_returns,
    )
    starting_balances = dict(balances)
    ss_base_annual = _ss_annual_benefit(social_security)
    rows: list[dict[str, Any]] = []
    source_rollups: dict[str, dict[str, float]] = {}
    total_spending = 0.0
    total_gross = 0.0
    total_tax = 0.0
    total_federal_tax = 0.0
    total_state_tax = 0.0
    total_gap = 0.0
    total_surplus = 0.0
    first_gap_age: int | None = None
    state_requested = state is not None or residency_change is not None

    for offset in range(terminal_age - current_age + 1):
        age = current_age + offset
        year = base_year + offset if base_year is not None else offset
        state_projection_year = year if base_year is not None else tax_year + offset
        spending = spending_target * (1.0 + spending_inflation_rate) ** offset
        earned = earned_income * (1.0 + wage_growth_rate) ** offset if age < retirement_age else 0.0
        ss_gross = 0.0
        if social_security is not None and age >= social_security.claim_age:
            ss_gross = ss_base_annual * (1.0 + social_security.cola_rate) ** (
                age - social_security.claim_age
            )
        stream_by_kind = {"pension": 0.0, "annuity": 0.0}
        for stream in income_streams:
            stream_by_kind[stream.kind] += _stream_amount(stream, age)

        pension_gross = stream_by_kind["pension"]
        annuity_gross = stream_by_kind["annuity"]
        non_ss_ordinary = earned + pension_gross + annuity_gross
        base_gross = non_ss_ordinary + ss_gross

        plan = _gross_up_withdrawal_need(
            balances=balances,
            spending_target=spending,
            base_gross=base_gross,
            earned=earned,
            pension_gross=pension_gross,
            annuity_gross=annuity_gross,
            ss_gross=ss_gross,
            age=age,
            filing_status=filing_status,
            tax_year=tax_year,
            birth_year=birth_year,
            state=state,
            residency_change=residency_change,
            projection_year=state_projection_year,
        )
        by_type = _withdrawal_rows_by_type(plan["withdrawals"])
        forced_rmd = min(
            _forced_rmd_for_year(balances=balances, age=age, birth_year=birth_year),
            by_type["traditional"][0],
        )
        taxable_gross, _ = by_type["taxable"]
        traditional_gross, _ = by_type["traditional"]
        roth_gross, _ = by_type["roth"]
        discretionary_trad = max(0.0, traditional_gross - forced_rmd)

        bracket_fill_gross, _, headroom = _bracket_fill(
            balances=balances,
            traditional_withdrawn=traditional_gross,
            taxable_withdrawn=taxable_gross,
            ss_gross=ss_gross,
            non_ss_ordinary=non_ss_ordinary,
            target_rate=bracket_fill_target_rate,
            filing_status=filing_status,
            tax_year=tax_year,
        )
        if bracket_fill_gross > 0.004:
            traditional_gross += bracket_fill_gross

        withdrawals = {
            "taxable": taxable_gross,
            "traditional": traditional_gross,
            "roth": roth_gross,
        }
        tax_picture = _year_tax_picture(
            ss_gross=ss_gross,
            non_ss_ordinary=non_ss_ordinary,
            withdrawals=withdrawals,
            filing_status=filing_status,
            tax_year=tax_year,
        )
        state_code, state_rule = _state_rule_for_year(
            state=state,
            residency_change=residency_change,
            projection_year=state_projection_year,
            tax_year=tax_year,
        )
        state_tax_by_source, state_notes, state_table_version = _state_tax_by_source(
            state_rule=state_rule,
            age=age,
            filing_status=filing_status,
            earned=earned,
            ss_gross=ss_gross,
            pension_gross=pension_gross,
            annuity_gross=annuity_gross,
            forced_rmd=forced_rmd,
            discretionary_trad=discretionary_trad,
            bracket_fill_gross=bracket_fill_gross,
            taxable_gross=taxable_gross,
            roth_gross=roth_gross,
        )
        ordinary_components = [
            ("earned_income", earned, earned),
            ("social_security", ss_gross, tax_picture.taxable_ss),
            ("pension", pension_gross, pension_gross),
            ("annuity", annuity_gross, annuity_gross),
            ("rmd", forced_rmd, forced_rmd),
            ("traditional_withdrawal", discretionary_trad, discretionary_trad),
            ("bracket_fill", bracket_fill_gross, bracket_fill_gross),
        ]
        ordinary_components = [
            (source, gross, taxable)
            for source, gross, taxable in ordinary_components
            if gross > 0.004 or taxable > 0.004
        ]
        ordinary_tax_by_source = _allocate_ordinary_tax(
            ordinary_components,
            tax_picture.ordinary_tax,
        )
        gross_by_source = {source: gross for source, gross, _ in ordinary_components}
        layers: list[dict[str, Any]] = []
        for source in ("earned_income", "social_security", "pension", "annuity", "rmd"):
            _add_layer(
                layers,
                source,
                gross_by_source.get(source, 0.0),
                ordinary_tax_by_source.get(source, 0.0) + state_tax_by_source.get(source, 0.0),
            )
        if taxable_gross > 0.004:
            _add_layer(
                layers,
                "taxable_withdrawal",
                taxable_gross,
                tax_picture.taxable_withdrawal_tax
                + state_tax_by_source.get("taxable_withdrawal", 0.0),
            )
        _add_layer(
            layers,
            "traditional_withdrawal",
            gross_by_source.get("traditional_withdrawal", 0.0),
            ordinary_tax_by_source.get("traditional_withdrawal", 0.0)
            + state_tax_by_source.get("traditional_withdrawal", 0.0),
        )
        if roth_gross > 0.004:
            _add_layer(
                layers,
                "roth_withdrawal",
                roth_gross,
                state_tax_by_source.get("roth_withdrawal", 0.0),
            )
        _add_layer(
            layers,
            "bracket_fill",
            gross_by_source.get("bracket_fill", 0.0),
            ordinary_tax_by_source.get("bracket_fill", 0.0)
            + state_tax_by_source.get("bracket_fill", 0.0),
        )
        for account_type in _ACCOUNT_TYPES:
            balances[account_type] = max(0.0, balances[account_type] - withdrawals[account_type])
            balances[account_type] *= 1.0 + returns[account_type]

        year_gross = sum(layer["gross"] for layer in layers)
        year_tax = sum(layer["tax"] for layer in layers)
        year_state_tax = sum(state_tax_by_source.values())
        year_federal_tax = year_tax - year_state_tax
        net_income = year_gross - year_tax
        gap = max(0.0, spending - net_income)
        surplus = max(0.0, net_income - spending)
        if gap > 0.004 and first_gap_age is None:
            first_gap_age = age
        effective_rate = year_tax / year_gross if year_gross > 0.0 else 0.0
        total_spending += spending
        total_gross += year_gross
        total_tax += year_tax
        total_federal_tax += year_federal_tax
        total_state_tax += year_state_tax
        total_gap += gap
        total_surplus += surplus
        for layer in layers:
            rollup = source_rollups.setdefault(layer["source"], {"gross": 0.0, "tax": 0.0})
            rollup["gross"] += float(layer["gross"])
            rollup["tax"] += float(layer["tax"])

        row: dict[str, Any] = {
            "age": age,
            "year": year,
            "spendingTarget": round(spending, 2),
            "layers": layers,
            "totalGross": round(year_gross, 2),
            "totalTax": round(year_tax, 2),
            "netIncome": round(net_income, 2),
            "gap": round(gap, 2),
            "surplusAfterTax": round(surplus, 2),
            "effectiveTaxRate": round(effective_rate, 4),
            "endingAccountBalances": {
                account_type: round(balances[account_type], 2) for account_type in _ACCOUNT_TYPES
            },
        }
        if headroom is not None:
            row["bracketHeadroom"] = headroom
        if state_requested:
            row["stateCode"] = state_code
            row["stateTaxModeled"] = state_rule is not None
            row["federalTax"] = round(year_federal_tax, 2)
            row["stateTax"] = round(year_state_tax, 2)
            row["stateTaxTableVersion"] = state_table_version
            row["stateTaxNotes"] = (
                list(state_notes)
                if state_rule is not None
                else [
                    f"No reference state-tax rule registered for {state_code}; state tax is not modeled."
                ]
            )
        rows.append(row)

    ending_balances = {
        account_type: round(balances[account_type], 2) for account_type in _ACCOUNT_TYPES
    }
    source_totals = {
        source: {
            "gross": round(values["gross"], 2),
            "tax": round(values["tax"], 2),
            "net": round(values["gross"] - values["tax"], 2),
        }
        for source, values in sorted(source_rollups.items())
    }
    return {
        "years": rows,
        "rollups": {
            "projectionYears": len(rows),
            "currentAge": current_age,
            "terminalAge": terminal_age,
            "retirementAge": retirement_age,
            "totalSpendingTarget": round(total_spending, 2),
            "totalGrossIncome": round(total_gross, 2),
            "totalTax": round(total_tax, 2),
            **(
                {
                    "totalFederalTax": round(total_federal_tax, 2),
                    "totalStateTax": round(total_state_tax, 2),
                }
                if state_requested
                else {}
            ),
            "totalNetIncome": round(total_gross - total_tax, 2),
            "totalGap": round(total_gap, 2),
            "totalSurplusAfterTax": round(total_surplus, 2),
            "firstGapAge": first_gap_age,
            "startingAccountBalances": {
                account_type: round(starting_balances[account_type], 2)
                for account_type in _ACCOUNT_TYPES
            },
            "endingAccountBalances": ending_balances,
            "sourceTotals": source_totals,
            "rmdStartAge": rmd_start_age(birth_year),
            "rmdStartAgePolicyVersion": RMD_START_AGE_POLICY_VERSION,
        },
        "assumptions": {
            "filingStatus": filing_status,
            "taxTableYear": tax_table.year,
            "taxTableVersion": tax_table.table_version,
            "spendingInflationRate": round(spending_inflation_rate, 6),
            "wageGrowthRate": round(wage_growth_rate, 6),
            "expectedReturn": round(expected_return, 6),
            "accountReturns": {
                account_type: round(returns[account_type], 6) for account_type in _ACCOUNT_TYPES
            },
            "withdrawalOrder": ["rmd", "taxable", "traditional", "roth"],
            "socialSecurityClaimAge": None
            if social_security is None
            else social_security.claim_age,
            "socialSecurityFraAge": None if social_security is None else social_security.fra_age,
            "bracketFillTargetRate": bracket_fill_target_rate,
            **(
                {
                    "state": state.upper() if state is not None else None,
                    "residencyChange": None
                    if residency_change is None
                    else {
                        "year": residency_change.year,
                        "from": residency_change.from_state,
                        "to": residency_change.to_state,
                    },
                }
                if state_requested
                else {}
            ),
        },
    }


__all__ = ["IncomeStream", "SocialSecurityIncome", "income_layering"]
