# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Deterministic year-by-year cash-flow + net-worth projection (educational).

The annual income / expense / savings table and the balance-sheet (net-worth)
trajectory an advisor's planning page shows: from today through a terminal age,
grow earned income by a wage COLA and spending by inflation, take federal
ordinary tax each year, save any surplus into the portfolio (it compounds at the
expected return) and fund any deficit by a portfolio withdrawal — then roll the
whole thing up into lifetime income / expense / tax totals and the year the
portfolio is exhausted, if ever.

Pure and deterministic — plain numbers in, plain data out; no simulation, no
market data, no client context. It is a single deterministic path (RightCapital's
"Cash Flow" + "Net Worth" tables), the companion to the stochastic Monte-Carlo
fan chart, not a probability. A planning illustration, not a projection of any
specific person's outcome, and not tax or investment advice.

Conventions (documented because they are load-bearing):

* **Phases.** A year is *accumulation* while ``age < retirement_age`` (earned
  income = wages, COLA-grown) and *retirement* otherwise (earned income stops;
  ``retirement_income`` — Social Security / pension — flows instead, inflation
  (COLA)-grown from today).
* **Tax.** Federal ordinary tax only, via the shared progressive brackets +
  standard deduction for ``filing_status``. All earned income, retirement income
  and portfolio withdrawals are treated as ordinary-taxable — a conservative
  simplification (real plans blend in capital-gains / Roth / partly-taxable
  Social Security); a CFP refines the tax-aware withdrawal sequence.
* **Funding a deficit.** When after-tax guaranteed income cannot cover spending,
  the portfolio withdrawal is *grossed up* for the tax on the withdrawal itself
  (a short fixed-point iteration), so the net of (income + withdrawal − tax)
  equals spending.
* **Timing.** Surplus is saved at year-end (no growth in its first year);
  withdrawals are taken at year-start (they miss that year's growth). Both
  conservative, matching the FIRE accumulator and the Monte-Carlo decumulator.
* **Net worth.** ``portfolio − liabilities``; liabilities are held at their
  current value (amortization / scheduled payoff is a CFP refinement).
"""

from __future__ import annotations

import math
from typing import Any

from .tax import FilingStatus, ordinary_tax

#: DoS / sanity bounds for the public, unauthenticated surface.
_MIN_AGE = 0
_MAX_AGE = 130
_MAX_PROJECTION_YEARS = 100

#: Iterations for the deficit-year withdrawal gross-up. The fixed-point
#: ``W = (expenses − income) + tax(income + W)`` is a contraction (the tax slope
#: is the marginal rate < 1), so a handful of steps converge to the cent.
_GROSS_UP_ITERS = 12

_FILING_STATUSES: tuple[FilingStatus, ...] = (
    "single",
    "married_joint",
    "married_separate",
    "head_of_household",
)


def _withdrawal_and_tax(
    *,
    base_ordinary: float,
    expenses: float,
    filing_status: FilingStatus,
) -> tuple[float, float]:
    """Desired portfolio withdrawal + the year's federal ordinary tax.

    ``base_ordinary`` is the year's guaranteed/earned ordinary income (wages or
    Social-Security/pension). If its after-tax value already covers ``expenses``
    the withdrawal is zero and the tax is on ``base_ordinary`` alone; otherwise
    solve for the withdrawal that — grossed up for its own tax — makes
    ``base_ordinary + withdrawal − tax == expenses``.
    """
    tax_no_draw = ordinary_tax(base_ordinary, filing_status)
    if base_ordinary - tax_no_draw >= expenses:
        return 0.0, tax_no_draw
    withdrawal = max(0.0, expenses - base_ordinary)
    for _ in range(_GROSS_UP_ITERS):
        tax = ordinary_tax(base_ordinary + withdrawal, filing_status)
        next_withdrawal = max(0.0, expenses - base_ordinary + tax)
        if abs(next_withdrawal - withdrawal) < 0.005:
            withdrawal = next_withdrawal
            break
        withdrawal = next_withdrawal
    return withdrawal, ordinary_tax(base_ordinary + withdrawal, filing_status)


def project_cash_flow(
    *,
    current_age: int,
    retirement_age: int,
    terminal_age: int,
    current_income: float,
    current_expenses: float,
    current_portfolio: float,
    filing_status: FilingStatus = "married_joint",
    income_growth_rate: float = 0.03,
    expense_inflation_rate: float = 0.025,
    expected_return: float = 0.05,
    retirement_income: float = 0.0,
    current_liabilities: float = 0.0,
    base_year: int | None = None,
) -> dict[str, Any]:
    """Year-by-year cash-flow + net-worth projection with a lifetime tax rollup.

    Args:
        current_age: Age today (the first projected year). ``[0, 130]``.
        retirement_age: Age earned income stops and retirement income begins.
            May be ``<= current_age`` (an already-retired client).
        terminal_age: Last projected age. ``> current_age``; the projection spans
            ``terminal_age - current_age + 1`` years (``<= 100``).
        current_income: Annual gross earned income today (>= 0).
        current_expenses: Annual living expenses today (>= 0).
        current_portfolio: Investable assets today — the balance that compounds
            at ``expected_return`` (include cash here) (>= 0).
        filing_status: Federal filing status for the ordinary-tax brackets.
        income_growth_rate: Annual wage COLA (> -1).
        expense_inflation_rate: Annual spending inflation; also the COLA applied
            to ``retirement_income`` (> -1).
        expected_return: Annual portfolio return (> -1).
        retirement_income: Annual Social-Security/pension in today's dollars,
            paid from ``retirement_age`` on, COLA-grown (>= 0).
        current_liabilities: Total debt today, held flat across the projection
            for the net-worth line (>= 0).
        base_year: Calendar year of ``current_age``; when given each row's
            ``year`` is the calendar year, else the 0-based index.

    Returns:
        ``years`` (per-year rows), ``aggregate`` (lifetime totals, peak/ending
        net worth, depletion age), ``lifetimeTax`` (income/taxes/effective rate),
        and ``assumptions`` (the rates + filing status echoed back).

    Raises:
        ValueError: on a malformed/out-of-range input (the gateway maps it to 400).
    """
    if not isinstance(current_age, int) or isinstance(current_age, bool):
        raise ValueError("current_age must be an integer")
    if not isinstance(retirement_age, int) or isinstance(retirement_age, bool):
        raise ValueError("retirement_age must be an integer")
    if not isinstance(terminal_age, int) or isinstance(terminal_age, bool):
        raise ValueError("terminal_age must be an integer")
    if not _MIN_AGE <= current_age <= _MAX_AGE:
        raise ValueError(f"current_age must be in [{_MIN_AGE}, {_MAX_AGE}]")
    if not _MIN_AGE <= retirement_age <= _MAX_AGE:
        raise ValueError(f"retirement_age must be in [{_MIN_AGE}, {_MAX_AGE}]")
    if terminal_age <= current_age:
        raise ValueError("terminal_age must be greater than current_age")
    if terminal_age - current_age + 1 > _MAX_PROJECTION_YEARS:
        raise ValueError(f"projection spans at most {_MAX_PROJECTION_YEARS} years")
    if filing_status not in _FILING_STATUSES:
        raise ValueError(f"filing_status must be one of {', '.join(_FILING_STATUSES)}")
    for name, amount in (
        ("current_income", current_income),
        ("current_expenses", current_expenses),
        ("current_portfolio", current_portfolio),
        ("retirement_income", retirement_income),
        ("current_liabilities", current_liabilities),
    ):
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or not math.isfinite(amount)
            or amount < 0
        ):
            raise ValueError(f"{name} must be a finite non-negative number")
    for name, rate in (
        ("income_growth_rate", income_growth_rate),
        ("expense_inflation_rate", expense_inflation_rate),
        ("expected_return", expected_return),
    ):
        if (
            isinstance(rate, bool)
            or not isinstance(rate, (int, float))
            or not math.isfinite(rate)
            or rate <= -1
        ):
            raise ValueError(f"{name} must be a finite number > -1")
    if base_year is not None and (isinstance(base_year, bool) or not isinstance(base_year, int)):
        raise ValueError("base_year must be an integer or omitted")

    num_years = terminal_age - current_age + 1
    portfolio = float(current_portfolio)
    liabilities = float(current_liabilities)

    rows: list[dict[str, Any]] = []
    lifetime_income = 0.0
    lifetime_expenses = 0.0
    lifetime_taxes = 0.0
    lifetime_savings = 0.0
    lifetime_withdrawals = 0.0
    peak_net_worth = portfolio - liabilities
    peak_net_worth_age = current_age
    depletion_age: int | None = None
    first_deficit_age: int | None = None

    for k in range(num_years):
        age = current_age + k
        retired = age >= retirement_age
        earned_income = 0.0 if retired else current_income * (1.0 + income_growth_rate) ** k
        retire_income = (
            retirement_income * (1.0 + expense_inflation_rate) ** k if retired else 0.0
        )
        base_ordinary = earned_income + retire_income
        expenses = current_expenses * (1.0 + expense_inflation_rate) ** k

        withdrawal, tax = _withdrawal_and_tax(
            base_ordinary=base_ordinary,
            expenses=expenses,
            filing_status=filing_status,
        )

        if withdrawal <= 0.0:
            # Surplus (or exactly covered): save it; it compounds from next year.
            net_cash_flow = base_ordinary - tax - expenses
            portfolio = portfolio * (1.0 + expected_return) + net_cash_flow
            lifetime_savings += net_cash_flow
        else:
            # Deficit funded from the portfolio, capped at what is actually there.
            # Past depletion the desired withdrawal cannot be taken, so the tax is
            # recomputed on the ACTUAL withdrawal — taxing money that was never
            # withdrawn would massively overstate lifetime tax + the effective rate.
            if first_deficit_age is None:
                first_deficit_age = age
            available = portfolio
            actual_withdrawal = min(withdrawal, available)
            if actual_withdrawal < withdrawal:
                if depletion_age is None:
                    depletion_age = age
                tax = ordinary_tax(base_ordinary + actual_withdrawal, filing_status)
            portfolio = (available - actual_withdrawal) * (1.0 + expected_return)
            net_cash_flow = -actual_withdrawal
            lifetime_withdrawals += actual_withdrawal

        net_worth = portfolio - liabilities
        if net_worth > peak_net_worth:
            peak_net_worth = net_worth
            peak_net_worth_age = age

        lifetime_income += base_ordinary
        lifetime_expenses += expenses
        lifetime_taxes += tax

        rows.append(
            {
                "age": age,
                "year": (base_year + k) if base_year is not None else k,
                "phase": "retirement" if retired else "accumulation",
                "earnedIncome": round(earned_income, 2),
                "retirementIncome": round(retire_income, 2),
                "income": round(base_ordinary, 2),
                "expenses": round(expenses, 2),
                "taxes": round(tax, 2),
                "netCashFlow": round(net_cash_flow, 2),
                "portfolioBalance": round(portfolio, 2),
                "liabilities": round(liabilities, 2),
                "netWorth": round(net_worth, 2),
            }
        )

    ending = rows[-1]
    aggregate = {
        "projectionYears": num_years,
        "currentAge": current_age,
        "retirementAge": retirement_age,
        "terminalAge": terminal_age,
        "startingPortfolio": round(float(current_portfolio), 2),
        "startingNetWorth": round(float(current_portfolio) - float(current_liabilities), 2),
        "endingPortfolio": ending["portfolioBalance"],
        "endingNetWorth": ending["netWorth"],
        "peakNetWorth": round(peak_net_worth, 2),
        "peakNetWorthAge": peak_net_worth_age,
        "lifetimeIncome": round(lifetime_income, 2),
        "lifetimeExpenses": round(lifetime_expenses, 2),
        "lifetimeTaxes": round(lifetime_taxes, 2),
        "lifetimeSavings": round(lifetime_savings, 2),
        "lifetimeWithdrawals": round(lifetime_withdrawals, 2),
        "depletionAge": depletion_age,
        "firstDeficitAge": first_deficit_age,
        "fundedThroughTerminal": depletion_age is None,
    }

    effective_rate = lifetime_taxes / lifetime_income if lifetime_income > 0 else 0.0
    lifetime_tax = {
        "totalIncome": round(lifetime_income, 2),
        "totalTaxesPaid": round(lifetime_taxes, 2),
        "effectiveRate": round(effective_rate, 4),
    }

    assumptions = {
        "filingStatus": filing_status,
        "incomeGrowthRate": round(income_growth_rate, 6),
        "expenseInflationRate": round(expense_inflation_rate, 6),
        "expectedReturn": round(expected_return, 6),
        "retirementIncomeGrowthRate": round(expense_inflation_rate, 6),
    }

    return {
        "years": rows,
        "aggregate": aggregate,
        "lifetimeTax": lifetime_tax,
        "assumptions": assumptions,
    }


__all__ = ["project_cash_flow"]
