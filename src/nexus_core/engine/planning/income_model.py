# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Income → tax model for the composite Roth-conversion analysis.

Reduces an :class:`~nexus_core.engine.planning.case.IncomeExConversion` (plus a
candidate conversion amount) to the figures the composite needs: taxable Social
Security, AGI, the IRMAA + NIIT MAGIs, ordinary taxable income, and the three
federal tax components (ordinary, preferential-rate LTCG, NIIT). Computing them
together is what captures the interactions a flat-rate model misses:

- **Social-Security "tax torpedo"** — a conversion is a Traditional-IRA
  distribution, so it enters provisional income and can pull more Social Security
  into taxability, taxing the conversion at more than its bracket rate.
- **LTCG stacking** — ordinary conversion income stacks *under* the preferential
  stack, lifting long-term gains / qualified dividends from 0% into 15%/20%.
- **NIIT** — the conversion is not itself net investment income, but it raises
  MAGI, which can pull existing NII over the 3.8% threshold.

Documented simplifications (planning illustration, NOT tax advice): US federal
only; capital losses net to an AGI offset capped at $3,000/yr with no carryover;
short-term gains are treated as ordinary; the OBBBA senior-bonus phaseout keys off
the IRMAA MAGI; Social-Security taxability uses the standard worksheet with the
statutory base/additional thresholds. Pure + deterministic; no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from .case import IncomeExConversion
from .tables import BracketTable
from .tax import FilingStatus, ordinary_tax

_MAX_CAPITAL_LOSS_OFFSET = 3_000.0


def ss_taxable(ss_gross: float, provisional: float, base: float, additional: float) -> float:
    """Taxable portion of Social Security via the IRS provisional-income worksheet."""
    if ss_gross <= 0.0:
        return 0.0
    if provisional <= base:
        return 0.0
    if provisional <= additional:
        return min(0.5 * ss_gross, 0.5 * (provisional - base))
    lower_band = min(0.5 * ss_gross, 0.5 * (additional - base))
    return min(0.85 * ss_gross, 0.85 * (provisional - additional) + lower_band)


def marginal_ordinary_rate(taxable: float, brackets: list[tuple[float, float]]) -> float:
    """Marginal rate the top dollar of ``taxable`` falls in."""
    for upper, rate in brackets:
        if taxable < upper:
            return rate
    return brackets[-1][1]


def marginal_ltcg_rate(stack_top: float, breakpoints: tuple[float, float]) -> float:
    """Preferential rate at a given top-of-stack income level."""
    zero_upper, fifteen_upper = breakpoints
    if stack_top < zero_upper:
        return 0.0
    if stack_top < fifteen_upper:
        return 0.15
    return 0.20


def stacked_ltcg_tax(
    ordinary_taxable: float, preferential: float, breakpoints: tuple[float, float]
) -> float:
    """Tax on ``preferential`` income stacked on top of ``ordinary_taxable``."""
    if preferential <= 0.0:
        return 0.0
    zero_upper, fifteen_upper = breakpoints
    start = ordinary_taxable
    end = ordinary_taxable + preferential
    band_15 = max(0.0, min(end, fifteen_upper) - max(start, zero_upper))
    band_20 = max(0.0, end - max(start, fifteen_upper))
    return 0.15 * band_15 + 0.20 * band_20


@dataclass(frozen=True, slots=True)
class FederalPicture:
    """The federal tax picture at one conversion level (internal to the composite)."""

    conversion_taxable: float
    taxable_ss: float
    agi: float
    magi_irmaa: float
    magi_niit: float
    preferential_income: float
    net_investment_income: float
    ordinary_taxable: float
    deduction: float
    ordinary_tax: float
    ltcg_tax: float
    niit: float
    marginal_ordinary_rate: float
    marginal_ltcg_rate: float

    @property
    def total_tax(self) -> float:
        return self.ordinary_tax + self.ltcg_tax + self.niit


def _itemized(income: IncomeExConversion) -> float | None:
    ded = income.itemized_or_standard
    return None if ded == "standard" else float(ded)


def federal_picture(
    income: IncomeExConversion,
    fs: FilingStatus,
    bt: BracketTable,
    *,
    n_seniors: int,
    conversion_taxable: float,
) -> FederalPicture:
    """Full federal tax picture with ``conversion_taxable`` added as ordinary income.

    ``conversion_taxable`` is the *taxable* portion of the conversion (after the
    pro-rata basis split); pass 0.0 for the before-conversion baseline.
    """
    net_cap = income.short_term_gains + income.long_term_gains
    agi_capital = net_cap if net_cap >= 0.0 else max(net_cap, -_MAX_CAPITAL_LOSS_OFFSET)

    # Preferential stack: qualified dividends + the long-term gain surviving netting.
    pref_ltcg = min(max(0.0, income.long_term_gains), max(0.0, net_cap))
    preferential = income.qualified_dividends + pref_ltcg

    # Net investment income for NIIT (tax-exempt interest is NOT investment income).
    nii = income.taxable_interest + income.ordinary_dividends + max(0.0, net_cap)

    agi_excl_ss = (
        income.wages
        + income.pension
        + income.taxable_interest
        + income.ordinary_dividends
        + income.other_ordinary
        + agi_capital
        - income.above_the_line
        + conversion_taxable
    )
    base, additional = bt.ss_provisional_thresholds[fs]
    provisional = agi_excl_ss + income.tax_exempt_interest + 0.5 * income.social_security_gross
    taxable_ss = ss_taxable(income.social_security_gross, provisional, base, additional)

    agi = agi_excl_ss + taxable_ss
    magi_irmaa = agi + income.tax_exempt_interest
    magi_niit = agi

    deduction = bt.total_deduction(
        fs, itemized=_itemized(income), n_seniors=n_seniors, magi=magi_irmaa
    )
    brackets = bt.brackets_for(fs)
    breakpoints = bt.ltcg_breakpoints[fs]

    # IRS Qualified-Dividends & Capital-Gain worksheet ordering: the full
    # deduction reduces *taxable income*, and preferential income (LTCG +
    # qualified dividends) stacks on top of the post-deduction ordinary base — so
    # deduction left over after ordinary income shelters preferential income
    # first (it is NOT dropped). ``pref_taxable`` is the preferential amount that
    # survives the deduction; ``ordinary_taxable`` is the rest of taxable income.
    taxable_income = max(0.0, agi - deduction)
    pref_taxable = min(preferential, taxable_income)
    ordinary_taxable = max(0.0, taxable_income - pref_taxable)

    ord_tax = ordinary_tax(ordinary_taxable, fs, brackets=brackets, std_deduction=0.0)
    ltcg = stacked_ltcg_tax(ordinary_taxable, pref_taxable, breakpoints)
    niit = bt.niit_rate * min(nii, max(0.0, magi_niit - bt.niit_threshold[fs]))

    return FederalPicture(
        conversion_taxable=conversion_taxable,
        taxable_ss=taxable_ss,
        agi=agi,
        magi_irmaa=magi_irmaa,
        magi_niit=magi_niit,
        preferential_income=preferential,
        net_investment_income=nii,
        ordinary_taxable=ordinary_taxable,
        deduction=deduction,
        ordinary_tax=ord_tax,
        ltcg_tax=ltcg,
        niit=niit,
        marginal_ordinary_rate=marginal_ordinary_rate(ordinary_taxable, brackets),
        marginal_ltcg_rate=marginal_ltcg_rate(taxable_income, breakpoints),
    )


__all__ = [
    "FederalPicture",
    "federal_picture",
    "marginal_ltcg_rate",
    "marginal_ordinary_rate",
    "ss_taxable",
    "stacked_ltcg_tax",
]
