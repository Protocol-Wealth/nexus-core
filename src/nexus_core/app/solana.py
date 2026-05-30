# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Solana SPL token price REST surface (Jupiter-backed).

``GET /api/solana/price/{mint}`` returns a Solana token's derived USD price (+
24h change, liquidity) via Jupiter; ``GET /api/solana/prices?mints=`` batches.
Public market data — input is a token mint, output is a price. No wallet,
account, or client context; keyless (Jupiter v3). Complements CoinGecko (which
addresses by coin-id) for the long tail of SPL tokens.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Response

from ..data.onchain import JupiterClient, is_solana_mint
from ..disclaimers import TERSE

_PRICE_TTL = 60
_MAX_BATCH = 50
_METHODOLOGY = (
    "Solana token prices are Jupiter v3 derived prices (aggregated from on-chain DEX liquidity)."
)
_DISCLAIMER = f"{TERSE} {_METHODOLOGY}"


def build_solana_router(*, jupiter: JupiterClient) -> APIRouter:
    """Build the Solana token-price router around a Jupiter client."""
    router = APIRouter(prefix="/api/solana", tags=["solana"])

    @router.get("/price/{mint}", summary="Solana SPL token USD price")
    def price(
        response: Response,
        mint: Annotated[str, Path(description="Solana token mint (base58)")],
    ) -> dict[str, Any]:
        """Derived USD price for a single Solana token mint."""
        if not is_solana_mint(mint):
            raise HTTPException(status_code=400, detail="Invalid Solana mint (expected base58)")
        result = jupiter.get_price(mint)
        if result is None:
            raise HTTPException(status_code=404, detail=f"No Jupiter price for mint '{mint}'")
        response.headers["Cache-Control"] = f"public, max-age={_PRICE_TTL}"
        return {**asdict(result), "disclaimer": _DISCLAIMER}

    @router.get("/prices", summary="Batch Solana SPL token USD prices")
    def prices(
        response: Response,
        mints: Annotated[str, Query(description="Comma-separated token mints (max 50)")],
    ) -> dict[str, Any]:
        """Derived USD prices for up to 50 Solana token mints."""
        mint_list = [m.strip() for m in mints.split(",") if m.strip()]
        if not mint_list:
            raise HTTPException(status_code=400, detail="Provide at least one mint via ?mints=")
        if len(mint_list) > _MAX_BATCH:
            raise HTTPException(status_code=400, detail=f"At most {_MAX_BATCH} mints per request")
        result = jupiter.get_prices(mint_list)
        response.headers["Cache-Control"] = f"public, max-age={_PRICE_TTL}"
        return {
            "prices": {mint: asdict(p) for mint, p in result.items()},
            "count": len(result),
            "disclaimer": _DISCLAIMER,
        }

    return router


__all__ = ["build_solana_router"]
