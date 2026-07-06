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
- :mod:`collar_select` — batch equity collar screening: per-position strike
  selection (put % below spot; call by target delta with a minimum-OTM floor)
  on an approximate strike-increment grid, dividend-aware THEORETICAL
  Black-Scholes premiums, and a ranked ``screen_collars`` helper.
  ``CollarScreenPosition``, ``CollarScreenResult``, ``evaluate_collar_position``,
  ``screen_collars``.

Everything here is an **educational illustration** over public market parameters
— not investment advice, a recommendation, or a suitability determination.

For richer fixed-income / exotic pricing, ``pip install nexus-core[pricing]``
adds QuantLib + FinancePy; the vanilla-option math here needs neither.
"""

from .black_scholes import Greeks, OptionKind, bs_price, greeks, implied_vol
from .collar_select import (
    CollarScreenPosition,
    CollarScreenResult,
    evaluate_collar_position,
    screen_collars,
)
from .crypto_overlays import (
    CryptoCollarIllustration,
    CryptoCoveredCallIllustration,
    CryptoProtectivePutIllustration,
    Settlement,
    crypto_collar,
    crypto_covered_call,
    crypto_protective_put,
)
from .option_chain import (
    ChainQuote,
    IvTermStructure,
    TermStructurePoint,
    iv_term_structure,
    rank_covered_calls,
    select_by_delta,
)
from .options_book import (
    BookMtm,
    BookPosition,
    ScenarioCell,
    ScenarioResult,
    book_mtm,
    scenario_stress,
)
from .overlays import (
    CashSecuredPutIllustration,
    CollarIllustration,
    CoveredCallIllustration,
    cash_secured_put_overlay,
    collar_overlay,
    covered_call_overlay,
)
from .overwrite import (
    CoveredCallLadder,
    LadderLeg,
    RollAnalysis,
    covered_call_ladder,
    roll_analysis,
)
from .regime_overlay import (
    RegimeConditionedOverwrite,
    regime_adjusted_target_delta,
    regime_conditioned_overwrite,
)
from .skew import SkewPoint, VolSkew, vol_skew

__all__ = [
    "BookMtm",
    "BookPosition",
    "CashSecuredPutIllustration",
    "ChainQuote",
    "CollarIllustration",
    "CollarScreenPosition",
    "CollarScreenResult",
    "CoveredCallIllustration",
    "CoveredCallLadder",
    "CryptoCollarIllustration",
    "CryptoCoveredCallIllustration",
    "CryptoProtectivePutIllustration",
    "Greeks",
    "IvTermStructure",
    "LadderLeg",
    "OptionKind",
    "RegimeConditionedOverwrite",
    "RollAnalysis",
    "ScenarioCell",
    "ScenarioResult",
    "Settlement",
    "SkewPoint",
    "TermStructurePoint",
    "VolSkew",
    "book_mtm",
    "bs_price",
    "cash_secured_put_overlay",
    "collar_overlay",
    "covered_call_ladder",
    "covered_call_overlay",
    "crypto_collar",
    "crypto_covered_call",
    "crypto_protective_put",
    "evaluate_collar_position",
    "greeks",
    "implied_vol",
    "iv_term_structure",
    "rank_covered_calls",
    "regime_adjusted_target_delta",
    "regime_conditioned_overwrite",
    "roll_analysis",
    "scenario_stress",
    "screen_collars",
    "select_by_delta",
    "vol_skew",
]
