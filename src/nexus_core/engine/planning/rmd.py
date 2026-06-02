# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Required Minimum Distribution (RMD) calculator (educational).

A traditional (pre-tax) account holder must take an annual RMD starting at the
SECURE 2.0 age (73). The amount is the prior-year-end balance divided by the IRS
Uniform Lifetime Table distribution period for the account owner's age. This
calculator reuses the engine's published factor table (``tax.rmd_factor``).

Documented simplifications (planning illustration, not tax advice): the IRS
Uniform Lifetime Table only (the Joint Life table for a >10-years-younger spouse
beneficiary is out of scope); no aggregation rules across multiple accounts; no
QCD or still-working exceptions. Pure + deterministic; no I/O.
"""

from __future__ import annotations

from typing import Any

from .tax import RMD_START_AGE, rmd_factor


def rmd(*, age: int, balance: float) -> dict[str, Any]:
    """Required minimum distribution for an owner of ``age`` with ``balance``.

    Args:
        age: The owner's age at year end (the year the RMD is for).
        balance: The prior-year-end traditional account balance (>= 0).

    Returns:
        ``rmdStartAge``, whether an RMD ``applies`` this year, the IRS
        ``distributionPeriod`` factor, the ``rmdAmount`` (0 before the start
        age), and the implied ``effectiveRate`` (rmdAmount / balance).

    Raises:
        ValueError: On a negative age or balance.
    """
    if age < 0:
        raise ValueError("age must be non-negative")
    if balance < 0.0:
        raise ValueError("balance must be non-negative")

    applies = age >= RMD_START_AGE
    period = rmd_factor(age)
    amount = balance / period if applies else 0.0
    effective_rate = amount / balance if balance > 0 else 0.0

    return {
        "rmdStartAge": RMD_START_AGE,
        "applies": applies,
        "distributionPeriod": period,
        "rmdAmount": round(amount, 2),
        "effectiveRate": round(effective_rate, 4),
    }


__all__ = ["rmd"]
