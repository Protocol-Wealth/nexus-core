# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Required Minimum Distribution (RMD) calculator (educational).

A traditional (pre-tax) account holder must take an annual RMD starting at the
SECURE/SECURE 2.0 applicable age. The amount is the prior-year-end balance
divided by the IRS Uniform Lifetime Table distribution period for the account
owner's age. This calculator reuses the engine's published factor table
(``tax.rmd_factor``) and start-age policy (``tax.rmd_start_age``).

Documented simplifications (planning illustration, not tax advice): the IRS
Uniform Lifetime Table only (the Joint Life table for a >10-years-younger spouse
beneficiary is out of scope); no aggregation rules across multiple accounts; no
QCD or still-working exceptions. Pure + deterministic; no I/O.
"""

from __future__ import annotations

from typing import Any

from .tax import RMD_START_AGE_POLICY_VERSION, rmd_factor, rmd_start_age


def rmd(*, age: int, balance: float, birth_year: int | None = None) -> dict[str, Any]:
    """Required minimum distribution for an owner of ``age`` with ``balance``.

    Args:
        age: The owner's age at year end (the year the RMD is for).
        balance: The prior-year-end traditional account balance (>= 0).
        birth_year: Optional birth year for SECURE 2.0 start-age policy. When
            omitted, the legacy age-only contract defaults to age 73.

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

    start_age = rmd_start_age(birth_year)
    applies = age >= start_age
    period = rmd_factor(age)
    amount = balance / period if applies else 0.0
    effective_rate = amount / balance if balance > 0 else 0.0

    return {
        "rmdStartAge": start_age,
        "rmdStartAgePolicyVersion": RMD_START_AGE_POLICY_VERSION,
        "applies": applies,
        "distributionPeriod": period,
        "rmdAmount": round(amount, 2),
        "effectiveRate": round(effective_rate, 4),
    }


__all__ = ["rmd"]
