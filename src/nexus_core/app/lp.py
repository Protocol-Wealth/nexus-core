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
position math. No identity or client linkage, no auth, no stored state.

USD prices are **required** query params: the math is exact given prices, and
nexus-core has no ERC-20-address → USD path yet (auto-pricing is future work).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Response

from ..data.market import CoinGeckoMarketData
from ..data.onchain import (
    CHAIN_IDS,
    MerklClient,
    SlipstreamClient,
    TatumClient,
    TheGraphClient,
)
from ..engine.lp import PositionAnalytics, analyze_uniswap_v3_position
from .benchmarks import fetch_benchmark_series

_LP_TTL = 60
_DISCLAIMER = (
    "Anonymous public on-chain data — educational only, not investment advice. "
    "Impermanent loss is vs holding the deposited token amounts at current prices; "
    "fee APR is a pool-average estimate; uncollected fees are as of the position's "
    "last interaction; reward APR is from Merkl liquidity incentives."
)
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

    def _guard(chain: str) -> None:
        if chain.lower() not in TheGraphClient.supported_chains():
            raise HTTPException(
                status_code=400, detail=f"Unsupported chain '{chain}'. See GET /api/lp/chains."
            )
        if not thegraph.is_configured():
            raise HTTPException(
                status_code=503, detail="LP analytics unavailable: THEGRAPH_API_KEY not configured"
            )

    @router.get("/chains", summary="Chains/versions with LP analytics")
    def chains() -> dict[str, Any]:
        """LP analytics coverage (Uniswap V3 per supported chain)."""
        return {
            "chains": [
                {"chain": c, "protocol": "uniswap", "version": "v3"}
                for c in TheGraphClient.supported_chains()
            ],
            "disclaimer": _DISCLAIMER,
        }

    @router.get(
        "/uniswap-v3/{chain}/{token_id}/analytics",
        summary="Uniswap V3 position analytics",
    )
    def analytics(
        response: Response,
        chain: Annotated[str, Path(description="Chain key, e.g. ethereum")],
        token_id: Annotated[str, Path(description="Uniswap V3 position NFT tokenId")],
        price_token0_usd: Annotated[float, Query(ge=0, description="USD price of token0")],
        price_token1_usd: Annotated[float, Query(ge=0, description="USD price of token1")],
    ) -> dict[str, Any]:
        """Value, IL-vs-HODL, fee APR, uncollected fees, and reward APR."""
        _guard(chain)
        computed = _compute(chain, token_id, price_token0_usd, price_token1_usd)
        if computed is None:
            raise HTTPException(
                status_code=404, detail=f"No Uniswap V3 position '{token_id}' on '{chain}'"
            )
        result, source = computed
        response.headers["Cache-Control"] = f"public, max-age={_LP_TTL}"
        return {**asdict(result), "uncollected_fees_source": source, "disclaimer": _DISCLAIMER}

    @router.get(
        "/uniswap-v3/{chain}/{token_id}/vs-benchmark",
        summary="Uniswap V3 position vs hold-strategy benchmarks",
    )
    def vs_benchmark(
        response: Response,
        chain: Annotated[str, Path(description="Chain key, e.g. ethereum")],
        token_id: Annotated[str, Path(description="Uniswap V3 position NFT tokenId")],
        price_token0_usd: Annotated[float, Query(ge=0, description="USD price of token0")],
        price_token1_usd: Annotated[float, Query(ge=0, description="USD price of token1")],
        days: Annotated[int, Query(ge=1, le=365, description="Benchmark lookback window")] = 90,
    ) -> dict[str, Any]:
        """The position's analytics alongside hold-strategy benchmark returns."""
        _guard(chain)
        computed = _compute(chain, token_id, price_token0_usd, price_token1_usd)
        if computed is None:
            raise HTTPException(
                status_code=404, detail=f"No Uniswap V3 position '{token_id}' on '{chain}'"
            )
        result, source = computed
        benchmark_returns = {b.name: b.total_return_pct for b in fetch_benchmark_series(coingecko, days)}
        response.headers["Cache-Control"] = f"public, max-age={_LP_TTL}"
        return {
            "position": {**asdict(result), "uncollected_fees_source": source},
            "benchmarks": {"days": days, "returns_pct": benchmark_returns},
            "comparison": {
                "position_il_pct": result.impermanent_loss_pct,
                "position_total_apr_estimate": result.total_apr_estimate,
                "benchmark_returns_pct": benchmark_returns,
                "note": _COMPARISON_NOTE,
            },
            "disclaimer": _DISCLAIMER,
        }

    @router.get(
        "/aerodrome/{token_id}/analytics",
        summary="Aerodrome Slipstream position analytics (Base, on-chain RPC)",
    )
    def aerodrome(
        response: Response,
        token_id: Annotated[str, Path(description="Aerodrome Slipstream position NFT tokenId")],
        price_token0_usd: Annotated[float, Query(ge=0, description="USD price of token0")],
        price_token1_usd: Annotated[float, Query(ge=0, description="USD price of token1")],
    ) -> dict[str, Any]:
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
        return {
            **asdict(result),
            "protocol": "aerodrome-slipstream",
            "data_mode": "onchain_rpc",
            "note": _AERODROME_NOTE,
            "disclaimer": _DISCLAIMER,
        }

    return router


__all__ = ["build_lp_router"]
