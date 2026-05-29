# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Derivatives pricing + educational option-overlay analytics.

- :mod:`black_scholes` — clean-room Black-Scholes-Merton price, Greeks, and
  implied volatility for European options (pure ``scipy.stats.norm`` + ``math``;
  no heavy dependency). ``OptionKind``, ``bs_price``, ``Greeks``, ``greeks``,
  ``implied_vol``.
- :mod:`overlays` — educational illustration of three common equity/ETF option
  overlays: ``covered_call_overlay``, ``cash_secured_put_overlay``,
  ``collar_overlay``. Each returns a dataclass describing the structure's
  payoff (net premium, breakevens, max profit/loss, static / if-assigned /
  annualized returns, downside protection), using a theoretical premium from
  :mod:`black_scholes` when a market premium isn't supplied.

Everything here is an **educational illustration** over public market parameters
— not investment advice, a recommendation, or a suitability determination.

For richer fixed-income / exotic pricing, ``pip install nexus-core[pricing]``
adds QuantLib + FinancePy; the vanilla-option math here needs neither.
"""

from .black_scholes import Greeks, OptionKind, bs_price, greeks, implied_vol
from .overlays import (
    CashSecuredPutIllustration,
    CollarIllustration,
    CoveredCallIllustration,
    cash_secured_put_overlay,
    collar_overlay,
    covered_call_overlay,
)

__all__ = [
    "CashSecuredPutIllustration",
    "CollarIllustration",
    "CoveredCallIllustration",
    "Greeks",
    "OptionKind",
    "bs_price",
    "cash_secured_put_overlay",
    "collar_overlay",
    "covered_call_overlay",
    "greeks",
    "implied_vol",
]
