# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Required Minimum Distribution (RMD) calculator (educational).

A traditional (pre-tax) account holder must take an annual RMD starting at the
SECURE/SECURE 2.0 applicable age. The amount is the prior-year-end balance
divided by the IRS Uniform Lifetime Table distribution period for the account
owner's age. This calculator reuses the engine's published factor table
(``tax.rmd_factor``) and start-age policy (``tax.rmd_start_age``).

Money paths use ``decimal.Decimal`` so the balance / factor division is exact
to the published table value, then quantized to cents (RMD amount) and four
decimal places (effective rate) with ``ROUND_HALF_EVEN``. The public result
still returns those amounts as ``float`` so the existing planning wire is
unchanged. Distribution periods continue to come from ``tax.rmd_factor``.

Documented simplifications (planning illustration, not tax advice): the IRS
Uniform Lifetime Table only (the Joint Life table for a >10-years-younger spouse
beneficiary is out of scope); no aggregation rules across multiple accounts; no
QCD or still-working exceptions. Pure + deterministic; no I/O.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from .tax import RMD_START_AGE_POLICY_VERSION, rmd_factor, rmd_start_age

_CENTS = Decimal("0.01")
_RATE_PLACES = Decimal("0.0001")


def _as_money(value: object, *, name: str) -> Decimal:
    """Parse a non-negative finite money amount.

    ``bool`` is rejected (it is a subclass of ``int``). Floats are converted
    through ``str`` so a decimal literal such as ``500000.0`` does not pick up
    a binary-float encoding of a different value.
    """
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{name} must be non-negative")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} must be non-negative")
        amount = Decimal(str(value))
    else:
        raise ValueError(f"{name} must be non-negative")
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{name} must be non-negative")
    return amount


def _quantize(value: Decimal, quantum: Decimal) -> float:
    return float(value.quantize(quantum, rounding=ROUND_HALF_EVEN))


def rmd(*, age: int, balance: float | Decimal, birth_year: int | None = None) -> dict[str, Any]:
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
    balance_dec = _as_money(balance, name="balance")

    start_age = rmd_start_age(birth_year)
    applies = age >= start_age
    period = rmd_factor(age)
    period_dec = Decimal(str(period))
    amount = (balance_dec / period_dec) if applies else Decimal("0")
    effective_rate = (amount / balance_dec) if balance_dec > 0 else Decimal("0")

    return {
        "rmdStartAge": start_age,
        "rmdStartAgePolicyVersion": RMD_START_AGE_POLICY_VERSION,
        "applies": applies,
        "distributionPeriod": period,
        "rmdAmount": _quantize(amount, _CENTS),
        "effectiveRate": _quantize(effective_rate, _RATE_PLACES),
    }


__all__ = ["rmd"]
