# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""LP (liquidity-provider) position analytics.

Pure concentrated-liquidity math — position value, impermanent loss, fee APR —
for Uniswap V3 and compatible AMMs. No I/O; the data layer supplies subgraph
state, RPC ``tokensOwed``, and USD prices.
"""

from .uniswap_v3 import (
    PositionAnalytics,
    analyze_uniswap_v3_position,
    estimate_fee_apr,
    get_amounts_for_liquidity,
    impermanent_loss_vs_hodl,
    is_in_range,
    sqrt_price_x96_to_price,
    tick_to_price,
    tick_to_sqrt_price_x96,
    uncollected_fees_from_growth,
)

__all__ = [
    "PositionAnalytics",
    "analyze_uniswap_v3_position",
    "estimate_fee_apr",
    "get_amounts_for_liquidity",
    "impermanent_loss_vs_hodl",
    "is_in_range",
    "sqrt_price_x96_to_price",
    "tick_to_price",
    "tick_to_sqrt_price_x96",
    "uncollected_fees_from_growth",
]
