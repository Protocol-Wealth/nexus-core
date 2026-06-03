# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the income → tax model (SS torpedo, LTCG stacking, NIIT, MAGI)."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning.case import IncomeExConversion
from nexus_core.engine.planning.income_model import (
    federal_picture,
    ss_taxable,
    stacked_ltcg_tax,
)
from nexus_core.engine.planning.tables import reference_bracket_table


def test_ss_taxable_worksheet_bands() -> None:
    assert ss_taxable(20_000, 20_000, 25_000, 34_000) == 0.0  # below base
    assert ss_taxable(20_000, 30_000, 25_000, 34_000) == pytest.approx(2_500.0)  # 50% band
    assert ss_taxable(20_000, 50_000, 25_000, 34_000) == pytest.approx(17_000.0)  # 85% cap


def test_stacked_ltcg_zero_band() -> None:
    assert stacked_ltcg_tax(0.0, 10_000.0, (48_350.0, 533_400.0)) == 0.0


def test_stacked_ltcg_straddles_into_15pct() -> None:
    tax = stacked_ltcg_tax(45_000.0, 10_000.0, (48_350.0, 533_400.0))
    assert tax == pytest.approx((55_000 - 48_350) * 0.15)


def test_stacked_ltcg_into_20pct() -> None:
    tax = stacked_ltcg_tax(530_000.0, 10_000.0, (48_350.0, 533_400.0))
    expected = (533_400 - 530_000) * 0.15 + (540_000 - 533_400) * 0.20
    assert tax == pytest.approx(expected)


def test_magi_irmaa_includes_tax_exempt_interest() -> None:
    bt = reference_bracket_table(2026)
    income = IncomeExConversion(pension=40_000, tax_exempt_interest=8_000)
    p = federal_picture(income, "single", bt, n_seniors=1, conversion_taxable=0.0)
    # MAGI for IRMAA = AGI + tax-exempt interest; NIIT MAGI excludes it.
    assert p.magi_irmaa == pytest.approx(p.magi_niit + 8_000.0)


def test_conversion_triggers_ss_torpedo() -> None:
    bt = reference_bracket_table(2026)
    # Low base income so SS is only partly taxable before the conversion.
    income = IncomeExConversion(pension=12_000, social_security_gross=40_000)
    base = federal_picture(income, "single", bt, n_seniors=1, conversion_taxable=0.0)
    bumped = federal_picture(income, "single", bt, n_seniors=1, conversion_taxable=30_000.0)
    # The conversion enters provisional income, pulling more SS into taxability.
    assert bumped.taxable_ss > base.taxable_ss


def test_conversion_lifts_preferential_income_into_15pct() -> None:
    bt = reference_bracket_table(2026)
    # Sits in the 0% LTCG band before, pushed up by ordinary conversion income.
    income = IncomeExConversion(
        pension=20_000, ordinary_dividends=10_000, qualified_dividends=10_000, long_term_gains=10_000
    )
    base = federal_picture(income, "single", bt, n_seniors=0, conversion_taxable=0.0)
    bumped = federal_picture(income, "single", bt, n_seniors=0, conversion_taxable=60_000.0)
    assert base.ltcg_tax == pytest.approx(0.0)
    assert bumped.ltcg_tax > 0.0  # stacking pushed gains out of the 0% band


def test_leftover_deduction_shelters_preferential_income() -> None:
    # Low ordinary income + large preferential: the deduction left over after
    # ordinary income must shelter LTCG/QDI first (IRS QDI worksheet ordering),
    # not be dropped. MFJ, 2 seniors: ordinary income << deduction, so the
    # preferential that survives the deduction lands in the 0% LTCG band -> $0.
    bt = reference_bracket_table(2026)
    income = IncomeExConversion(
        pension=15_000,
        social_security_gross=30_000,
        ordinary_dividends=70_000,
        qualified_dividends=70_000,
        long_term_gains=30_000,
    )
    p = federal_picture(income, "married_joint", bt, n_seniors=2, conversion_taxable=0.0)
    assert p.ordinary_taxable == 0.0
    assert p.ltcg_tax == pytest.approx(0.0)  # regression: was ~$495 before the fix


def test_full_deduction_case_unchanged() -> None:
    # When ordinary income exceeds the deduction, the worksheet ordering is the
    # same as the simple "remove preferential then deduct" path — guard against a
    # regression in the common case.
    bt = reference_bracket_table(2026)
    income = IncomeExConversion(
        pension=120_000, ordinary_dividends=10_000, qualified_dividends=10_000, long_term_gains=30_000
    )
    p = federal_picture(income, "single", bt, n_seniors=0, conversion_taxable=0.0)
    # ordinary taxable = 120000 - 15000 std = 105000; 40k preferential stacks on
    # top, all above the single 15% breakpoint (48,350) -> 15%.
    assert p.ordinary_taxable == pytest.approx(105_000.0)
    assert p.ltcg_tax == pytest.approx(40_000 * 0.15)


def test_niit_only_applies_above_threshold() -> None:
    bt = reference_bracket_table(2026)
    income = IncomeExConversion(taxable_interest=20_000, ordinary_dividends=20_000, pension=100_000)
    low = federal_picture(income, "single", bt, n_seniors=0, conversion_taxable=0.0)
    high = federal_picture(income, "single", bt, n_seniors=0, conversion_taxable=120_000.0)
    # MAGI below 200k single -> no NIIT; conversion lifts MAGI over it -> NIIT applies.
    assert low.niit == pytest.approx(0.0)
    assert high.niit > 0.0
