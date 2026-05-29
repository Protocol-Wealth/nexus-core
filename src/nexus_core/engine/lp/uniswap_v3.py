# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Pure Uniswap V3 concentrated-liquidity math for LP position analytics.

No I/O — every function is a deterministic computation over numbers the data
layer supplies (subgraph position/pool state + RPC ``tokensOwed`` + USD prices).
Reimplemented clean-room from the public Uniswap V3 math (Atis Elsts'
liquidity-math note + ``SqrtPriceMath`` getAmount0/1Delta) and revert.finance's
position-analytics methodology; verified against ported numeric test vectors.

Conventions:

- On-chain integers (``liquidity``, ``sqrtPriceX96``, ``feeGrowth*X128``) stay
  Python ``int`` through the arithmetic; float scaling happens only at the final
  human-readable step (Python ``int`` is arbitrary-precision, so this loses no
  precision until the deliberate ``/ 10**decimals``).
- ``amount0``/``amount1`` are token0/token1 in human units.
- Impermanent loss is **exact** (amount reconstruction vs a HODL of the deposited
  amounts repriced at current USD), not the capped full-range heuristic.
- ``fee_apr`` is a pool-average **estimate** (volume × fee ÷ TVL, annualised),
  not a position's realised APR — labelled as such wherever surfaced.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

Q96 = 2**96
Q128 = 2**128
Q256 = 2**256
MIN_TICK = -887272
MAX_TICK = 887272


# ── tick / price primitives ──────────────────────────────────────────────


def tick_to_price(tick: int) -> float:
    """Price of token0 in token1 at ``tick`` (1.0001**tick), decimals-unadjusted."""
    return math.pow(1.0001, tick)


def tick_to_sqrt_price_x96(tick: int) -> int:
    """Convert a tick to its sqrtPriceX96 (Q64.96 fixed point)."""
    return int(math.sqrt(1.0001**tick) * Q96)


def sqrt_price_x96_to_price(sqrt_price_x96: int, decimals0: int, decimals1: int) -> float:
    """Human-readable price of token0 in token1 from sqrtPriceX96.

    ``price = (sqrtPriceX96 / 2**96)**2`` scaled by the token decimal delta.
    """
    ratio = sqrt_price_x96 / Q96
    price = ratio * ratio  # float * float (avoids `** 2` typing as Any)
    # 10**decimals types as Any (int power can be negative→float); float() pins it.
    return float(price * (10**decimals0) / (10**decimals1))


def get_amounts_for_liquidity(
    sqrt_price_x96: int,
    tick_lower: int,
    tick_upper: int,
    liquidity: int,
    decimals0: int = 18,
    decimals1: int = 18,
) -> tuple[float, float]:
    """Token amounts a position holds at the current price (human units).

    Piecewise on where the current price sits relative to the range:
    below → all token0, above → all token1, in-range → both. This is the
    canonical Uniswap V3 ``getAmount0Delta`` / ``getAmount1Delta`` evaluated
    against the current sqrt price.
    """
    if liquidity == 0:
        return 0.0, 0.0

    sqrt_price = sqrt_price_x96 / Q96
    sqrt_lower = math.sqrt(1.0001**tick_lower)
    sqrt_upper = math.sqrt(1.0001**tick_upper)

    if sqrt_price <= sqrt_lower:
        amount0 = liquidity * (1 / sqrt_lower - 1 / sqrt_upper)
        amount1 = 0.0
    elif sqrt_price >= sqrt_upper:
        amount0 = 0.0
        amount1 = liquidity * (sqrt_upper - sqrt_lower)
    else:
        amount0 = liquidity * (1 / sqrt_price - 1 / sqrt_upper)
        amount1 = liquidity * (sqrt_price - sqrt_lower)

    return amount0 / (10**decimals0), amount1 / (10**decimals1)


def is_in_range(current_tick: int, tick_lower: int, tick_upper: int) -> bool:
    """Whether the pool's current tick is inside the position range.

    Integer-tick comparison (the canonical in-range test) — used for the
    in-range flag and fee accrual, consistent with on-chain semantics.
    """
    return tick_lower <= current_tick < tick_upper


# ── fees ─────────────────────────────────────────────────────────────────


def estimate_fee_apr(
    pool_volume_24h_usd: float,
    pool_tvl_usd: float,
    fee_tier: int,
    position_liquidity: int,
    pool_liquidity: int,
    in_range: bool,
) -> float:
    """Annualised fee-APR **estimate** (percent) for a position.

    ``daily_fees = volume × fee_rate``; the position earns its liquidity-share
    while in range; annualised over its TVL-share. This is a pool-average
    approximation (active-tick liquidity ≠ total pool liquidity), not a realised
    APR. Returns 0 when out of range or inputs are degenerate.
    """
    if not in_range or pool_tvl_usd <= 0 or pool_liquidity <= 0:
        return 0.0

    fee_rate = fee_tier / 1_000_000  # hundredths-of-a-bip → decimal (3000 → 0.003)
    daily_pool_fees = pool_volume_24h_usd * fee_rate
    liquidity_share = position_liquidity / pool_liquidity
    daily_position_fees = daily_pool_fees * liquidity_share
    position_value = pool_tvl_usd * liquidity_share
    if position_value <= 0:
        return 0.0
    return (daily_position_fees * 365 / position_value) * 100


def uncollected_fees_from_growth(
    fee_growth_inside0_x128: int,
    fee_growth_inside1_x128: int,
    fee_growth_inside0_last_x128: int,
    fee_growth_inside1_last_x128: int,
    liquidity: int,
    decimals0: int = 18,
    decimals1: int = 18,
) -> tuple[float, float]:
    """Uncollected fees from feeGrowthInside deltas (human units).

    The precise on-chain formula: ``fees = liquidity × ΔfeeGrowthInside / 2**128``.
    Deltas use modular ``2**256`` arithmetic because feeGrowth is a wrapping
    uint256 accumulator. (v1 reads ``tokensOwed`` via RPC instead; this is kept
    for the precise path and is exercised by the test vectors.)
    """
    delta0 = (fee_growth_inside0_x128 - fee_growth_inside0_last_x128) % Q256
    delta1 = (fee_growth_inside1_x128 - fee_growth_inside1_last_x128) % Q256
    fees0 = (liquidity * delta0) / Q128 / (10**decimals0)
    fees1 = (liquidity * delta1) / Q128 / (10**decimals1)
    return fees0, fees1


# ── impermanent loss (exact, vs HODL of deposited amounts) ─────────────────


def impermanent_loss_vs_hodl(
    deposited0: float,
    deposited1: float,
    current_amount0: float,
    current_amount1: float,
    price0_usd: float,
    price1_usd: float,
) -> tuple[float, float]:
    """Exact impermanent loss vs holding the deposited amounts.

    ``hodl = deposited0·p0 + deposited1·p1`` (the originally deposited token
    quantities valued at *current* USD prices); ``lp = amount0·p0 + amount1·p1``
    (the position's current underlying amounts at current prices). IL excludes
    fees and rewards.

    Returns ``(il_usd, il_pct)`` where negative means the LP underperformed
    HODL. ``il_pct`` is 0 when the HODL baseline is non-positive (no usable
    deposit baseline).
    """
    hodl_value = deposited0 * price0_usd + deposited1 * price1_usd
    lp_value = current_amount0 * price0_usd + current_amount1 * price1_usd
    il_usd = lp_value - hodl_value
    il_pct = (il_usd / hodl_value * 100) if hodl_value > 0 else 0.0
    return il_usd, il_pct


# ── position analytics ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class PositionAnalytics:
    """Computed analytics for a single Uniswap V3 position (all human units)."""

    token_id: str
    chain: str
    pool: str
    token0_symbol: str
    token1_symbol: str
    fee_tier: int

    in_range: bool
    current_tick: int
    tick_lower: int
    tick_upper: int
    liquidity: str

    amount0: float
    amount1: float
    position_value_usd: float

    uncollected_fees0: float
    uncollected_fees1: float
    uncollected_fees_usd: float

    fee_apr_estimate: float  # percent, pool-average estimate
    reward_apr: float  # percent, from Merkl incentives (0 if none)
    total_apr_estimate: float  # fee_apr_estimate + reward_apr

    impermanent_loss_usd: float | None  # None when no usable deposit baseline
    impermanent_loss_pct: float | None

    range_width_pct: float
    current_price: float
    price_token0_usd: float
    price_token1_usd: float


def analyze_uniswap_v3_position(
    *,
    token_id: str,
    chain: str,
    pool: str,
    token0_symbol: str,
    token1_symbol: str,
    decimals0: int,
    decimals1: int,
    fee_tier: int,
    liquidity: int,
    tick_lower: int,
    tick_upper: int,
    current_tick: int,
    sqrt_price_x96: int,
    deposited0: float,
    deposited1: float,
    pool_liquidity: int,
    pool_tvl_usd: float,
    pool_avg_daily_volume_usd: float,
    price_token0_usd: float,
    price_token1_usd: float,
    uncollected0: float,
    uncollected1: float,
    reward_apr: float = 0.0,
) -> PositionAnalytics:
    """Compose the primitives into a full :class:`PositionAnalytics` (pure).

    The data layer supplies subgraph state (position + pool), RPC ``tokensOwed``
    (``uncollected0/1``), USD prices, and an optional Merkl ``reward_apr``.
    """
    in_range = is_in_range(current_tick, tick_lower, tick_upper)
    amount0, amount1 = get_amounts_for_liquidity(
        sqrt_price_x96, tick_lower, tick_upper, liquidity, decimals0, decimals1
    )
    position_value_usd = amount0 * price_token0_usd + amount1 * price_token1_usd
    uncollected_fees_usd = uncollected0 * price_token0_usd + uncollected1 * price_token1_usd

    fee_apr = estimate_fee_apr(
        pool_avg_daily_volume_usd, pool_tvl_usd, fee_tier, liquidity, pool_liquidity, in_range
    )

    # IL only when both deposit legs are present (a usable HODL baseline).
    if deposited0 > 0 or deposited1 > 0:
        il_usd, il_pct = impermanent_loss_vs_hodl(
            deposited0, deposited1, amount0, amount1, price_token0_usd, price_token1_usd
        )
        il_usd_opt: float | None = il_usd
        il_pct_opt: float | None = il_pct
    else:
        il_usd_opt = il_pct_opt = None

    price_lower = tick_to_price(tick_lower)
    price_upper = tick_to_price(tick_upper)
    range_width_pct = ((price_upper - price_lower) / price_lower * 100) if price_lower > 0 else 0.0

    return PositionAnalytics(
        token_id=token_id,
        chain=chain,
        pool=pool,
        token0_symbol=token0_symbol,
        token1_symbol=token1_symbol,
        fee_tier=fee_tier,
        in_range=in_range,
        current_tick=current_tick,
        tick_lower=tick_lower,
        tick_upper=tick_upper,
        liquidity=str(liquidity),
        amount0=amount0,
        amount1=amount1,
        position_value_usd=position_value_usd,
        uncollected_fees0=uncollected0,
        uncollected_fees1=uncollected1,
        uncollected_fees_usd=uncollected_fees_usd,
        fee_apr_estimate=fee_apr,
        reward_apr=reward_apr,
        total_apr_estimate=fee_apr + reward_apr,
        impermanent_loss_usd=il_usd_opt,
        impermanent_loss_pct=il_pct_opt,
        range_width_pct=range_width_pct,
        current_price=sqrt_price_x96_to_price(sqrt_price_x96, decimals0, decimals1),
        price_token0_usd=price_token0_usd,
        price_token1_usd=price_token1_usd,
    )


__all__ = [
    "MAX_TICK",
    "MIN_TICK",
    "PositionAnalytics",
    "Q128",
    "Q96",
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
