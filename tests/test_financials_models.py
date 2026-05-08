# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for nexus_core.financials.models."""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")

from nexus_core.financials.models import (  # noqa: E402
    DcfInputs,
    altman_z_score,
    capm_expected_return,
    dcf_value,
    dupont_five_step,
    dupont_three_step,
    wacc,
)
from tests.test_financials_ratios import make_bundle  # noqa: E402


def test_dcf_basic():
    inp = DcfInputs(
        free_cash_flows=[100.0, 110.0, 120.0],
        terminal_growth=0.02,
        discount_rate=0.10,
        net_debt=50.0,
        shares_outstanding=100.0,
    )
    out = dcf_value(inp)
    assert out.enterprise_value > 0
    assert out.equity_value == pytest.approx(out.enterprise_value - 50.0, rel=1e-6)
    assert out.per_share_value == pytest.approx(out.equity_value / 100.0, rel=1e-6)


def test_dcf_refuses_invalid_rates():
    bad = DcfInputs(
        free_cash_flows=[100.0],
        terminal_growth=0.10,
        discount_rate=0.10,
    )
    with pytest.raises(ValueError):
        dcf_value(bad)


def test_capm_basic():
    assert capm_expected_return(0.04, 1.2, 0.06) == pytest.approx(0.112)


def test_wacc_basic():
    # 60/40 equity/debt, ke=10%, kd=5%, tax=20%
    out = wacc(60.0, 40.0, 0.10, 0.05, 0.20)
    expected = 0.6 * 0.10 + 0.4 * 0.05 * (1 - 0.20)
    assert out == pytest.approx(expected)


def test_dupont_three_step():
    out = dupont_three_step(make_bundle())
    # NM = 0.125, AT = 1.0, EM = 2.0  → ROE = 0.25
    assert out.net_margin == pytest.approx(0.125)
    assert out.asset_turnover == pytest.approx(1.0)
    assert out.equity_multiplier == pytest.approx(2.0)
    assert out.roe == pytest.approx(0.25)


def test_dupont_five_step():
    out = dupont_five_step(make_bundle())
    # tax_burden = 50/72 ≈ 0.694
    assert out.tax_burden == pytest.approx(50_000 / 72_000)
    # interest_burden = 72/80 = 0.9
    assert out.interest_burden == pytest.approx(0.9)
    # op_margin = 80/400 = 0.2
    assert out.operating_margin == pytest.approx(0.2)
    # asset_turnover = 1.0
    # equity_multiplier = 2.0
    # product ≈ 0.694 * 0.9 * 0.2 * 1.0 * 2.0 ≈ 0.25
    assert out.roe == pytest.approx(0.25, rel=1e-3)


def test_altman_z_safe_zone():
    out = altman_z_score(make_bundle())
    assert out.z_score is not None
    assert out.distress_zone in {"safe", "grey", "distress"}
