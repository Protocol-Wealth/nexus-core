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
"""

from __future__ import annotations

from typing import Any, Literal

FilingStatus = Literal["single", "married_joint", "married_separate", "head_of_household"]
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

#: RMDs begin at this age (SECURE 2.0).
_RMD_START_AGE = 73

#: 2025 standard deduction by filing status (illustrative basis).
_STD_DEDUCTION: dict[FilingStatus, float] = {
    "single": 15_000.0,
    "married_joint": 30_000.0,
    "married_separate": 15_000.0,
    "head_of_household": 22_500.0,
}

#: Ordinary brackets: (upper_bound_of_bracket, marginal_rate); last is open-ended.
_ORDINARY_BRACKETS: dict[FilingStatus, list[tuple[float, float]]] = {
    "single": [
        (11_925, 0.10), (48_475, 0.12), (103_350, 0.22), (197_300, 0.24),
        (250_525, 0.32), (626_350, 0.35), (float("inf"), 0.37),
    ],
    "married_joint": [
        (23_850, 0.10), (96_950, 0.12), (206_700, 0.22), (394_600, 0.24),
        (501_050, 0.32), (751_600, 0.35), (float("inf"), 0.37),
    ],
    "married_separate": [
        (11_925, 0.10), (48_475, 0.12), (103_350, 0.22), (197_300, 0.24),
        (250_525, 0.32), (375_800, 0.35), (float("inf"), 0.37),
    ],
    "head_of_household": [
        (17_000, 0.10), (64_850, 0.12), (103_350, 0.22), (197_300, 0.24),
        (250_500, 0.32), (626_350, 0.35), (float("inf"), 0.37),
    ],
}

#: Long-term capital-gains breakpoints: (0%_upper, 15%_upper); above ⇒ 20%.
_LTCG_BREAKPOINTS: dict[FilingStatus, tuple[float, float]] = {
    "single": (48_350, 533_400),
    "married_joint": (96_700, 600_050),
    "married_separate": (48_350, 300_000),
    "head_of_household": (64_750, 566_700),
}

#: IRS Uniform Lifetime Table factors (2022+), ages 73..100. Beyond ⇒ last value.
_RMD_FACTORS: dict[int, float] = {
    73: 26.5, 74: 25.5, 75: 24.6, 76: 23.7, 77: 22.9, 78: 22.0, 79: 21.1,
    80: 20.2, 81: 19.4, 82: 18.5, 83: 17.7, 84: 16.8, 85: 16.0, 86: 15.2,
    87: 14.4, 88: 13.7, 89: 12.9, 90: 12.2, 91: 11.5, 92: 10.8, 93: 10.1,
    94: 9.5, 95: 8.9, 96: 8.4, 97: 7.8, 98: 7.3, 99: 6.8, 100: 6.4,
}


def _rmd_factor(age: int) -> float:
    if age <= _RMD_START_AGE:
        return _RMD_FACTORS[_RMD_START_AGE]
    return _RMD_FACTORS.get(age, _RMD_FACTORS[100])


#: Public alias — the SECURE 2.0 age at which RMDs begin.
RMD_START_AGE = _RMD_START_AGE


def rmd_factor(age: int) -> float:
    """IRS Uniform Lifetime Table distribution period for ``age`` (clamped to 73+)."""
    return _rmd_factor(age)


def ordinary_brackets(filing_status: FilingStatus) -> list[tuple[float, float]]:
    """Progressive ordinary brackets ``(upper_bound, rate)`` in taxable-income space."""
    return list(_ORDINARY_BRACKETS[filing_status])


def standard_deduction(filing_status: FilingStatus) -> float:
    """Standard deduction for ``filing_status`` (illustrative current basis)."""
    return _STD_DEDUCTION[filing_status]


def ordinary_tax(
    income: float,
    filing_status: FilingStatus,
    *,
    brackets: list[tuple[float, float]] | None = None,
    std_deduction: float | None = None,
) -> float:
    """Progressive federal ordinary tax after the standard deduction.

    ``brackets`` and ``std_deduction`` override the engine's built-in figures so a
    caller can inject a snapshot-able table (the composite Roth/IRMAA analysis
    does this); both default to the built-in current-basis values.
    """
    ded = _STD_DEDUCTION[filing_status] if std_deduction is None else std_deduction
    brk = _ORDINARY_BRACKETS[filing_status] if brackets is None else brackets
    taxable = max(0.0, income - ded)
    tax = 0.0
    lower = 0.0
    for upper, rate in brk:
        if taxable <= lower:
            break
        slice_top = min(taxable, upper)
        tax += (slice_top - lower) * rate
        lower = upper
    return tax


def _ltcg_tax(gains: float, ordinary_income: float, filing_status: FilingStatus) -> float:
    """LTCG tax; rate selected by where ordinary income sits in the breakpoints."""
    if gains <= 0:
        return 0.0
    zero_upper, fifteen_upper = _LTCG_BREAKPOINTS[filing_status]
    if ordinary_income < zero_upper:
        rate = 0.0
    elif ordinary_income < fifteen_upper:
        rate = 0.15
    else:
        rate = 0.20
    return gains * rate


def tax_aware_withdrawal(
    *,
    year: int,
    filing_status: str,
    accounts: list[dict[str, Any]],
    gross_need: float,
    age: int,
    other_taxable_income: float,
) -> dict[str, Any]:
    """Return the tax-aware withdrawal plan. Raises ``ValueError`` on bad input.

    ``year`` selects the bracket basis (a single illustrative 2025/2026 table is
    used for all years here). Ordering: RMD from traditional first, then
    taxable → traditional → roth.
    """
    if filing_status not in _FILING_STATUSES:
        raise ValueError(f"filingStatus must be one of {', '.join(_FILING_STATUSES)}")
    status: FilingStatus = filing_status
    if gross_need < 0:
        raise ValueError("grossNeed must be non-negative")

    balances: dict[str, float] = {"taxable": 0.0, "traditional": 0.0, "roth": 0.0}
    for account in accounts:
        acct_type = account.get("type")
        if acct_type not in balances:
            raise ValueError(f"account type must be taxable/traditional/roth; got {acct_type!r}")
        balance = account.get("balance", 0.0)
        if not isinstance(balance, (int, float)) or isinstance(balance, bool) or balance < 0:
            raise ValueError(f"account balance must be a non-negative number; got {balance!r}")
        balances[acct_type] += float(balance)

    withdrawn: dict[str, float] = {"taxable": 0.0, "traditional": 0.0, "roth": 0.0}
    remaining = gross_need

    # 1. RMD from traditional (mandatory) — counts toward the need.
    rmd = balances["traditional"] / _rmd_factor(age) if age >= _RMD_START_AGE else 0.0
    rmd_draw = min(rmd, balances["traditional"])
    withdrawn["traditional"] += rmd_draw
    balances["traditional"] -= rmd_draw
    remaining -= rmd_draw

    # 2. Fill the remaining need: taxable → traditional → roth.
    for acct_type in ("taxable", "traditional", "roth"):
        if remaining <= 1e-9:
            break
        draw = min(remaining, balances[acct_type])
        withdrawn[acct_type] += draw
        balances[acct_type] -= draw
        remaining -= draw

    if remaining > 1e-6:
        raise InfeasiblePlanError(
            f"insufficient account balances to meet grossNeed of {gross_need:,.0f}; "
            f"short by {remaining:,.0f}"
        )

    # 3. Taxes. Traditional is ordinary income (marginal, stacked on other income);
    #    taxable account's assumed gain fraction is LTCG; roth is tax-free.
    base = other_taxable_income
    trad = withdrawn["traditional"]
    tax_traditional = ordinary_tax(base + trad, status) - ordinary_tax(base, status)
    gains = withdrawn["taxable"] * _TAXABLE_GAIN_FRACTION
    tax_taxable = _ltcg_tax(gains, base + trad, status)

    tax_by_type = {"taxable": tax_taxable, "traditional": tax_traditional, "roth": 0.0}
    rows = [
        {"type": acct_type, "gross": round(withdrawn[acct_type], 2), "tax": round(tax_by_type[acct_type], 2)}
        for acct_type in ("taxable", "traditional", "roth")
        if withdrawn[acct_type] > 0
    ]
    total_tax = tax_taxable + tax_traditional
    total_gross = sum(withdrawn.values())
    effective_rate = total_tax / total_gross if total_gross > 0 else 0.0
    return {
        "withdrawals": rows,
        "totalTax": round(total_tax, 2),
        "effectiveRate": round(effective_rate, 4),
        "rmdSatisfied": withdrawn["traditional"] + 1e-6 >= rmd,
    }


__all__ = [
    "RMD_START_AGE",
    "FilingStatus",
    "InfeasiblePlanError",
    "ordinary_brackets",
    "ordinary_tax",
    "rmd_factor",
    "standard_deduction",
    "tax_aware_withdrawal",
]
