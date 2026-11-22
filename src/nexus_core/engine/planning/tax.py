# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tax-aware withdrawal sequencing (educational).

Given a gross cash need and a de-identified portfolio (taxable / traditional /
roth balances), produce a tax-efficient withdrawal plan: satisfy any Required
Minimum Distribution from the traditional account first, then draw taxable →
traditional → roth, and estimate the tax on each leg.

The tax model is a **documented simplification for planning illustration, not tax
advice**: US federal only, progressive ordinary brackets + standard deduction
(traditional withdrawals + other ordinary income), long-term capital gains at
0/15/20% on an assumed gain fraction of taxable-account draws, and zero tax on
roth. Bracket figures are an illustrative 2025/2026 basis — verify against
current IRS tables for real use. Pure + deterministic; no I/O.

Money paths use ``decimal.Decimal`` so bracket arithmetic, the standard
deduction, ordinary and LTCG tax, RMD draws, and withdrawal sequencing are
exact to the published table values, then quantized to cents (dollar amounts)
and four decimal places (effective rate) with ``ROUND_HALF_EVEN``. Public
results still return those amounts as ``float`` so the existing planning wire
is unchanged. RMD factor-table lookups and integer ages stay as they are;
``rmd_factor`` still returns the published float period.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal

from .state_tax import (
    IncomeSource,
    StateResidencyChange,
    estimate_state_income_tax_components,
    reference_state_tax_rule,
    state_code_for_year,
    state_tax_notes,
)
from .tables import FilingStatus, TableError, reference_bracket_table

AccountType = Literal["taxable", "traditional", "roth"]

_FILING_STATUSES: tuple[FilingStatus, ...] = (
    "single",
    "married_joint",
    "married_separate",
    "head_of_household",
)


class InfeasiblePlanError(ValueError):
    """A well-formed plan that cannot be satisfied (e.g. balances < need)."""


#: Assumed fraction of a taxable-account withdrawal that is long-term capital
#: gain (the rest is return of basis, untaxed). Illustrative.
_TAXABLE_GAIN_FRACTION = 0.5
TAXABLE_WITHDRAWAL_GAIN_FRACTION = _TAXABLE_GAIN_FRACTION

#: Default RMD start age for age-only callers. Birth-year-aware callers should
#: use :func:`rmd_start_age`.
_RMD_START_AGE = 73
RMD_START_AGE_POLICY_VERSION = "secure2.0-goodfaith-73-per-89FR58644"

# APPLICABLE AGE, 1959 COHORT - status as of 2026-07-07:
# SECURE 2.0 §107 drafting error makes both 73 and 75 arguably apply to
# individuals born in 1959. The 2024 final RMD regs (89 FR 58886) reserved
# this issue; the 2024 proposed regs (89 FR 58644) propose age 73. No final
# regulation has been issued. Per IRS Announcements 2025-2 and 2026-7,
# taxpayers must apply a reasonable, good-faith interpretation in the
# interim. This kernel returns 73 for the 1959 cohort as that good-faith
# interpretation, consistent with the proposed regs. Revisit on issuance
# of final regs. Announcement 2026-7's delayed-applicability language covers
# future final regs amending §§1.401(a)(9)-4, -5, and -6; the 1959 applicable-age
# fix sits in a different reserved/proposed section, with no final regulation
# issued as of this policy date. policy_version:
# "secure2.0-goodfaith-73-per-89FR58644".
RmdStartAge = int | float

#: IRS Uniform Lifetime Table (Treas. Reg. §1.401(a)(9)-9(c), 2022+), ages
#: 72..120. Below 72 uses the age-72 row; 120 is the "120 and older" row.
_RMD_FACTORS: dict[int, float] = {
    72: 27.4,
    73: 26.5,
    74: 25.5,
    75: 24.6,
    76: 23.7,
    77: 22.9,
    78: 22.0,
    79: 21.1,
    80: 20.2,
    81: 19.4,
    82: 18.5,
    83: 17.7,
    84: 16.8,
    85: 16.0,
    86: 15.2,
    87: 14.4,
    88: 13.7,
    89: 12.9,
    90: 12.2,
    91: 11.5,
    92: 10.8,
    93: 10.1,
    94: 9.5,
    95: 8.9,
    96: 8.4,
    97: 7.8,
    98: 7.3,
    99: 6.8,
    100: 6.4,
    101: 6.0,
    102: 5.6,
    103: 5.2,
    104: 4.9,
    105: 4.6,
    106: 4.3,
    107: 4.1,
    108: 3.9,
    109: 3.7,
    110: 3.5,
    111: 3.4,
    112: 3.3,
    113: 3.1,
    114: 3.0,
    115: 2.9,
    116: 2.8,
    117: 2.7,
    118: 2.5,
    119: 2.3,
    120: 2.0,
}
_RMD_TABLE_FIRST_AGE = 72
_RMD_TABLE_LAST_AGE = 120


def _require_whole_age(age: object) -> int:
    """Coerce a whole-number age; reject bools and non-integers at runtime."""
    if (
        isinstance(age, bool)
        or not isinstance(age, (int, float))
        or not math.isfinite(age)
        or age != int(age)
    ):
        raise ValueError(f"age must be a whole number; got {age!r}")
    return int(age)


_CENTS = Decimal("0.01")
_RATE_PLACES = Decimal("0.0001")
_TAXABLE_GAIN_FRACTION_DEC = Decimal("0.5")


def _as_amount(value: object, *, name: str) -> Decimal:
    """Parse a finite number as Decimal.

    ``bool`` is rejected (it is a subclass of ``int``). Floats are converted
    through ``str`` so a decimal literal does not pick up a binary-float
    encoding of a different value.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a finite number")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        amount = Decimal(str(value))
    else:
        raise ValueError(f"{name} must be a finite number")
    if not amount.is_finite():
        raise ValueError(f"{name} must be a finite number")
    return amount


def _as_money(value: object, *, name: str) -> Decimal:
    """Parse a non-negative finite money amount."""
    amount = _as_amount(value, name=name)
    if amount < 0:
        raise ValueError(f"{name} must be non-negative")
    return amount


def _as_bound(value: object, *, name: str) -> Decimal:
    """Parse a bracket upper bound; ``+Infinity`` is allowed."""
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be a finite number or +Infinity")
    if isinstance(value, Decimal):
        if value.is_infinite() and value > 0:
            return value
        if not value.is_finite():
            raise ValueError(f"{name} must be a finite number or +Infinity")
        return value
    if isinstance(value, float) and math.isinf(value):
        if value > 0:
            return Decimal("Infinity")
        raise ValueError(f"{name} must be a finite number or +Infinity")
    return _as_amount(value, name=name)


def _quantize(value: Decimal, quantum: Decimal) -> float:
    return float(value.quantize(quantum, rounding=ROUND_HALF_EVEN))


def _rmd_factor(age: int) -> float:
    age = _require_whole_age(age)
    if age <= _RMD_TABLE_FIRST_AGE:
        return _RMD_FACTORS[_RMD_TABLE_FIRST_AGE]
    if age >= _RMD_TABLE_LAST_AGE:
        return _RMD_FACTORS[_RMD_TABLE_LAST_AGE]
    return _RMD_FACTORS[age]


#: Public alias — the SECURE 2.0 age at which RMDs begin.
RMD_START_AGE = _RMD_START_AGE


def rmd_start_age(birth_year: int | None = None) -> RmdStartAge:
    """RMD applicable age under the engine's SECURE/SECURE 2.0 policy.

    ``None`` preserves the legacy age-only tool contract and returns 73. With a
    birth year, the policy follows the 2024 final-regulation table and the 1959
    good-faith interpretation documented in ``RMD_START_AGE_POLICY_VERSION``.

    The public-safe contract uses year of birth, not date of birth. Therefore a
    1949 input cannot distinguish the pre-July-1 cohort; this function applies
    the year-level planning convention of age 72 for 1949 and 1950.
    """
    if birth_year is None:
        return RMD_START_AGE
    if isinstance(birth_year, bool) or not isinstance(birth_year, int):
        raise ValueError(f"birthYear must be a whole number; got {birth_year!r}")
    if birth_year < 1900 or birth_year > 2200:
        raise ValueError(f"birthYear must be a plausible year; got {birth_year!r}")
    if birth_year <= 1948:
        return 70.5
    if birth_year <= 1950:
        return 72
    if birth_year <= 1959:
        return 73
    return 75


def rmd_factor(age: int) -> float:
    """IRS Uniform Lifetime Table distribution period for ``age`` (rows 72..120; clamped at both ends).

    ``age`` must be a whole number. A float such as ``73.0`` is accepted; a
    non-integer such as ``73.5`` raises ``ValueError`` rather than ``KeyError``.
    """
    return _rmd_factor(age)


def ordinary_brackets(
    filing_status: FilingStatus, *, year: int = 2026
) -> list[tuple[float, float]]:
    """Progressive ordinary brackets ``(upper_bound, rate)`` in taxable-income space."""
    return reference_bracket_table(year).brackets_for(filing_status)


def standard_deduction(filing_status: FilingStatus, *, year: int = 2026) -> float:
    """Standard deduction for ``filing_status`` (illustrative current basis)."""
    return _quantize(
        _as_amount(
            reference_bracket_table(year).standard_deduction[filing_status],
            name="standard deduction",
        ),
        _CENTS,
    )


def _load_brackets(
    filing_status: FilingStatus,
    *,
    brackets: list[tuple[float, float]] | None,
    std_deduction: float | Decimal | None,
    year: int,
) -> tuple[list[tuple[Decimal, Decimal]], Decimal]:
    if brackets is None or std_deduction is None:
        table = reference_bracket_table(year)
        ded_raw: float | Decimal = (
            table.standard_deduction[filing_status] if std_deduction is None else std_deduction
        )
        brk_raw = table.brackets_for(filing_status) if brackets is None else brackets
    else:
        ded_raw = std_deduction
        brk_raw = brackets
    parsed = [
        (
            _as_bound(upper, name="bracket upper bound"),
            _as_amount(rate, name="bracket rate"),
        )
        for upper, rate in brk_raw
    ]
    return parsed, _as_amount(ded_raw, name="standard deduction")


def _ordinary_tax_dec(
    income: float | Decimal,
    filing_status: FilingStatus,
    *,
    brackets: list[tuple[float, float]] | None = None,
    std_deduction: float | Decimal | None = None,
    year: int = 2026,
) -> Decimal:
    brk, ded = _load_brackets(
        filing_status, brackets=brackets, std_deduction=std_deduction, year=year
    )
    taxable = _as_amount(income, name="income") - ded
    if taxable < 0:
        taxable = Decimal("0")
    tax = Decimal("0")
    lower = Decimal("0")
    for upper, rate in brk:
        if taxable <= lower:
            break
        slice_top = taxable if taxable < upper else upper
        tax += (slice_top - lower) * rate
        lower = upper
    return tax


def ordinary_tax(
    income: float | Decimal,
    filing_status: FilingStatus,
    *,
    brackets: list[tuple[float, float]] | None = None,
    std_deduction: float | Decimal | None = None,
    year: int = 2026,
) -> float:
    """Progressive federal ordinary tax after the standard deduction.

    Computed in ``decimal.Decimal`` and quantized to cents with
    ``ROUND_HALF_EVEN``. The return value is a JSON-safe ``float``.

    ``brackets`` and ``std_deduction`` override the engine's built-in figures so a
    caller can inject a snapshot-able table (the composite Roth/IRMAA analysis
    does this); both default to the built-in current-basis values.
    """
    return _quantize(
        _ordinary_tax_dec(
            income,
            filing_status,
            brackets=brackets,
            std_deduction=std_deduction,
            year=year,
        ),
        _CENTS,
    )


def _ltcg_tax_dec(
    gains: float | Decimal,
    ordinary_income: float | Decimal,
    filing_status: FilingStatus,
    *,
    year: int,
) -> Decimal:
    """LTCG tax; rate selected by where ordinary income sits in the breakpoints."""
    gains_dec = _as_amount(gains, name="gains")
    if gains_dec <= 0:
        return Decimal("0")
    ordinary_dec = _as_amount(ordinary_income, name="ordinary income")
    zero_upper, fifteen_upper = reference_bracket_table(year).ltcg_breakpoints[filing_status]
    zero_u = _as_amount(zero_upper, name="ltcg zero breakpoint")
    fifteen_u = _as_amount(fifteen_upper, name="ltcg fifteen breakpoint")
    if ordinary_dec < zero_u:
        rate = Decimal("0")
    elif ordinary_dec < fifteen_u:
        rate = Decimal("0.15")
    else:
        rate = Decimal("0.20")
    return gains_dec * rate


def ltcg_tax(
    gains: float | Decimal,
    ordinary_income: float | Decimal,
    filing_status: FilingStatus,
    *,
    year: int = 2026,
) -> float:
    """Long-term capital-gain tax using the shared planning bracket table.

    Computed in ``decimal.Decimal`` and quantized to cents with
    ``ROUND_HALF_EVEN``. The return value is a JSON-safe ``float``. Rate
    selection still uses a strict ``<`` against the published breakpoints, so
    income exactly at a breakpoint uses the next rate.
    """
    return _quantize(_ltcg_tax_dec(gains, ordinary_income, filing_status, year=year), _CENTS)


def tax_aware_withdrawal(
    *,
    year: int,
    filing_status: str,
    accounts: list[dict[str, Any]],
    gross_need: float | Decimal,
    age: int,
    other_taxable_income: float | Decimal,
    birth_year: int | None = None,
    state: str | None = None,
    residency_change: StateResidencyChange | None = None,
    projection_year: int | None = None,
) -> dict[str, Any]:
    """Return the tax-aware withdrawal plan. Raises ``ValueError`` on bad input.

    ``year`` selects the bracket basis (a single illustrative 2025/2026 table is
    used for all years here). Ordering: RMD from traditional first, then
    taxable → traditional → roth. Dollar amounts are computed in Decimal and
    returned as cents-quantized floats.
    """
    if filing_status not in _FILING_STATUSES:
        raise ValueError(f"filingStatus must be one of {', '.join(_FILING_STATUSES)}")
    status: FilingStatus = filing_status
    try:
        need = _as_money(gross_need, name="grossNeed")
    except ValueError as exc:
        raise ValueError("grossNeed must be non-negative") from exc
    try:
        tax_table = reference_bracket_table(year)
    except TableError as exc:
        raise ValueError(str(exc)) from exc

    balances: dict[str, Decimal] = {
        "taxable": Decimal("0"),
        "traditional": Decimal("0"),
        "roth": Decimal("0"),
    }
    for account in accounts:
        acct_type = account.get("type")
        if acct_type not in balances:
            raise ValueError(f"account type must be taxable/traditional/roth; got {acct_type!r}")
        balance = account.get("balance", 0.0)
        try:
            balances[acct_type] += _as_money(balance, name="account balance")
        except ValueError as exc:
            raise ValueError(
                f"account balance must be a non-negative number; got {balance!r}"
            ) from exc

    withdrawn: dict[str, Decimal] = {
        "taxable": Decimal("0"),
        "traditional": Decimal("0"),
        "roth": Decimal("0"),
    }
    remaining = need

    # 1. RMD from traditional (mandatory) — counts toward the need.
    start_age = rmd_start_age(birth_year)
    if age >= start_age:
        period = Decimal(str(_rmd_factor(age)))
        rmd = balances["traditional"] / period
    else:
        rmd = Decimal("0")
    rmd_draw = rmd if rmd < balances["traditional"] else balances["traditional"]
    rmd_draw = rmd_draw.quantize(_CENTS, rounding=ROUND_HALF_EVEN)
    withdrawn["traditional"] += rmd_draw
    balances["traditional"] -= rmd_draw
    remaining -= rmd_draw

    # 2. Fill the remaining need: taxable → traditional → roth.
    for acct_type in ("taxable", "traditional", "roth"):
        if remaining <= 0:
            break
        available = balances[acct_type]
        draw = remaining if remaining < available else available
        draw = draw.quantize(_CENTS, rounding=ROUND_HALF_EVEN)
        if draw <= 0:
            continue
        withdrawn[acct_type] += draw
        balances[acct_type] -= draw
        remaining -= draw

    if remaining.quantize(_CENTS, rounding=ROUND_HALF_EVEN) > 0:
        raise InfeasiblePlanError(
            f"insufficient account balances to meet grossNeed of {float(need):,.0f}; "
            f"short by {float(remaining.quantize(_CENTS, rounding=ROUND_HALF_EVEN)):,.0f}"
        )

    # 3. Taxes. Traditional is ordinary income (marginal, stacked on other income);
    #    taxable account's assumed gain fraction is LTCG; roth is tax-free.
    base = _as_amount(other_taxable_income, name="otherTaxableIncome")
    trad = withdrawn["traditional"]
    tax_traditional = _ordinary_tax_dec(base + trad, status, year=year) - _ordinary_tax_dec(
        base, status, year=year
    )
    gains = withdrawn["taxable"] * _TAXABLE_GAIN_FRACTION_DEC
    tax_taxable = _ltcg_tax_dec(gains, base + trad, status, year=year)

    tax_by_type = {"taxable": tax_taxable, "traditional": tax_traditional, "roth": Decimal("0")}
    state_by_type = {"taxable": Decimal("0"), "traditional": Decimal("0"), "roth": Decimal("0")}
    state_meta: dict[str, Any] | None = None
    state_code = state_code_for_year(
        base_state=state,
        residency_change=residency_change,
        year=year if projection_year is None else projection_year,
    )
    if state_code is not None:
        try:
            state_rule = reference_state_tax_rule(state_code, year)
        except TableError as exc:
            raise ValueError(str(exc)) from exc
        if state_rule is None:
            state_meta = {
                "stateCode": state_code,
                "stateTaxModeled": False,
                "stateTax": 0.0,
                "stateTaxTableVersion": None,
                "stateTaxTableSource": None,
                "stateTaxTableLastVerified": None,
                "stateTaxNotes": [
                    f"No reference state-tax rule registered for {state_code}; state tax is not modeled."
                ],
            }
        else:
            state_components: list[tuple[str, IncomeSource, float]] = [
                ("taxable", "taxable_gain", float(gains)),
                ("traditional", "traditional_distribution", float(trad)),
                ("roth", "roth_distribution", float(withdrawn["roth"])),
            ]
            baseline = base if base > 0 else Decimal("0")
            state_estimates = estimate_state_income_tax_components(
                state_rule,
                state_components,
                age=age,
                filing_status=status,
                total_income=float(baseline + trad + gains),
                baseline_taxable_income=float(baseline),
            )
            for acct_type in ("taxable", "traditional", "roth"):
                estimate = state_estimates.get(acct_type)
                state_by_type[acct_type] = (
                    _as_amount(estimate.tax, name="state tax")
                    if estimate is not None
                    else Decimal("0")
                )
            state_total = sum(state_by_type.values(), start=Decimal("0"))
            state_meta = {
                "stateCode": state_code,
                "stateTaxModeled": True,
                "stateTax": _quantize(state_total, _CENTS),
                "stateTaxTableVersion": state_rule.table_version,
                "stateTaxTableSource": state_rule.source,
                "stateTaxTableLastVerified": state_rule.last_verified,
                "stateTaxNotes": list(state_tax_notes(state_rule, tuple(state_estimates.values()))),
            }
    rows = [
        {
            "type": acct_type,
            "gross": _quantize(withdrawn[acct_type], _CENTS),
            "tax": _quantize(tax_by_type[acct_type] + state_by_type[acct_type], _CENTS),
            **(
                {
                    "federalTax": _quantize(tax_by_type[acct_type], _CENTS),
                    "stateTax": _quantize(state_by_type[acct_type], _CENTS),
                }
                if state_meta is not None
                else {}
            ),
        }
        for acct_type in ("taxable", "traditional", "roth")
        if withdrawn[acct_type] > 0
    ]
    total_tax = tax_taxable + tax_traditional + sum(state_by_type.values(), start=Decimal("0"))
    total_gross = sum(withdrawn.values(), start=Decimal("0"))
    effective_rate = (total_tax / total_gross) if total_gross > 0 else Decimal("0")
    rmd_target = rmd.quantize(_CENTS, rounding=ROUND_HALF_EVEN)
    result: dict[str, Any] = {
        "withdrawals": rows,
        "totalTax": _quantize(total_tax, _CENTS),
        "effectiveRate": _quantize(effective_rate, _RATE_PLACES),
        "federalTax": _quantize(tax_taxable + tax_traditional, _CENTS),
        "rmdStartAge": start_age,
        "rmdStartAgePolicyVersion": RMD_START_AGE_POLICY_VERSION,
        "taxTableYear": tax_table.year,
        "taxTableVersion": tax_table.table_version,
        "taxTableSource": tax_table.source,
        "taxTableLastVerified": tax_table.last_verified,
        "rmdSatisfied": withdrawn["traditional"] >= rmd_target,
    }
    if state_meta is not None:
        result.update(state_meta)
    return result


__all__ = [
    "RMD_START_AGE",
    "RMD_START_AGE_POLICY_VERSION",
    "RmdStartAge",
    "FilingStatus",
    "InfeasiblePlanError",
    "ordinary_brackets",
    "ordinary_tax",
    "ltcg_tax",
    "rmd_factor",
    "rmd_start_age",
    "standard_deduction",
    "TAXABLE_WITHDRAWAL_GAIN_FRACTION",
    "tax_aware_withdrawal",
]
