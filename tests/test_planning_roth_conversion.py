# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the Roth conversion calculator."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import roth_conversion
from nexus_core.engine.planning.tax import ordinary_tax


def test_conversion_tax_is_the_incremental_ordinary_tax() -> None:
    """The conversion tax must equal the bracket-creep-aware incremental tax."""
    income, conversion = 100_000.0, 80_000.0
    expected = ordinary_tax(income + conversion, "single") - ordinary_tax(
        income, "single"
    )
    out = roth_conversion(
        current_taxable_income=income,
        filing_status="single",
        conversion_amount=conversion,
        growth_rate=0.05,
        years=10,
        retirement_marginal_rate=0.24,
    )
    assert out["conversionTax"] == round(expected, 2)
    assert out["effectiveConversionRate"] == round(expected / conversion, 4)
    # A large conversion stacking on income should creep past one flat bracket.
    assert out["effectiveConversionRate"] > 0.0


def test_single_bracket_conversion_hand_values() -> None:
    """$10k conversion that stays inside the 22% bracket (single, $100k income)."""
    factor = 1.05**10
    out = roth_conversion(
        current_taxable_income=100_000.0,
        filing_status="single",
        conversion_amount=10_000.0,
        growth_rate=0.05,
        years=10,
        retirement_marginal_rate=0.24,
        taxes_paid_from_conversion=True,
    )
    assert out["conversionTax"] == 2_200.0  # 10k * 22%
    assert out["effectiveConversionRate"] == 0.22
    assert out["rothSeed"] == 7_800.0
    assert out["externalTaxPaidToday"] == 0.0
    assert out["convertedAfterTaxValue"] == pytest.approx(7_800.0 * factor, abs=0.01)
    assert out["notConvertedAfterTaxValue"] == pytest.approx(
        10_000.0 * factor * 0.76, abs=0.01
    )
    # benefit = factor * amount * (retirement_rate - effective_rate)
    assert out["netBenefit"] == pytest.approx(10_000.0 * factor * 0.02, abs=0.01)


def test_breakeven_is_the_effective_conversion_rate() -> None:
    base = {
        "current_taxable_income": 120_000.0,
        "filing_status": "married_joint",
        "conversion_amount": 60_000.0,
        "growth_rate": 0.06,
        "years": 15,
    }
    eff = roth_conversion(**base, retirement_marginal_rate=0.10)[
        "breakevenRetirementRate"
    ]
    # Above breakeven -> converting wins; below -> it loses; at it -> ~neutral.
    assert roth_conversion(**base, retirement_marginal_rate=eff + 0.05)["netBenefit"] > 0
    assert roth_conversion(**base, retirement_marginal_rate=eff - 0.05)["netBenefit"] < 0
    # `eff` is the breakeven rate rounded to 4 decimals, so feeding it back leaves
    # only a rounding residual (~ amount * factor * 5e-4), not exactly zero.
    at_breakeven = roth_conversion(**base, retirement_marginal_rate=eff)["netBenefit"]
    assert abs(at_breakeven) < 60_000.0 * (1.06**15) * 5e-4


def test_payment_mode_changes_seed_but_not_net_benefit() -> None:
    base = {
        "current_taxable_income": 90_000.0,
        "filing_status": "single",
        "conversion_amount": 50_000.0,
        "growth_rate": 0.05,
        "years": 20,
        "retirement_marginal_rate": 0.28,
    }
    from_outside = roth_conversion(**base, taxes_paid_from_conversion=False)
    from_account = roth_conversion(**base, taxes_paid_from_conversion=True)

    # Seed + today's cash differ between the modes...
    assert from_outside["rothSeed"] == 50_000.0
    assert from_outside["externalTaxPaidToday"] == from_outside["conversionTax"]
    assert from_account["rothSeed"] == round(
        50_000.0 - from_account["conversionTax"], 2
    )
    assert from_account["externalTaxPaidToday"] == 0.0
    # ...but the net benefit is mode-invariant under the equal-growth assumption.
    assert from_outside["netBenefit"] == pytest.approx(
        from_account["netBenefit"], abs=0.01
    )


def test_zero_years_is_present_value() -> None:
    out = roth_conversion(
        current_taxable_income=50_000.0,
        filing_status="single",
        conversion_amount=20_000.0,
        growth_rate=0.07,
        years=0,
        retirement_marginal_rate=0.22,
        taxes_paid_from_conversion=True,
    )
    # factor == 1: values are just today's after-tax amounts.
    assert out["convertedAfterTaxValue"] == round(20_000.0 - out["conversionTax"], 2)
    assert out["notConvertedAfterTaxValue"] == round(20_000.0 * 0.78, 2)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"conversion_amount": 0.0}, "conversion_amount must be positive"),
        ({"current_taxable_income": -1.0}, "must be non-negative"),
        ({"growth_rate": -1.0}, "greater than -1"),
        ({"years": -1}, "years must be non-negative"),
        ({"retirement_marginal_rate": 1.0}, r"\[0, 1\)"),
        ({"retirement_marginal_rate": -0.1}, r"\[0, 1\)"),
    ],
)
def test_validation(kwargs: dict[str, object], match: str) -> None:
    base = {
        "current_taxable_income": 80_000.0,
        "filing_status": "single",
        "conversion_amount": 25_000.0,
        "growth_rate": 0.05,
        "years": 10,
        "retirement_marginal_rate": 0.24,
    }
    base.update(kwargs)
    with pytest.raises(ValueError, match=match):
        roth_conversion(**base)  # type: ignore[arg-type]
