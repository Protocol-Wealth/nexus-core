# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Roth conversion calculator (educational).

Should you convert pre-tax (traditional) dollars to Roth this year? Converting
means paying ordinary income tax now on the converted amount in exchange for
tax-free growth and tax-free, RMD-free withdrawals later. The decision turns on
one comparison: the **effective tax rate you pay to convert today** vs. the
**marginal rate those dollars would face when withdrawn in retirement**.

This calculator computes the conversion's *true incremental* federal tax by
reusing the engine's progressive bracket model (``ordinary_tax``) — i.e.
``ordinary_tax(income + conversion) − ordinary_tax(income)`` — so it captures
bracket creep when a large conversion stacks on top of existing income, rather
than assuming a single flat marginal rate. It then grows both the convert and
don't-convert positions at a fixed rate and compares their after-tax terminal
values.

Documented simplifications (planning illustration, NOT tax advice): US federal
ordinary tax only (state, NIIT, IRMAA, ACA-subsidy and Social-Security-taxation
interactions are out of scope); the retirement tax rate is a single
user-supplied marginal rate (future brackets are unknowable); growth is a fixed
annual rate; and external dollars used to pay the conversion tax are assigned the
same growth rate as the portfolio (so the net benefit is driven by
``retirementMarginalRate`` vs. the effective conversion rate, independent of
whether the tax is paid from the conversion or from outside funds — paying from
outside funds is generally still preferable in reality because those dollars
leave a taxable account, an effect this simplified model does not credit).

Pure + deterministic — no I/O, no market data, no client context.
"""

from __future__ import annotations

from typing import Any

from .tables import reference_bracket_table
from .tax import FilingStatus, ordinary_tax


def roth_conversion(
    *,
    current_taxable_income: float,
    filing_status: FilingStatus,
    conversion_amount: float,
    growth_rate: float,
    years: int,
    retirement_marginal_rate: float,
    taxes_paid_from_conversion: bool = False,
    brackets: list[tuple[float, float]] | None = None,
    std_deduction: float | None = None,
    year: int = 2026,
) -> dict[str, Any]:
    """Compare converting ``conversion_amount`` to Roth now vs. leaving it pre-tax.

    Args:
        current_taxable_income: This year's ordinary income before the conversion
            (gross; the standard deduction is applied by ``ordinary_tax``).
        filing_status: Federal filing status.
        conversion_amount: Pre-tax dollars to convert (must be positive).
        growth_rate: Expected annual total return, decimal (must be > -1).
        years: Years until the dollars would be withdrawn (>= 0).
        retirement_marginal_rate: Marginal rate the traditional dollars would face
            at withdrawal, decimal in [0, 1).
        taxes_paid_from_conversion: If True, the conversion tax is withheld from
            the converted amount (only the remainder seeds the Roth). If False
            (default), the tax is paid from outside funds and the full amount
            seeds the Roth; the outlay is reported as ``externalTaxPaidToday``.
        brackets: Optional ``(upper_bound, rate)`` schedule overriding the built-in
            table, so a caller can inject a snapshot-able bracket table.
        std_deduction: Optional deduction overriding the built-in standard
            deduction (e.g. a senior-adjusted or itemized figure).
        year: Registered federal tax-table year to use when the built-in
            reference basis is needed.

    Returns:
        A dict with the incremental ``conversionTax`` and
        ``effectiveConversionRate``; ``rothSeed`` and ``externalTaxPaidToday``;
        the ``convertedAfterTaxValue`` and ``notConvertedAfterTaxValue`` after
        ``years``; the ``netBenefit`` (positive favors converting); and
        ``breakevenRetirementRate`` — the retirement marginal rate above which
        converting comes out ahead (equal to the effective conversion rate).

    Raises:
        ValueError: On a non-positive conversion amount, a negative income, a
            growth rate <= -1, negative years, or a retirement rate outside [0, 1).
    """
    if conversion_amount <= 0.0:
        raise ValueError("conversion_amount must be positive")
    if current_taxable_income < 0.0:
        raise ValueError("current_taxable_income must be non-negative")
    if growth_rate <= -1.0:
        raise ValueError("growth_rate must be greater than -1")
    if years < 0:
        raise ValueError("years must be non-negative")
    if not 0.0 <= retirement_marginal_rate < 1.0:
        raise ValueError("retirement_marginal_rate must be in [0, 1)")

    tax_table = reference_bracket_table(year) if brackets is None or std_deduction is None else None
    conversion_tax = ordinary_tax(
        current_taxable_income + conversion_amount,
        filing_status,
        brackets=brackets,
        std_deduction=std_deduction,
        year=year,
    ) - ordinary_tax(
        current_taxable_income,
        filing_status,
        brackets=brackets,
        std_deduction=std_deduction,
        year=year,
    )
    effective_conversion_rate = conversion_tax / conversion_amount

    factor = (1.0 + growth_rate) ** years
    external_tax_paid_today = 0.0 if taxes_paid_from_conversion else conversion_tax
    roth_seed = conversion_amount - (conversion_tax if taxes_paid_from_conversion else 0.0)

    converted_after_tax = roth_seed * factor
    not_converted_after_tax = conversion_amount * factor * (1.0 - retirement_marginal_rate)
    # Opportunity cost of paying the tax from outside funds, grown at the same
    # rate (zero when the tax is withheld from the conversion). With this neutral
    # assumption the net benefit reduces to
    #   factor * conversion_amount * (retirement_marginal_rate - effective_rate)
    # in both payment modes.
    external_opportunity_cost = external_tax_paid_today * factor
    net_benefit = converted_after_tax - not_converted_after_tax - external_opportunity_cost

    return {
        "conversionTax": round(conversion_tax, 2),
        "effectiveConversionRate": round(effective_conversion_rate, 4),
        "rothSeed": round(roth_seed, 2),
        "externalTaxPaidToday": round(external_tax_paid_today, 2),
        "convertedAfterTaxValue": round(converted_after_tax, 2),
        "notConvertedAfterTaxValue": round(not_converted_after_tax, 2),
        "netBenefit": round(net_benefit, 2),
        "breakevenRetirementRate": round(effective_conversion_rate, 4),
        "taxTableYear": year,
        "taxTableVersion": (
            tax_table.table_version if tax_table is not None else "caller-provided-unversioned"
        ),
        "taxTableSource": (tax_table.source if tax_table is not None else "caller_provided"),
        "taxTableLastVerified": (
            tax_table.last_verified if tax_table is not None else None
        ),
    }


__all__ = ["roth_conversion"]
