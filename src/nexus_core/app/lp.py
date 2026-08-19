# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""LP position-analytics REST surface (Uniswap V3).

``GET /api/lp/uniswap-v3/{chain}/{token_id}/analytics`` resolves a Uniswap V3
position NFT to its analytics — current value, in-range, exact impermanent loss
vs HODL, fee-APR estimate, uncollected fees, and (Merkl) reward APR for a total
APR. ``…/vs-benchmark`` adds the hold-strategy benchmark returns over a window so
the position can be compared against simply holding ("was LPing worth it?").

Composes anonymous public sources:

- The Graph (position + pool state) — ``THEGRAPH_API_KEY``
- Tatum ``eth_call`` → NonfungiblePositionManager ``tokensOwed`` (uncollected fees)
- Merkl v4 (keyless) — liquidity-incentive reward APR for the pool
- CoinGecko (keyless) — hold-strategy benchmark returns (vs-benchmark only)

**Anonymous public on-chain data** — input is a chain + NFT tokenId, output is
position math. No identity or client linkage, no caller API key, no stored
state.

USD prices are **required** query params: the math is exact given prices, and
nexus-core has no ERC-20-address → USD path yet (auto-pricing is future work).
"""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Response
from pydantic import BaseModel, ConfigDict

from ..data.market import CoinGeckoMarketData
from ..data.onchain import (
    CHAIN_IDS,
    MerklClient,
    SlipstreamClient,
    TatumClient,
    TheGraphClient,
)
from ..disclaimers import TERSE
from ..engine.lp import (
    PositionAnalytics,
    analyze_uniswap_v3_position,
    get_amounts_for_liquidity,
    is_in_range,
)
from .benchmarks import fetch_benchmark_series

_EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

_LP_TTL = 60
_METHODOLOGY = (
    "Anonymous public on-chain data. Impermanent loss is vs holding the deposited token "
    "amounts at current prices; fee APR is a pool-average estimate; uncollected fees are "
    "as of the position's last interaction; reward APR is from Merkl liquidity incentives."
)
_DISCLAIMER = f"{TERSE} {_METHODOLOGY}"
_COMPARISON_NOTE = (
    "Impermanent loss is the position's value vs holding its OWN deposited tokens "
    "(at current prices); fee/total APR is an annualized estimated yield; benchmark "
    "returns are buy-and-hold over the last N days. These are different baselines — "
    "read them together directionally, not as a single outperformance number."
)
_AERODROME_NOTE = (
    "Aerodrome Slipstream read on-chain (Base) — position value, in-range, token "
    "amounts, and uncollected fees only. Impermanent loss (needs deposit history), "
    "fee APR (needs pool volume), and AERO gauge reward APR are NOT available in "
    "on-chain-only mode and are reported as null/zero."
)
_POSITIONS_NOTE = (
    "Open Uniswap V3 positions an address owns. Token amounts + uncollected fees are "
    "in TOKEN units (current underlying via the pool sqrtPrice + the position's range "
    "+ liquidity; fees as of the position's last interaction). USD valuation needs "
    "per-token prices — pass them to the per-position analytics route."
)


class ChainCoverage(BaseModel):
    """One chain/protocol/version combination with LP analytics."""

    model_config = ConfigDict(extra="forbid")

    chain: str
    protocol: str
    version: str


class ChainList(BaseModel):
    """Response body for ``GET /api/lp/chains``."""

    model_config = ConfigDict(extra="forbid")

    chains: list[ChainCoverage]
    disclaimer: str


class TokenRef(BaseModel):
    """One side of a pool: contract address, symbol, and ERC-20 decimals."""

    model_config = ConfigDict(extra="forbid")

    address: str
    symbol: str
    decimals: int


class UncollectedFees(BaseModel):
    """Fees earned but not yet collected, in TOKEN units, plus their provenance."""

    model_config = ConfigDict(extra="forbid")

    token0: float
    token1: float
    source: str


class OwnedPosition(BaseModel):
    """One open position from ``GET …/positions``.

    ``liquidity`` is a ``str`` on purpose — Uniswap V3 liquidity is a uint128 and
    a typical value (1e18) is far above JSON's safely-representable integer
    range, so it has always gone over the wire quoted. Declaring it ``int`` here
    would unquote it and hand every JavaScript client a silently rounded number.
    """

    model_config = ConfigDict(extra="forbid")

    token_id: str
    chain: str
    pool_address: str
    fee_tier: int
    token0: TokenRef
    token1: TokenRef
    tick_lower: int
    tick_upper: int
    current_tick: int
    in_range: bool
    liquidity: str
    amount0: float
    amount1: float
    uncollected_fees: UncollectedFees


class PositionsByOwnerResponse(BaseModel):
    """Response body for ``GET /api/lp/uniswap-v3/{chain}/positions``."""

    model_config = ConfigDict(extra="forbid")

    chain: str
    owner: str
    count: int
    positions: list[OwnedPosition]
    note: str
    disclaimer: str


class PositionAnalyticsBody(BaseModel):
    """Field-for-field mirror of the :class:`PositionAnalytics` dataclass.

    Order matters: the routes spread ``asdict(result)`` into this model, and the
    declaration order here is the key order on the wire.

    Two type choices are load-bearing. ``liquidity`` stays a ``str`` (see
    :class:`OwnedPosition`). ``impermanent_loss_usd``/``_pct`` stay nullable and
    are never excluded — the Aerodrome route reports both as ``null`` because
    on-chain-only mode has no deposit baseline, and dropping the keys would turn
    a documented "not available" into a missing field.
    """

    model_config = ConfigDict(extra="forbid")

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

    fee_apr_estimate: float
    reward_apr: float
    total_apr_estimate: float

    impermanent_loss_usd: float | None
    impermanent_loss_pct: float | None

    range_width_pct: float
    current_price: float
    price_token0_usd: float
    price_token1_usd: float


class AnalyticsResponse(PositionAnalyticsBody):
    """Position analytics plus fee provenance and the disclaimer, in that order."""

    uncollected_fees_source: str
    disclaimer: str


class BenchmarkPosition(PositionAnalyticsBody):
    """The ``position`` block of the vs-benchmark view (no nested disclaimer)."""

    uncollected_fees_source: str


class BenchmarkWindow(BaseModel):
    """Hold-strategy benchmark returns over the requested window.

    ``returns_pct`` is keyed by benchmark name ("ETH", "ETH-USDC 60/40", …), so
    it stays a free-form mapping. A fixed model would silently drop any
    composition added to ``BENCHMARK_COMPOSITIONS`` later.
    """

    model_config = ConfigDict(extra="forbid")

    days: int
    returns_pct: dict[str, float]


class BenchmarkComparison(BaseModel):
    """The position's headline numbers next to the benchmark returns."""

    model_config = ConfigDict(extra="forbid")

    position_il_pct: float | None
    position_total_apr_estimate: float
    benchmark_returns_pct: dict[str, float]
    note: str


class VsBenchmarkResponse(BaseModel):
    """Response body for ``GET …/{token_id}/vs-benchmark``."""

    model_config = ConfigDict(extra="forbid")

    position: BenchmarkPosition
    benchmarks: BenchmarkWindow
    comparison: BenchmarkComparison
    disclaimer: str


class AerodromeResponse(PositionAnalyticsBody):
    """Response body for ``GET /api/lp/aerodrome/{token_id}/analytics``."""

    protocol: str
    data_mode: str
    note: str
    disclaimer: str


def build_lp_router(
    *,
    thegraph: TheGraphClient,
    tatum: TatumClient,
    merkl: MerklClient,
    coingecko: CoinGeckoMarketData,
    slipstream: SlipstreamClient,
) -> APIRouter:
    """Build the LP position-analytics router around its data clients."""
    router = APIRouter(prefix="/api/lp", tags=["lp"])

    def _compute(
        chain: str, token_id: str, price0: float, price1: float
    ) -> tuple[PositionAnalytics, str] | None:
        """Fetch + compose a position's analytics; ``None`` if the position is absent.

        Returns ``(analytics, uncollected_fees_source)``.
        """
        pos = thegraph.fetch_v3_position(chain, token_id)
        if pos is None:
            return None
        owed = tatum.nfpm_tokens_owed(
            chain, token_id, decimals0=pos.decimals0, decimals1=pos.decimals1
        )
        uncollected0, uncollected1 = owed if owed is not None else (0.0, 0.0)
        chain_id = CHAIN_IDS.get(chain.lower(), 0)
        reward_apr = merkl.reward_apr_for_pool(chain_id, pos.pool_address) if chain_id else 0.0
        result = analyze_uniswap_v3_position(
            token_id=pos.token_id,
            chain=pos.chain,
            pool=pos.pool_address,
            token0_symbol=pos.token0_symbol,
            token1_symbol=pos.token1_symbol,
            decimals0=pos.decimals0,
            decimals1=pos.decimals1,
            fee_tier=pos.fee_tier,
            liquidity=pos.liquidity,
            tick_lower=pos.tick_lower,
            tick_upper=pos.tick_upper,
            current_tick=pos.current_tick,
            sqrt_price_x96=pos.sqrt_price_x96,
            deposited0=pos.deposited0,
            deposited1=pos.deposited1,
            pool_liquidity=pos.pool_liquidity,
            pool_tvl_usd=pos.pool_tvl_usd,
            pool_avg_daily_volume_usd=pos.pool_avg_daily_volume_usd,
            price_token0_usd=price0,
            price_token1_usd=price1,
            uncollected0=uncollected0,
            uncollected1=uncollected1,
            reward_apr=reward_apr,
        )
        return result, ("rpc_tokens_owed" if owed is not None else "unavailable")

    def _list_positions(chain: str, owner: str, limit: int) -> list[OwnedPosition]:
        """Enumerate an address's open positions → per-position on-chain state.

        Token amounts + uncollected fees in TOKEN units (no USD — that needs the
        per-token prices the analytics route takes).
        """
        rows: list[OwnedPosition] = []
        for pos in thegraph.fetch_v3_positions_by_owner(chain, owner, first=limit):
            amount0, amount1 = get_amounts_for_liquidity(
                pos.sqrt_price_x96,
                pos.tick_lower,
                pos.tick_upper,
                pos.liquidity,
                pos.decimals0,
                pos.decimals1,
            )
            owed = tatum.nfpm_tokens_owed(
                chain, pos.token_id, decimals0=pos.decimals0, decimals1=pos.decimals1
            )
            uncollected0, uncollected1 = owed if owed is not None else (0.0, 0.0)
            rows.append(
                OwnedPosition(
                    token_id=pos.token_id,
                    chain=pos.chain,
                    pool_address=pos.pool_address,
                    fee_tier=pos.fee_tier,
                    token0=TokenRef(
                        address=pos.token0_address,
                        symbol=pos.token0_symbol,
                        decimals=pos.decimals0,
                    ),
                    token1=TokenRef(
                        address=pos.token1_address,
                        symbol=pos.token1_symbol,
                        decimals=pos.decimals1,
                    ),
                    tick_lower=pos.tick_lower,
                    tick_upper=pos.tick_upper,
                    current_tick=pos.current_tick,
                    in_range=is_in_range(pos.current_tick, pos.tick_lower, pos.tick_upper),
                    liquidity=str(pos.liquidity),
                    amount0=amount0,
                    amount1=amount1,
                    uncollected_fees=UncollectedFees(
                        token0=uncollected0,
                        token1=uncollected1,
                        source="rpc_tokens_owed" if owed is not None else "unavailable",
                    ),
                )
            )
        return rows

    def _guard(chain: str) -> None:
        if chain.lower() not in TheGraphClient.supported_chains():
            raise HTTPException(
                status_code=400, detail=f"Unsupported chain '{chain}'. See GET /api/lp/chains."
            )
        if not thegraph.is_configured():
            raise HTTPException(
                status_code=503, detail="LP analytics unavailable: THEGRAPH_API_KEY not configured"
            )

    @router.get(
        "/chains",
        summary="Chains/versions with LP analytics",
        response_model=ChainList,
    )
    def chains() -> ChainList:
        """LP analytics coverage (Uniswap V3 per supported chain)."""
        return ChainList(
            chains=[
                ChainCoverage(chain=c, protocol="uniswap", version="v3")
                for c in TheGraphClient.supported_chains()
            ],
            disclaimer=_DISCLAIMER,
        )

    @router.get(
        "/uniswap-v3/{chain}/positions",
        summary="Uniswap V3 positions owned by an address",
        response_model=PositionsByOwnerResponse,
    )
    def positions_by_owner(
        response: Response,
        chain: Annotated[str, Path(description="Chain key, e.g. ethereum")],
        owner: Annotated[str, Query(description="EVM address (0x…) that owns the positions")],
        limit: Annotated[int, Query(ge=1, le=200, description="Max positions to return")] = 100,
    ) -> PositionsByOwnerResponse:
        """List the open Uniswap V3 positions an address owns.

        Per position: pool, fee tier, range, in-range, current token amounts, and
        uncollected fees (token units). Anonymous public on-chain data.
        """
        _guard(chain)
        if not _EVM_ADDRESS_RE.match(owner):
            raise HTTPException(status_code=400, detail="owner must be a 0x EVM address")
        positions = _list_positions(chain, owner, limit)
        response.headers["Cache-Control"] = f"public, max-age={_LP_TTL}"
        return PositionsByOwnerResponse(
            chain=chain.lower(),
            owner=owner.lower(),
            count=len(positions),
            positions=positions,
            note=_POSITIONS_NOTE,
            disclaimer=_DISCLAIMER,
        )

    @router.get(
        "/uniswap-v3/{chain}/{token_id}/analytics",
        summary="Uniswap V3 position analytics",
        response_model=AnalyticsResponse,
    )
    def analytics(
        response: Response,
        chain: Annotated[str, Path(description="Chain key, e.g. ethereum")],
        token_id: Annotated[str, Path(description="Uniswap V3 position NFT tokenId")],
        price_token0_usd: Annotated[float, Query(ge=0, description="USD price of token0")],
        price_token1_usd: Annotated[float, Query(ge=0, description="USD price of token1")],
    ) -> AnalyticsResponse:
        """Value, IL-vs-HODL, fee APR, uncollected fees, and reward APR."""
        _guard(chain)
        computed = _compute(chain, token_id, price_token0_usd, price_token1_usd)
        if computed is None:
            raise HTTPException(
                status_code=404, detail=f"No Uniswap V3 position '{token_id}' on '{chain}'"
            )
        result, source = computed
        response.headers["Cache-Control"] = f"public, max-age={_LP_TTL}"
        return AnalyticsResponse(
            **asdict(result), uncollected_fees_source=source, disclaimer=_DISCLAIMER
        )

    @router.get(
        "/uniswap-v3/{chain}/{token_id}/vs-benchmark",
        summary="Uniswap V3 position vs hold-strategy benchmarks",
        response_model=VsBenchmarkResponse,
    )
    def vs_benchmark(
        response: Response,
        chain: Annotated[str, Path(description="Chain key, e.g. ethereum")],
        token_id: Annotated[str, Path(description="Uniswap V3 position NFT tokenId")],
        price_token0_usd: Annotated[float, Query(ge=0, description="USD price of token0")],
        price_token1_usd: Annotated[float, Query(ge=0, description="USD price of token1")],
        days: Annotated[int, Query(ge=1, le=365, description="Benchmark lookback window")] = 90,
    ) -> VsBenchmarkResponse:
        """The position's analytics alongside hold-strategy benchmark returns."""
        _guard(chain)
        computed = _compute(chain, token_id, price_token0_usd, price_token1_usd)
        if computed is None:
            raise HTTPException(
                status_code=404, detail=f"No Uniswap V3 position '{token_id}' on '{chain}'"
            )
        result, source = computed
        benchmark_returns = {
            b.name: b.total_return_pct for b in fetch_benchmark_series(coingecko, days)
        }
        response.headers["Cache-Control"] = f"public, max-age={_LP_TTL}"
        return VsBenchmarkResponse(
            position=BenchmarkPosition(**asdict(result), uncollected_fees_source=source),
            benchmarks=BenchmarkWindow(days=days, returns_pct=benchmark_returns),
            comparison=BenchmarkComparison(
                position_il_pct=result.impermanent_loss_pct,
                position_total_apr_estimate=result.total_apr_estimate,
                benchmark_returns_pct=benchmark_returns,
                note=_COMPARISON_NOTE,
            ),
            disclaimer=_DISCLAIMER,
        )

    @router.get(
        "/aerodrome/{token_id}/analytics",
        summary="Aerodrome Slipstream position analytics (Base, on-chain RPC)",
        response_model=AerodromeResponse,
    )
    def aerodrome(
        response: Response,
        token_id: Annotated[str, Path(description="Aerodrome Slipstream position NFT tokenId")],
        price_token0_usd: Annotated[float, Query(ge=0, description="USD price of token0")],
        price_token1_usd: Annotated[float, Query(ge=0, description="USD price of token1")],
    ) -> AerodromeResponse:
        """Value, in-range, amounts, and uncollected fees for a Base Slipstream position."""
        if not slipstream.is_configured():
            raise HTTPException(
                status_code=503, detail="Aerodrome analytics unavailable: TATUM_API_KEY not configured"
            )
        fetched = slipstream.fetch_position(token_id)
        if fetched is None:
            raise HTTPException(
                status_code=404, detail=f"No Aerodrome Slipstream position '{token_id}' on base"
            )
        pos, uncollected0, uncollected1 = fetched
        result = analyze_uniswap_v3_position(
            token_id=pos.token_id,
            chain=pos.chain,
            pool=pos.pool_address,
            token0_symbol=pos.token0_symbol,
            token1_symbol=pos.token1_symbol,
            decimals0=pos.decimals0,
            decimals1=pos.decimals1,
            fee_tier=pos.fee_tier,
            liquidity=pos.liquidity,
            tick_lower=pos.tick_lower,
            tick_upper=pos.tick_upper,
            current_tick=pos.current_tick,
            sqrt_price_x96=pos.sqrt_price_x96,
            deposited0=pos.deposited0,
            deposited1=pos.deposited1,
            pool_liquidity=pos.pool_liquidity,
            pool_tvl_usd=pos.pool_tvl_usd,
            pool_avg_daily_volume_usd=pos.pool_avg_daily_volume_usd,
            price_token0_usd=price_token0_usd,
            price_token1_usd=price_token1_usd,
            uncollected0=uncollected0,
            uncollected1=uncollected1,
            reward_apr=0.0,
        )
        response.headers["Cache-Control"] = f"public, max-age={_LP_TTL}"
        return AerodromeResponse(
            **asdict(result),
            protocol="aerodrome-slipstream",
            data_mode="onchain_rpc",
            note=_AERODROME_NOTE,
            disclaimer=_DISCLAIMER,
        )

    return router


__all__ = [
    "AerodromeResponse",
    "AnalyticsResponse",
    "BenchmarkComparison",
    "BenchmarkPosition",
    "BenchmarkWindow",
    "ChainCoverage",
    "ChainList",
    "OwnedPosition",
    "PositionAnalyticsBody",
    "PositionsByOwnerResponse",
    "TokenRef",
    "UncollectedFees",
    "VsBenchmarkResponse",
    "build_lp_router",
]
