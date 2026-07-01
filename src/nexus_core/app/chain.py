# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Anonymous multi-chain native-balance REST surface (Tatum-backed).

``GET /api/chain/balance/{chain}/{address}`` resolves an arbitrary public
address to its native-coin balance on a given chain via Tatum's RPC gateways;
``GET /api/chain/native/{address}`` sweeps an EVM address across EVM chains.

This is **anonymous public on-chain data** — input is a chain + address, output
is a native balance. Nothing links an address to a person, name, or client
record; there is no account, no caller API key, and no stored identity.
Complements ``/api/wallet`` (DeBank EVM token portfolios) with native balances
across chains DeBank does not cover (incl. Solana).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Response

from ..data.onchain import TatumClient
from ..disclaimers import TERSE

_BALANCE_TTL = 300
_METHODOLOGY = "Anonymous public on-chain data."
_DISCLAIMER = f"{TERSE} {_METHODOLOGY}"


def build_chain_router(*, tatum: TatumClient) -> APIRouter:
    """Build the anonymous native-balance router around a Tatum client."""
    router = APIRouter(prefix="/api/chain", tags=["chain"])

    @router.get("/chains", summary="Supported chains for native-balance lookups")
    def chains() -> dict[str, Any]:
        """List the chains this surface can resolve a native balance for."""
        return {
            "chains": [TatumClient.chain_info(c) for c in TatumClient.supported_chains()],
            "disclaimer": _DISCLAIMER,
        }

    @router.get("/balance/{chain}/{address}", summary="Anonymous native-coin balance")
    def balance(
        response: Response,
        chain: str = Path(description="Chain key, e.g. ethereum, base, solana"),
        address: str = Path(description="Public address (EVM 0x… or Solana base58)"),
    ) -> dict[str, Any]:
        """Native-coin balance for a public address on a given chain."""
        if TatumClient.chain_info(chain) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported chain '{chain}'. See GET /api/chain/chains.",
            )
        if not tatum.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Chain balance unavailable: TATUM_API_KEY not configured",
            )
        result = tatum.native_balance(chain, address)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"No native balance for '{address}' on '{chain}' (invalid address or empty)",
            )
        response.headers["Cache-Control"] = f"public, max-age={_BALANCE_TTL}"
        return {**asdict(result), "disclaimer": _DISCLAIMER}

    @router.get("/native/{address}", summary="EVM native balances across chains")
    def native_sweep(
        response: Response,
        address: str = Path(description="Public EVM address, 0x… (40 hex chars)"),
    ) -> dict[str, Any]:
        """Native-coin balances for an EVM address across all supported EVM chains."""
        if not tatum.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Chain balance unavailable: TATUM_API_KEY not configured",
            )
        balances = tatum.multi_chain_native(address)
        if not balances:
            raise HTTPException(
                status_code=404,
                detail=f"No native balances for '{address}' (invalid EVM address or all zero)",
            )
        response.headers["Cache-Control"] = f"public, max-age={_BALANCE_TTL}"
        return {
            "address": address,
            "balances": {chain: asdict(bal) for chain, bal in balances.items()},
            "chain_count": len(balances),
            "disclaimer": _DISCLAIMER,
        }

    return router


__all__ = ["build_chain_router"]
