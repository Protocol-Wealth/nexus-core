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

from fastapi import APIRouter, HTTPException, Path, Response
from pydantic import BaseModel, ConfigDict

from ..data.onchain import TatumClient
from ..disclaimers import TERSE

_BALANCE_TTL = 300
_METHODOLOGY = "Anonymous public on-chain data."
_DISCLAIMER = f"{TERSE} {_METHODOLOGY}"


class ChainInfo(BaseModel):
    """Public metadata for one supported chain."""

    model_config = ConfigDict(extra="forbid")

    chain: str
    family: str
    symbol: str


class ChainList(BaseModel):
    """Response body for ``GET /api/chain/chains``."""

    model_config = ConfigDict(extra="forbid")

    chains: list[ChainInfo]
    disclaimer: str


class NativeBalanceRow(BaseModel):
    """One chain's native-coin balance. Mirrors the ``NativeBalance`` dataclass.

    ``raw`` is an ``int`` on purpose. It is the balance in the smallest unit —
    wei or lamports — so a typical value is 18 digits. Declaring it ``float``
    would serialize 1500000000000000000 as 1.5e+18 and silently change the wire
    format for every balance on the surface.
    """

    model_config = ConfigDict(extra="forbid")

    chain: str
    symbol: str
    address: str
    balance: float
    raw: int


class NativeBalanceResponse(NativeBalanceRow):
    """Single-chain balance plus the disclaimer, in that order."""

    disclaimer: str


class NativeSweepResponse(BaseModel):
    """Response body for ``GET /api/chain/native/{address}``.

    ``balances`` is keyed by chain name, so it stays a free-form mapping.
    """

    model_config = ConfigDict(extra="forbid")

    address: str
    balances: dict[str, NativeBalanceRow]
    chain_count: int
    disclaimer: str


def build_chain_router(*, tatum: TatumClient) -> APIRouter:
    """Build the anonymous native-balance router around a Tatum client."""
    router = APIRouter(prefix="/api/chain", tags=["chain"])

    @router.get(
        "/chains",
        summary="Supported chains for native-balance lookups",
        response_model=ChainList,
    )
    def chains() -> ChainList:
        """List the chains this surface can resolve a native balance for."""
        infos = [TatumClient.chain_info(c) for c in TatumClient.supported_chains()]
        return ChainList(
            # chain_info is Optional in signature but never None for a key that
            # supported_chains() itself produced; the filter keeps mypy honest
            # without inventing a runtime branch that cannot be reached.
            chains=[ChainInfo(**info) for info in infos if info is not None],
            disclaimer=_DISCLAIMER,
        )

    @router.get(
        "/balance/{chain}/{address}",
        summary="Anonymous native-coin balance",
        response_model=NativeBalanceResponse,
    )
    def balance(
        response: Response,
        chain: str = Path(description="Chain key, e.g. ethereum, base, solana"),
        address: str = Path(description="Public address (EVM 0x… or Solana base58)"),
    ) -> NativeBalanceResponse:
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
        return NativeBalanceResponse(**asdict(result), disclaimer=_DISCLAIMER)

    @router.get(
        "/native/{address}",
        summary="EVM native balances across chains",
        response_model=NativeSweepResponse,
    )
    def native_sweep(
        response: Response,
        address: str = Path(description="Public EVM address, 0x… (40 hex chars)"),
    ) -> NativeSweepResponse:
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
        return NativeSweepResponse(
            address=address,
            balances={chain: NativeBalanceRow(**asdict(bal)) for chain, bal in balances.items()},
            chain_count=len(balances),
            disclaimer=_DISCLAIMER,
        )

    return router


__all__ = [
    "ChainInfo",
    "ChainList",
    "NativeBalanceResponse",
    "NativeBalanceRow",
    "NativeSweepResponse",
    "build_chain_router",
]
