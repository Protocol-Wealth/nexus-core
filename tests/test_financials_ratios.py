# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for nexus_core.financials.ratios."""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")

from nexus_core.financials.ratios import (  # noqa: E402
    all_ratios,
    efficiency,
    liquidity,
    profitability,
    solvency,
    valuation,
)
from nexus_core.financials.statements import (  # noqa: E402
    BalanceSheet,
    CashFlowStatement,
    IncomeStatement,
    Period,
    StatementBundle,
    StatisticsStatement,
)


def make_bundle() -> StatementBundle:
    income = IncomeStatement(
        period=Period.ANNUAL,
        period_end="2025-12-31",
        revenue=400_000.0,
        cost_of_revenue=240_000.0,
        gross_profit=160_000.0,
        operating_income=80_000.0,
        ebitda=100_000.0,
        net_income=50_000.0,
        interest_expense=8_000.0,
        income_before_tax=72_000.0,
        tax_provision=22_000.0,
    )
    balance = BalanceSheet(
        period=Period.ANNUAL,
        period_end="2025-12-31",
        cash_and_equivalents=20_000.0,
        short_term_investments=10_000.0,
        receivables=30_000.0,
        inventory=40_000.0,
        current_assets=100_000.0,
        accounts_payable=25_000.0,
        current_liabilities=50_000.0,
        total_assets=400_000.0,
        total_liabilities=200_000.0,
        long_term_debt=80_000.0,
        total_debt=100_000.0,
        total_equity=200_000.0,
        retained_earnings=80_000.0,
        invested_capital=300_000.0,
        working_capital=50_000.0,
    )
    cashflow = CashFlowStatement(
        period=Period.ANNUAL,
        period_end="2025-12-31",
        cfo=70_000.0,
        capital_expenditure=20_000.0,
        free_cash_flow=50_000.0,
    )
    stats = StatisticsStatement(
        period=Period.ANNUAL,
        period_end="2025-12-31",
        market_cap=1_000_000.0,
        enterprise_value=1_100_000.0,
        shares_outstanding=10_000.0,
        beta=1.1,
    )
    return StatementBundle(
        ticker="ACME",
        company_name="Acme Co.",
        period=Period.ANNUAL,
        as_of="2025-12-31",
        income=income,
        balance=balance,
        cashflow=cashflow,
        stats=stats,
    )


def test_liquidity_basic():
    r = liquidity(make_bundle())
    assert r.current_ratio == pytest.approx(2.0)
    # quick = (100k - 40k) / 50k
    assert r.quick_ratio == pytest.approx(1.2)
    # cash = (20k + 10k) / 50k
    assert r.cash_ratio == pytest.approx(0.6)
    assert r.working_capital == pytest.approx(50_000.0)


def test_solvency_basic():
    r = solvency(make_bundle())
    assert r.debt_to_equity == pytest.approx(0.5)
    assert r.debt_ratio == pytest.approx(0.25)
    assert r.interest_coverage == pytest.approx(10.0)


def test_profitability_basic():
    r = profitability(make_bundle())
    assert r.gross_margin == pytest.approx(0.4)
    assert r.operating_margin == pytest.approx(0.2)
    assert r.net_margin == pytest.approx(0.125)
    assert r.roe == pytest.approx(0.25)
    assert r.roa == pytest.approx(0.125)
    # ROIC = NOPAT / IC = 80k * (1 - 22/72) / 300k
    expected_roic = 80_000 * (1 - 22_000 / 72_000) / 300_000
    assert r.roic == pytest.approx(expected_roic, rel=1e-6)


def test_valuation_uses_stats_when_present():
    r = valuation(make_bundle())
    # PE = 1M / 50k = 20; PB = 1M / 200k = 5; PS = 1M / 400k = 2.5
    assert r.pe_ratio == pytest.approx(20.0)
    assert r.pb_ratio == pytest.approx(5.0)
    assert r.ps_ratio == pytest.approx(2.5)
    # EV/EBITDA = 1.1M / 100k = 11
    assert r.ev_to_ebitda == pytest.approx(11.0)


def test_efficiency_basic():
    r = efficiency(make_bundle())
    assert r.asset_turnover == pytest.approx(1.0)
    # inv_turn = 240k / 40k = 6
    assert r.inventory_turnover == pytest.approx(6.0)
    # rec_turn = 400k / 30k ≈ 13.33
    assert r.receivables_turnover == pytest.approx(400_000 / 30_000)


def test_all_ratios_returns_panel():
    panel = all_ratios(make_bundle())
    assert panel.liquidity.current_ratio == pytest.approx(2.0)
    assert panel.solvency.debt_ratio == pytest.approx(0.25)
    assert panel.profitability.gross_margin == pytest.approx(0.4)
