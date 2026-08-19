# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""DeFi vault discovery REST surface (vaults.fyi-backed).

``GET /api/vaults?chain=base`` lists production-ready DeFi vaults on a chain with
their current APY, TVL, protocol, and underlying asset. This is **public DeFi
market data** — no wallet, account, or client context.

vaults.fyi charges per call and requires a chain, so ``chain`` is mandatory and
responses are edge-cached for an hour (vault metrics move slowly). The surface is
un-activated (503) until ``VAULTSFYI_API_KEY`` is wired to the deployment.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict

from ..data.onchain import VaultsFyiClient, is_supported_chain
from ..disclaimers import TERSE

_VAULTS_TTL = 3600
_METHODOLOGY = "Public DeFi market data."
_DISCLAIMER = f"{TERSE} {_METHODOLOGY}"


class VaultRow(BaseModel):
    """One vault row. Field order and nullability mirror the ``Vault`` dataclass.

    The nullable fields are declared without defaults so they stay REQUIRED but
    may be null: ``asdict()`` always emits the key, and a model that omitted a
    null would change the wire shape for every vault missing an APY or a TVL.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    address: str
    chain: str
    protocol: str | None
    apy: float | None
    apy_breakdown: dict[str, float]
    tvl_usd: float | None
    underlying_asset_symbol: str | None
    curator: str | None
    vault_url: str | None
    vault_id: str


class VaultSearchResult(BaseModel):
    """Response body for ``GET /api/vaults``."""

    model_config = ConfigDict(extra="forbid")

    chain: str
    vault_count: int
    vaults: list[VaultRow]
    disclaimer: str


class VaultChains(BaseModel):
    """Response body for ``GET /api/vaults/chains``."""

    model_config = ConfigDict(extra="forbid")

    chains: list[str]
    disclaimer: str


def build_vaults_router(*, vaultsfyi: VaultsFyiClient) -> APIRouter:
    """Build the DeFi vault-discovery router around a vaults.fyi client."""
    router = APIRouter(prefix="/api/vaults", tags=["vaults"])

    @router.get("/chains", summary="Chains with vault data", response_model=VaultChains)
    def chains() -> VaultChains:
        """Networks this surface can list vaults for."""
        return VaultChains(chains=list(VaultsFyiClient.supported_chains()), disclaimer=_DISCLAIMER)

    @router.get("", summary="Discover DeFi vaults on a chain", response_model=VaultSearchResult)
    def search(
        response: Response,
        chain: Annotated[str, Query(description="Chain key, e.g. base, arbitrum, ethereum")],
        min_tvl: Annotated[int, Query(ge=0, description="Minimum TVL in USD")] = 1_000_000,
        per_page: Annotated[int, Query(ge=1, le=200, description="Max vaults to return")] = 50,
    ) -> VaultSearchResult:
        """Production-ready vaults on a chain, sorted by TVL desc."""
        if not is_supported_chain(chain):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported chain '{chain}'. See GET /api/vaults/chains.",
            )
        if not vaultsfyi.is_configured():
            raise HTTPException(
                status_code=503,
                detail="Vault discovery unavailable: VAULTSFYI_API_KEY not configured",
            )
        vaults = vaultsfyi.search_vaults(chain, min_tvl_usd=min_tvl, per_page=per_page)
        response.headers["Cache-Control"] = f"public, max-age={_VAULTS_TTL}"
        return VaultSearchResult(
            chain=chain.lower(),
            vault_count=len(vaults),
            vaults=[VaultRow(**asdict(v)) for v in vaults],
            disclaimer=_DISCLAIMER,
        )

    return router


__all__ = ["VaultChains", "VaultRow", "VaultSearchResult", "build_vaults_router"]
