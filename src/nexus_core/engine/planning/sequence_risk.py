# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Sequence-of-returns stress — the deterministic complement to the Monte Carlo.

The Monte Carlo decumulation (``monte_carlo.py``) takes withdrawals at the start
of each year, so a poor *sequence* of returns early in retirement does outsized
damage — but the simulation only reports the distribution, never isolates the
ordering effect. This module isolates it: hold a fixed multiset of annual returns
constant and replay the same withdrawal schedule under different *orderings*.

Because the arithmetic mean of the returns is identical across every ordering,
any spread in the terminal balance is attributable purely to sequence-of-returns
risk. The two bracketing cases are:

- **worst-first** — the lowest returns land in the earliest (largest-balance,
  withdrawal-pressured) years: the adverse bracket.
- **best-first** — the highest returns land first: the benign bracket.

A key invariant falls straight out of the math: with **no** withdrawals the
balance is ``initial * prod(1 + r)``, which is order-independent — so the gap is
exactly zero. Sequence-of-returns risk exists only because cashflows interact
with the ordering.

Pure and deterministic — no RNG, no I/O, no market data, no client context.
Educational scenario analysis only — not investment advice, not a projection of
any specific person's outcome. The within-year mechanic (withdraw at the start,
then grow, floor at zero) matches ``monte_carlo_decumulation`` exactly.
"""

from __future__ import annotations

from typing import Any


def _simulate(
    initial_balance: float,
    net_spend_by_year: list[float],
    returns_in_order: list[float],
) -> tuple[float, int | None]:
    """Replay one ordering; return ``(terminal_balance, depleted_year_index)``.

    ``depleted_year_index`` is the 0-based index of the first year the balance
    reaches zero, or ``None`` if the plan funds the full horizon. Mirrors the
    Monte Carlo engine: withdraw at the start of the year, then apply the return,
    and floor a depleted balance at zero (it stays depleted thereafter).
    """
    balance = initial_balance
    for year, ret in enumerate(returns_in_order):
        balance = (balance - net_spend_by_year[year]) * (1.0 + ret)
        if balance <= 0.0:
            return 0.0, year
    return balance, None


def sequence_of_returns_stress(
    *,
    initial_balance: float,
    net_spend_by_year: list[float],
    annual_returns: list[float],
) -> dict[str, Any]:
    """Quantify sequence-of-returns risk by replaying one return set in 3 orders.

    Args:
        initial_balance: Starting portfolio balance (must be positive).
        net_spend_by_year: Per-year net withdrawal (spend less guaranteed income);
            0 in accumulation years. Length defines the horizon.
        annual_returns: The portfolio's annual total returns, one per year. Same
            length as ``net_spend_by_year``; each must be greater than -1 (a
            >100% annual loss on an unlevered portfolio is not modeled).

    Returns:
        A dict with ``years``, the order-invariant ``meanAnnualReturn``, the
        ``worstFirst`` / ``bestFirst`` / ``asGiven`` outcomes (each
        ``{terminalBalance, depletedYear}``), and ``sequenceRiskGap`` — the
        ``bestFirst - worstFirst`` terminal spread, i.e. the magnitude of
        sequence-of-returns risk for this return set and withdrawal schedule.

    Raises:
        ValueError: On empty input, mismatched lengths, a non-positive
            ``initial_balance``, or an annual return ``<= -1``.
    """
    years = len(annual_returns)
    if years == 0:
        raise ValueError("annual_returns must be non-empty")
    if len(net_spend_by_year) != years:
        raise ValueError(
            "net_spend_by_year and annual_returns must have the same length "
            f"({len(net_spend_by_year)} vs {years})"
        )
    if initial_balance <= 0.0:
        raise ValueError("initial_balance must be positive")
    if any(r <= -1.0 for r in annual_returns):
        raise ValueError("each annual return must be greater than -1")

    mean_return = sum(annual_returns) / years
    orderings = {
        "worstFirst": sorted(annual_returns),
        "bestFirst": sorted(annual_returns, reverse=True),
        "asGiven": list(annual_returns),
    }

    outcomes: dict[str, dict[str, Any]] = {}
    for label, order in orderings.items():
        terminal, depleted = _simulate(initial_balance, net_spend_by_year, order)
        outcomes[label] = {
            "terminalBalance": round(terminal, 2),
            "depletedYear": depleted,
        }

    return {
        "years": years,
        "meanAnnualReturn": round(mean_return, 6),
        "worstFirst": outcomes["worstFirst"],
        "bestFirst": outcomes["bestFirst"],
        "asGiven": outcomes["asGiven"],
        "sequenceRiskGap": round(
            outcomes["bestFirst"]["terminalBalance"]
            - outcomes["worstFirst"]["terminalBalance"],
            2,
        ),
    }


__all__ = ["sequence_of_returns_stress"]
