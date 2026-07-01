# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Anonymous wallet-balance REST surface.

``GET /api/wallet/{address}`` resolves an arbitrary public EVM address to its
total USD balance + top token holdings via DeBank. This is **anonymous public
on-chain data** — the input is just an address, the output is just balances.
Nothing links an address to a person, name, or any client record; there is no
account, no caller API key, and no stored identity.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Response

from ..data.onchain import DeBankClient, is_evm_address
from ..disclaimers import TERSE

_WALLET_TTL = 300
_METHODOLOGY = "Anonymous public on-chain data."
_DISCLAIMER = f"{TERSE} {_METHODOLOGY}"


def build_wallet_router(*, debank: DeBankClient) -> APIRouter:
    """Build the anonymous wallet-balance router around a DeBank client."""
    router = APIRouter(prefix="/api/wallet", tags=["wallet"])

    @router.get("/{address}", summary="Anonymous EVM wallet balance snapshot")
    def wallet(
        response: Response,
        address: str = Path(description="Public EVM address, e.g. 0x… (40 hex chars)"),
    ) -> dict[str, Any]:
        """Total USD balance + top token holdings for a public EVM address."""
        if not is_evm_address(address):
            raise HTTPException(
                status_code=400, detail="Invalid EVM address (expected 0x + 40 hex chars)"
            )
        if not debank.is_configured():
            raise HTTPException(
                status_code=503, detail="Wallet lookup unavailable: DEBANK_API_KEY not configured"
            )
        snapshot = debank.wallet_snapshot(address)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"No on-chain balance data for '{address}'")
        response.headers["Cache-Control"] = f"public, max-age={_WALLET_TTL}"
        return {**snapshot, "disclaimer": _DISCLAIMER}

    return router


__all__ = ["build_wallet_router"]
