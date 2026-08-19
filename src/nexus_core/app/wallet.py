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

from fastapi import APIRouter, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict

from ..data.onchain import DeBankClient, is_evm_address
from ..disclaimers import TERSE

_WALLET_TTL = 300
_METHODOLOGY = "Anonymous public on-chain data."
_DISCLAIMER = f"{TERSE} {_METHODOLOGY}"


class WalletTokenHolding(BaseModel):
    """One token holding in the top-holdings list."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    chain: str
    usd_value: float


class WalletSnapshot(BaseModel):
    """Response body for ``GET /api/wallet/{address}``.

    Field order matches the previous hand-built dict exactly, so the serialized
    bytes are unchanged for every input the DeBank client can produce.

    ``chains`` is a free-form mapping on purpose: the keys are chain identifiers
    supplied by the provider, so modelling them as fixed fields would silently
    drop any chain the model did not name. A typed response must not be narrower
    than the data it describes.
    """

    model_config = ConfigDict(extra="forbid")

    address: str
    total_usd_value: float
    chains: dict[str, float]
    token_count: int
    top_tokens: list[WalletTokenHolding]
    disclaimer: str


def build_wallet_router(*, debank: DeBankClient) -> APIRouter:
    """Build the anonymous wallet-balance router around a DeBank client."""
    router = APIRouter(prefix="/api/wallet", tags=["wallet"])

    @router.get(
        "/{address}",
        summary="Anonymous EVM wallet balance snapshot",
        response_model=WalletSnapshot,
    )
    def wallet(
        response: Response,
        address: str = Path(description="Public EVM address, e.g. 0x… (40 hex chars)"),
    ) -> WalletSnapshot:
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
        return WalletSnapshot(**snapshot, disclaimer=_DISCLAIMER)

    return router


__all__ = ["WalletSnapshot", "WalletTokenHolding", "build_wallet_router"]
