# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Pydantic models for financial statements.

These shapes mirror the canonical fields of an SEC-filed 10-K / 10-Q —
income statement, balance sheet, cash-flow statement, plus a
"statistics" envelope (market cap, shares, beta, ratios as reported).
Every numeric field is ``float | None`` because real filings frequently
omit fields; downstream code must handle missing values explicitly.

Designed to be the canonical input to the ratio / model / performance /
risk modules. ``StatementBundle`` carries a triple of statements at a
shared ``Period``, plus the firm identifier and reporting context.

Adapter: ``from_finance_toolkit(toolkit)`` reads a FinanceToolkit
``Toolkit`` instance and produces a ``StatementBundle``. See
``adapter.py``.
"""

from __future__ import annotations

from enum import Enum

try:
    from pydantic import BaseModel, ConfigDict, Field
except ImportError:  # pragma: no cover
    BaseModel = ConfigDict = Field = None  # type: ignore[assignment,misc]


class Period(str, Enum):
    """Reporting period for a statement."""

    ANNUAL = "annual"
    QUARTERLY = "quarterly"
    TTM = "ttm"  # trailing twelve months


if BaseModel is not None:

    class IncomeStatement(BaseModel):
        """Income-statement (period-tagged)."""

        model_config = ConfigDict(extra="ignore", frozen=True)

        period: Period
        period_end: str = Field(..., description="ISO-8601 period end date.")
        currency: str = Field(default="USD", description="ISO 4217.")

        # Revenue + costs
        revenue: float | None = None
        cost_of_revenue: float | None = None
        gross_profit: float | None = None
        operating_expenses: float | None = None
        sga: float | None = None
        research_and_development: float | None = None
        operating_income: float | None = None
        ebitda: float | None = None
        interest_expense: float | None = None
        income_before_tax: float | None = None
        tax_provision: float | None = None
        net_income: float | None = None

        # Per-share
        weighted_avg_shares_basic: float | None = None
        weighted_avg_shares_diluted: float | None = None
        eps_basic: float | None = None
        eps_diluted: float | None = None
        dividends_per_share: float | None = None

    class BalanceSheet(BaseModel):
        """Balance-sheet snapshot."""

        model_config = ConfigDict(extra="ignore", frozen=True)

        period: Period
        period_end: str
        currency: str = "USD"

        # Assets
        cash_and_equivalents: float | None = None
        short_term_investments: float | None = None
        receivables: float | None = None
        inventory: float | None = None
        current_assets: float | None = None
        property_plant_equipment_net: float | None = None
        goodwill: float | None = None
        intangible_assets: float | None = None
        total_assets: float | None = None

        # Liabilities
        accounts_payable: float | None = None
        short_term_debt: float | None = None
        current_liabilities: float | None = None
        long_term_debt: float | None = None
        total_liabilities: float | None = None

        # Equity
        common_stock: float | None = None
        retained_earnings: float | None = None
        treasury_stock: float | None = None
        total_equity: float | None = None

        # Composite (often computed)
        total_debt: float | None = None
        net_debt: float | None = None
        invested_capital: float | None = None
        working_capital: float | None = None

    class CashFlowStatement(BaseModel):
        """Cash-flow statement (period-tagged)."""

        model_config = ConfigDict(extra="ignore", frozen=True)

        period: Period
        period_end: str
        currency: str = "USD"

        # Operating
        net_income: float | None = None
        depreciation_amortization: float | None = None
        change_in_working_capital: float | None = None
        cfo: float | None = Field(None, description="Cash flow from operations.")

        # Investing
        capital_expenditure: float | None = None
        acquisitions: float | None = None
        cfi: float | None = Field(None, description="Cash flow from investing.")

        # Financing
        debt_issued: float | None = None
        debt_repaid: float | None = None
        dividends_paid: float | None = None
        share_repurchases: float | None = None
        cff: float | None = Field(None, description="Cash flow from financing.")

        # Composite
        free_cash_flow: float | None = None

    class StatisticsStatement(BaseModel):
        """Market + ratio statistics as reported."""

        model_config = ConfigDict(extra="ignore", frozen=True)

        period: Period
        period_end: str
        currency: str = "USD"

        market_cap: float | None = None
        enterprise_value: float | None = None
        shares_outstanding: float | None = None
        beta: float | None = None
        average_daily_volume: float | None = None
        # Common ratios as reported
        pe_ratio: float | None = None
        pb_ratio: float | None = None
        ps_ratio: float | None = None
        ev_to_ebitda: float | None = None
        dividend_yield: float | None = None

    class StatementBundle(BaseModel):
        """Canonical envelope: a triple of statements + stats at a shared period."""

        model_config = ConfigDict(extra="ignore", frozen=True)

        ticker: str
        company_name: str | None = None
        period: Period
        as_of: str = Field(..., description="ISO-8601 statement-effective date.")
        currency: str = "USD"

        income: IncomeStatement
        balance: BalanceSheet
        cashflow: CashFlowStatement
        stats: StatisticsStatement | None = None

else:  # pragma: no cover
    # Pydantic not installed — surface the absence loudly when used.
    IncomeStatement = BalanceSheet = CashFlowStatement = StatisticsStatement = StatementBundle = None  # type: ignore[misc]
