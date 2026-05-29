# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""vaults.fyi v2 client for DeFi vault discovery (APY, TVL, protocol).

Resolves a chain to a list of production-ready DeFi vaults with their current
APY, TVL, protocol, and underlying asset via the vaults.fyi v2 API. This is
**public DeFi market data** — no wallet, account, or client context.

Auth is vaults.fyi's ``x-api-key`` header; the key comes from
``VAULTSFYI_API_KEY``. Without it, :meth:`is_configured` is ``False`` and
:meth:`search_vaults` returns an empty list.

vaults.fyi charges per call and **requires a chain** per request, so callers
must pass one; the default ``min_tvl_usd`` of $1M skews results toward serious
vaults. Built by reading the shape of the private pw-api
``src/lib/strategies/vaultsfyi.ts`` reference (endpoint, params, response
normalisation) and reimplementing in nexus-core's sync house style — no code
copied, no runtime call to pw-api.

Endpoint used (vaults.fyi v2):
    * ``/v2/detailed-vaults`` — filtered vault list.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.vaults.fyi"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MIN_TVL_USD = 1_000_000
_MAX_PER_PAGE = 200

# vaults.fyi names Ethereum mainnet "mainnet"; accept "ethereum" and normalise.
_SUPPORTED_CHAINS: tuple[str, ...] = (
    "mainnet",
    "arbitrum",
    "avalanche",
    "base",
    "polygon",
    "unichain",
    "linea",
)


def chain_alias(chain: str) -> str:
    """Normalise a chain key to vaults.fyi's network identifier."""
    key = chain.strip().lower()
    return "mainnet" if key == "ethereum" else key


def is_supported_chain(chain: str) -> bool:
    """Whether ``chain`` (or its ``ethereum``→``mainnet`` alias) is supported."""
    return chain_alias(chain) in _SUPPORTED_CHAINS


def _num(value: Any) -> float | None:
    """Coerce to float, or ``None`` if absent/non-numeric (preserves 'unknown')."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Vault:
    """One DeFi vault and its current headline metrics."""

    name: str
    address: str
    chain: str
    protocol: str | None
    apy: float | None  # current APY as a fraction (vaults.fyi's apy.current)
    tvl_usd: float | None
    underlying_asset_symbol: str | None
    vault_id: str


class VaultsFyiClient:
    """DeFi vault discovery client (vaults.fyi v2).

    Args:
        api_key: vaults.fyi key. Falls back to the ``VAULTSFYI_API_KEY`` env var.
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or os.environ.get("VAULTSFYI_API_KEY") or None
        self._http_client = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        """Whether a vaults.fyi API key is available."""
        return self._api_key is not None

    @staticmethod
    def supported_chains() -> tuple[str, ...]:
        """Networks vaults.fyi exposes vault data for."""
        return _SUPPORTED_CHAINS

    def search_vaults(
        self,
        chain: str,
        *,
        min_tvl_usd: int = _DEFAULT_MIN_TVL_USD,
        per_page: int = 50,
        only_transactional: bool = True,
    ) -> list[Vault]:
        """Production-ready vaults on ``chain``, sorted by TVL desc.

        Returns an empty list for an unconfigured key, an unsupported chain, or
        any upstream failure (best-effort — never raises).
        """
        if self._api_key is None:
            return []
        network = chain_alias(chain)
        if network not in _SUPPORTED_CHAINS:
            return []
        params = {
            "allowedNetworks": network,
            "minTvl": str(max(0, min_tvl_usd)),
            "perPage": str(min(max(per_page, 1), _MAX_PER_PAGE)),
            "onlyTransactional": "true" if only_transactional else "false",
        }
        try:
            payload = fetch_json(
                f"{_BASE_URL}/v2/detailed-vaults",
                params=params,
                headers={"x-api-key": self._api_key, "Accept": "application/json"},
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("vaults.fyi fetch failed: %s", exc)
            return []

        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            return []

        vaults: list[Vault] = []
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            protocol = entry.get("protocol")
            apy = entry.get("apy")
            tvl = entry.get("tvl")
            asset = entry.get("asset")
            vaults.append(
                Vault(
                    name=entry.get("name") or "",
                    address=entry.get("address") or "",
                    chain=entry.get("network") or network,
                    protocol=protocol.get("name") if isinstance(protocol, dict) else None,
                    apy=_num(apy.get("current")) if isinstance(apy, dict) else None,
                    tvl_usd=_num(tvl.get("usd")) if isinstance(tvl, dict) else None,
                    underlying_asset_symbol=asset.get("symbol") if isinstance(asset, dict) else None,
                    vault_id=entry.get("id") or "",
                )
            )
        vaults.sort(key=lambda v: v.tvl_usd or 0.0, reverse=True)
        return vaults


__all__ = ["Vault", "VaultsFyiClient", "chain_alias", "is_supported_chain"]
