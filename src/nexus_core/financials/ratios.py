# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Financial ratios — pure functions over StatementBundle.

Five families:

    - liquidity   (current / quick / cash / working-capital)
    - solvency    (debt-to-equity / debt-ratio / interest-coverage)
    - efficiency  (asset-turnover / DSO / DIO / DPO / cash-conversion)
    - profitability (gross / operating / net margins / ROE / ROA / ROIC)
    - valuation   (P/E / P/B / P/S / EV/EBITDA / dividend yield)

Every function returns a typed ``RatioPanel`` subclass with field-by-field
``float | None`` outputs (None when the underlying statement field is
missing). No third-party dep on the import path; FinanceToolkit
(if installed) feeds in via ``adapter.from_finance_toolkit``.

Inspired by the calculation surface of FinanceToolkit (MIT). Specific
formulas are standard textbook accounting; no FT code copied.
"""

from __future__ import annotations

from dataclasses import dataclass

from .statements import BalanceSheet, IncomeStatement, StatementBundle, StatisticsStatement


def _safe_div(num: float | None, den: float | None) -> float | None:
    """Divide, returning None on missing data or div-by-zero."""
    if num is None or den is None or den == 0:
        return None
    return num / den


@dataclass(frozen=True)
class LiquidityRatios:
    current_ratio: float | None = None
    quick_ratio: float | None = None
    cash_ratio: float | None = None
    working_capital: float | None = None


@dataclass(frozen=True)
class SolvencyRatios:
    debt_to_equity: float | None = None
    debt_ratio: float | None = None
    debt_to_capital: float | None = None
    interest_coverage: float | None = None


@dataclass(frozen=True)
class EfficiencyRatios:
    asset_turnover: float | None = None
    inventory_turnover: float | None = None
    receivables_turnover: float | None = None
    dso_days: float | None = None  # days sales outstanding
    dio_days: float | None = None  # days inventory outstanding
    dpo_days: float | None = None  # days payable outstanding
    cash_conversion_cycle: float | None = None


@dataclass(frozen=True)
class ProfitabilityRatios:
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    roe: float | None = None
    roa: float | None = None
    roic: float | None = None
    ebitda_margin: float | None = None


@dataclass(frozen=True)
class ValuationRatios:
    pe_ratio: float | None = None
    pb_ratio: float | None = None
    ps_ratio: float | None = None
    ev_to_ebitda: float | None = None
    dividend_yield: float | None = None


@dataclass(frozen=True)
class RatioPanel:
    """All five ratio families for one StatementBundle."""

    liquidity: LiquidityRatios
    solvency: SolvencyRatios
    efficiency: EfficiencyRatios
    profitability: ProfitabilityRatios
    valuation: ValuationRatios


def liquidity(bundle: StatementBundle) -> LiquidityRatios:
    bs: BalanceSheet = bundle.balance
    return LiquidityRatios(
        current_ratio=_safe_div(bs.current_assets, bs.current_liabilities),
        quick_ratio=_safe_div(
            (bs.current_assets or 0) - (bs.inventory or 0), bs.current_liabilities
        )
        if bs.current_assets is not None
        and bs.current_liabilities is not None
        and bs.inventory is not None
        else None,
        cash_ratio=_safe_div(
            (bs.cash_and_equivalents or 0) + (bs.short_term_investments or 0),
            bs.current_liabilities,
        )
        if bs.current_liabilities is not None
        else None,
        working_capital=(
            (bs.current_assets or 0) - (bs.current_liabilities or 0)
            if bs.current_assets is not None and bs.current_liabilities is not None
            else None
        ),
    )


def solvency(bundle: StatementBundle) -> SolvencyRatios:
    bs: BalanceSheet = bundle.balance
    inc: IncomeStatement = bundle.income
    return SolvencyRatios(
        debt_to_equity=_safe_div(bs.total_debt, bs.total_equity),
        debt_ratio=_safe_div(bs.total_debt, bs.total_assets),
        debt_to_capital=_safe_div(
            bs.total_debt, (bs.total_debt or 0) + (bs.total_equity or 0)
        )
        if bs.total_debt is not None and bs.total_equity is not None
        else None,
        interest_coverage=_safe_div(inc.operating_income, inc.interest_expense),
    )


def efficiency(bundle: StatementBundle) -> EfficiencyRatios:
    inc: IncomeStatement = bundle.income
    bs: BalanceSheet = bundle.balance
    asset_turn = _safe_div(inc.revenue, bs.total_assets)
    inv_turn = _safe_div(inc.cost_of_revenue, bs.inventory)
    rec_turn = _safe_div(inc.revenue, bs.receivables)
    dso = _safe_div(365, rec_turn) if rec_turn else None
    dio = _safe_div(365, inv_turn) if inv_turn else None
    dpo = _safe_div(365, _safe_div(inc.cost_of_revenue, bs.accounts_payable)) if (
        inc.cost_of_revenue and bs.accounts_payable
    ) else None
    ccc = (
        (dio or 0) + (dso or 0) - (dpo or 0)
        if dio is not None and dso is not None and dpo is not None
        else None
    )
    return EfficiencyRatios(
        asset_turnover=asset_turn,
        inventory_turnover=inv_turn,
        receivables_turnover=rec_turn,
        dso_days=dso,
        dio_days=dio,
        dpo_days=dpo,
        cash_conversion_cycle=ccc,
    )


def profitability(bundle: StatementBundle) -> ProfitabilityRatios:
    inc: IncomeStatement = bundle.income
    bs: BalanceSheet = bundle.balance
    return ProfitabilityRatios(
        gross_margin=_safe_div(inc.gross_profit, inc.revenue),
        operating_margin=_safe_div(inc.operating_income, inc.revenue),
        net_margin=_safe_div(inc.net_income, inc.revenue),
        roe=_safe_div(inc.net_income, bs.total_equity),
        roa=_safe_div(inc.net_income, bs.total_assets),
        roic=_safe_div(
            (inc.operating_income or 0) * (1 - (
                _safe_div(inc.tax_provision, inc.income_before_tax) or 0
            )),
            bs.invested_capital,
        )
        if inc.operating_income is not None and bs.invested_capital is not None
        else None,
        ebitda_margin=_safe_div(inc.ebitda, inc.revenue),
    )


def valuation(bundle: StatementBundle) -> ValuationRatios:
    stats: StatisticsStatement | None = bundle.stats
    if stats is None:
        return ValuationRatios()
    inc: IncomeStatement = bundle.income
    bs: BalanceSheet = bundle.balance
    return ValuationRatios(
        pe_ratio=stats.pe_ratio
        or _safe_div(stats.market_cap, inc.net_income),
        pb_ratio=stats.pb_ratio or _safe_div(stats.market_cap, bs.total_equity),
        ps_ratio=stats.ps_ratio or _safe_div(stats.market_cap, inc.revenue),
        ev_to_ebitda=stats.ev_to_ebitda
        or _safe_div(stats.enterprise_value, inc.ebitda),
        dividend_yield=stats.dividend_yield,
    )


def all_ratios(bundle: StatementBundle) -> RatioPanel:
    """Compute every ratio family for ``bundle``."""
    return RatioPanel(
        liquidity=liquidity(bundle),
        solvency=solvency(bundle),
        efficiency=efficiency(bundle),
        profitability=profitability(bundle),
        valuation=valuation(bundle),
    )
