# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""LP position-analytics REST surface (Uniswap V3).

``GET /api/lp/uniswap-v3/{chain}/{token_id}/analytics`` resolves a Uniswap V3
position NFT to its analytics — current value, in-range, exact impermanent loss
vs HODL, fee-APR estimate, uncollected fees, and (Merkl) reward APR for a total
APR. Composes three anonymous public sources:

- The Graph (position + pool state) — ``THEGRAPH_API_KEY``
- Tatum ``eth_call`` → NonfungiblePositionManager ``tokensOwed`` (uncollected fees)
- Merkl v4 (keyless) — liquidity-incentive reward APR for the pool

**Anonymous public on-chain data** — input is a chain + NFT tokenId, output is
position math. No identity or client linkage, no auth, no stored state.

USD prices are **required** query params: the math is exact given prices, and
nexus-core has no ERC-20-address → USD path yet (auto-pricing is future work).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Response

from ..data.onchain import CHAIN_IDS, MerklClient, TatumClient, TheGraphClient
from ..engine.lp import analyze_uniswap_v3_position

_LP_TTL = 60
_DISCLAIMER = (
    "Anonymous public on-chain data — educational only, not investment advice. "
    "Impermanent loss is vs holding the deposited token amounts at current prices; "
    "fee APR is a pool-average estimate; uncollected fees are as of the position's "
    "last interaction; reward APR is from Merkl liquidity incentives."
)


def build_lp_router(
    *, thegraph: TheGraphClient, tatum: TatumClient, merkl: MerklClient
) -> APIRouter:
    """Build the LP position-analytics router around its data clients."""
    router = APIRouter(prefix="/api/lp", tags=["lp"])

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
        if chain.lower() not in TheGraphClient.supported_chains():
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported chain '{chain}'. See GET /api/lp/chains.",
            )
        if not thegraph.is_configured():
            raise HTTPException(
                status_code=503,
                detail="LP analytics unavailable: THEGRAPH_API_KEY not configured",
            )
        pos = thegraph.fetch_v3_position(chain, token_id)
        if pos is None:
            raise HTTPException(
                status_code=404, detail=f"No Uniswap V3 position '{token_id}' on '{chain}'"
            )

        # Uncollected fees via RPC tokensOwed (best-effort; 0 if RPC unavailable).
        owed = tatum.nfpm_tokens_owed(
            chain, token_id, decimals0=pos.decimals0, decimals1=pos.decimals1
        )
        uncollected0, uncollected1 = owed if owed is not None else (0.0, 0.0)

        # Reward APR via Merkl (keyless, best-effort 0 if no campaign / unreachable).
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
            price_token0_usd=price_token0_usd,
            price_token1_usd=price_token1_usd,
            uncollected0=uncollected0,
            uncollected1=uncollected1,
            reward_apr=reward_apr,
        )
        response.headers["Cache-Control"] = f"public, max-age={_LP_TTL}"
        return {
            **asdict(result),
            "uncollected_fees_source": "rpc_tokens_owed" if owed is not None else "unavailable",
            "disclaimer": _DISCLAIMER,
        }

    return router


__all__ = ["build_lp_router"]
