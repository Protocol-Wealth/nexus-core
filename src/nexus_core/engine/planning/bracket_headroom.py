# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tax-bracket headroom / "Roth-fill" calculator (educational).

How much more ordinary income (e.g. a Roth conversion) fits before it spills into
the next federal bracket — or up to a chosen target rate? Pairs with the Roth
conversion calculator: ``roomToNextBracket`` (or ``roomToTargetRate``) is the
amount you can convert while keeping the marginal cost at the current rate.

Reuses the engine's progressive bracket table (``tax.ordinary_brackets``) +
standard deduction. Documented simplification: US federal ordinary brackets only
(no NIIT / IRMAA / state / phaseouts). Pure + deterministic; no I/O.
"""

from __future__ import annotations

from typing import Any

from .tax import FilingStatus, ordinary_brackets, standard_deduction

_INF = float("inf")


def bracket_headroom(
    *,
    taxable_income: float,
    filing_status: FilingStatus,
    target_rate: float | None = None,
    brackets: list[tuple[float, float]] | None = None,
    std_deduction: float | None = None,
) -> dict[str, Any]:
    """Marginal bracket + room before the next rate (and optionally a target rate).

    Args:
        taxable_income: Gross ordinary income (the standard deduction is applied).
        filing_status: Federal filing status.
        target_rate: Optional marginal rate to "fill up to"; reports the income
            room before the marginal rate would exceed it.
        brackets: Optional ``(upper_bound, rate)`` schedule overriding the engine's
            built-in table (lets a caller inject a snapshot-able bracket table).
        std_deduction: Optional deduction overriding the built-in standard
            deduction (e.g. an itemized total or a senior-adjusted figure).

    Returns:
        ``taxableIncome`` (after the standard deduction), ``marginalRate``, the
        current bracket ``bracketFloor`` / ``bracketCeiling`` (null at the top
        bracket), ``roomToNextBracket`` (null at the top), ``nextRate`` (null at
        the top), and — when ``target_rate`` is given — ``roomToTargetRate``
        (null when the target is at/above the top rate).

    Raises:
        ValueError: On a negative income or a ``target_rate`` outside [0, 1).
    """
    if taxable_income < 0.0:
        raise ValueError("taxable_income must be non-negative")
    if target_rate is not None and not 0.0 <= target_rate < 1.0:
        raise ValueError("target_rate must be in [0, 1)")

    if brackets is None:
        brackets = ordinary_brackets(filing_status)
    deduction = standard_deduction(filing_status) if std_deduction is None else std_deduction
    taxable = max(0.0, taxable_income - deduction)

    floor = 0.0
    marginal_rate = brackets[-1][1]
    ceiling = _INF
    next_rate: float | None = None
    for i, (upper, rate) in enumerate(brackets):
        if taxable < upper:
            marginal_rate = rate
            ceiling = upper
            next_rate = brackets[i + 1][1] if i + 1 < len(brackets) else None
            break
        floor = upper

    result: dict[str, Any] = {
        "taxableIncome": round(taxable, 2),
        "marginalRate": marginal_rate,
        "bracketFloor": round(floor, 2),
        "bracketCeiling": None if ceiling == _INF else round(ceiling, 2),
        "roomToNextBracket": None if ceiling == _INF else round(ceiling - taxable, 2),
        "nextRate": next_rate,
    }

    if target_rate is not None:
        # The fill ceiling is the upper bound of the highest bracket whose rate is
        # still <= target_rate (rates rise with the bounds, so the last match wins).
        fill_ceiling = 0.0
        for upper, rate in brackets:
            if rate <= target_rate:
                fill_ceiling = upper
        result["targetRate"] = target_rate
        result["roomToTargetRate"] = (
            None if fill_ceiling == _INF else round(max(0.0, fill_ceiling - taxable), 2)
        )

    return result


__all__ = ["bracket_headroom"]
