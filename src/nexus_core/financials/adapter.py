# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Adapter: FinanceToolkit ``Toolkit`` -> ``StatementBundle``.

The bridge layer that lets ``nexus_core.financials`` consume statements
fetched by FinanceToolkit (MIT). Lazy import — calling
``from_finance_toolkit(toolkit)`` requires the optional ``[financials]``
extra to be installed; the rest of ``nexus_core.financials`` works
without FT.

Also: ``to_scoring_context(toolkit, ticker)`` builds a partial
``ScoringContext`` (the input to ``nexus_core.engine.scoring`` 8-check
framework) from a fetched ``Toolkit`` instance, so callers can wire
the two sides together with one function call.

Attribution:
    FinanceToolkit — Copyright (c) 2025 Jeroen Bouma (MIT).
    https://github.com/JerBouma/FinanceToolkit

The adapter does not copy FT code — it reads from FT's public DataFrame
outputs and converts to our shapes.
"""

from __future__ import annotations

from typing import Any

from .statements import (
    BalanceSheet,
    CashFlowStatement,
    IncomeStatement,
    Period,
    StatementBundle,
    StatisticsStatement,
)


class FinanceToolkitNotInstalledError(RuntimeError):
    """Raised when the optional FinanceToolkit extra is missing."""


def _require_finance_toolkit() -> Any:
    try:
        from financetoolkit import Toolkit  # type: ignore[import-not-found]

        return Toolkit
    except ImportError as exc:
        raise FinanceToolkitNotInstalledError(
            "FinanceToolkit not installed. Install with: pip install nexus-core[financials]"
        ) from exc


def _safe_lookup(df: Any, key: str, ticker: str, period_idx: int = -1) -> float | None:
    """Pull a value from a FT DataFrame keyed by (ticker, key).

    FT returns wide-format DataFrames indexed by metric name with
    columns being periods. We index by metric, then take the period
    column — defaulting to the most recent (last) period.
    """
    if df is None:
        return None
    try:
        # FT often returns multi-ticker DataFrames; index by ticker first if multi-index.
        if hasattr(df, "loc"):
            row = df.loc[ticker, key] if (ticker,) in df.index else df.loc[key]
            value = row.iloc[period_idx] if hasattr(row, "iloc") else row
            return float(value) if value is not None else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None


def from_finance_toolkit(
    toolkit: Any,
    ticker: str,
    *,
    period: Period = Period.ANNUAL,
    period_idx: int = -1,
) -> StatementBundle:
    """Read FT's pre-fetched statements into a ``StatementBundle``.

    Args:
        toolkit: A ``financetoolkit.Toolkit`` instance with
            ``get_income_statement()`` / ``get_balance_sheet_statement()`` /
            ``get_cash_flow_statement()`` already called.
        ticker: Single ticker to extract.
        period: Reporting period tag for the bundle.
        period_idx: Which period column to use (-1 = most recent).
    """
    income_df = (
        toolkit.get_income_statement() if hasattr(toolkit, "get_income_statement") else None
    )
    balance_df = (
        toolkit.get_balance_sheet_statement()
        if hasattr(toolkit, "get_balance_sheet_statement")
        else None
    )
    cashflow_df = (
        toolkit.get_cash_flow_statement()
        if hasattr(toolkit, "get_cash_flow_statement")
        else None
    )

    income = IncomeStatement(
        period=period,
        period_end="",  # period end is in column index; caller can override
        revenue=_safe_lookup(income_df, "Revenue", ticker, period_idx),
        cost_of_revenue=_safe_lookup(income_df, "Cost of Goods Sold", ticker, period_idx),
        gross_profit=_safe_lookup(income_df, "Gross Profit", ticker, period_idx),
        operating_income=_safe_lookup(
            income_df, "Operating Income", ticker, period_idx
        ),
        ebitda=_safe_lookup(income_df, "EBITDA", ticker, period_idx),
        net_income=_safe_lookup(income_df, "Net Income", ticker, period_idx),
        interest_expense=_safe_lookup(
            income_df, "Interest Expense", ticker, period_idx
        ),
        income_before_tax=_safe_lookup(
            income_df, "Income Before Tax", ticker, period_idx
        ),
        tax_provision=_safe_lookup(income_df, "Income Tax Expense", ticker, period_idx),
        research_and_development=_safe_lookup(
            income_df, "Research and Development Expenses", ticker, period_idx
        ),
        sga=_safe_lookup(
            income_df, "Selling, General and Administrative Expenses", ticker, period_idx
        ),
        eps_basic=_safe_lookup(income_df, "Earnings per Share", ticker, period_idx),
        eps_diluted=_safe_lookup(income_df, "Diluted EPS", ticker, period_idx),
    )

    balance = BalanceSheet(
        period=period,
        period_end="",
        cash_and_equivalents=_safe_lookup(
            balance_df, "Cash and Cash Equivalents", ticker, period_idx
        ),
        short_term_investments=_safe_lookup(
            balance_df, "Short-Term Investments", ticker, period_idx
        ),
        receivables=_safe_lookup(balance_df, "Net Receivables", ticker, period_idx),
        inventory=_safe_lookup(balance_df, "Inventory", ticker, period_idx),
        current_assets=_safe_lookup(
            balance_df, "Total Current Assets", ticker, period_idx
        ),
        property_plant_equipment_net=_safe_lookup(
            balance_df, "Property, Plant and Equipment Net", ticker, period_idx
        ),
        goodwill=_safe_lookup(balance_df, "Goodwill", ticker, period_idx),
        intangible_assets=_safe_lookup(
            balance_df, "Intangible Assets", ticker, period_idx
        ),
        total_assets=_safe_lookup(balance_df, "Total Assets", ticker, period_idx),
        accounts_payable=_safe_lookup(
            balance_df, "Accounts Payable", ticker, period_idx
        ),
        short_term_debt=_safe_lookup(balance_df, "Short Term Debt", ticker, period_idx),
        current_liabilities=_safe_lookup(
            balance_df, "Total Current Liabilities", ticker, period_idx
        ),
        long_term_debt=_safe_lookup(balance_df, "Long Term Debt", ticker, period_idx),
        total_liabilities=_safe_lookup(
            balance_df, "Total Liabilities", ticker, period_idx
        ),
        common_stock=_safe_lookup(balance_df, "Common Stock", ticker, period_idx),
        retained_earnings=_safe_lookup(
            balance_df, "Retained Earnings", ticker, period_idx
        ),
        total_equity=_safe_lookup(balance_df, "Total Equity", ticker, period_idx),
        total_debt=_safe_lookup(balance_df, "Total Debt", ticker, period_idx),
    )

    cashflow = CashFlowStatement(
        period=period,
        period_end="",
        net_income=_safe_lookup(cashflow_df, "Net Income", ticker, period_idx),
        depreciation_amortization=_safe_lookup(
            cashflow_df, "Depreciation and Amortization", ticker, period_idx
        ),
        cfo=_safe_lookup(
            cashflow_df, "Cash Flow from Operations", ticker, period_idx
        ),
        capital_expenditure=_safe_lookup(
            cashflow_df, "Capital Expenditure", ticker, period_idx
        ),
        cfi=_safe_lookup(cashflow_df, "Cash Flow from Investing", ticker, period_idx),
        debt_issued=_safe_lookup(cashflow_df, "Debt Issued", ticker, period_idx),
        debt_repaid=_safe_lookup(cashflow_df, "Debt Repaid", ticker, period_idx),
        dividends_paid=_safe_lookup(
            cashflow_df, "Dividends Paid", ticker, period_idx
        ),
        share_repurchases=_safe_lookup(
            cashflow_df, "Stock Repurchased", ticker, period_idx
        ),
        cff=_safe_lookup(cashflow_df, "Cash Flow from Financing", ticker, period_idx),
        free_cash_flow=_safe_lookup(
            cashflow_df, "Free Cash Flow", ticker, period_idx
        ),
    )

    return StatementBundle(
        ticker=ticker,
        period=period,
        as_of="",  # caller populates if available
        income=income,
        balance=balance,
        cashflow=cashflow,
    )
