# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""DefiLlama-backed DeFi TVL client.

A keyless public client over the DefiLlama REST API (https://api.llama.fi).
Serves protocol- and chain-level Total Value Locked (TVL) and stablecoin
supply — public on-chain *market* data only. It takes no wallet address, no
account, and no client context; every input is a public protocol slug or chain
name and every output is aggregate market data.

Like every REST adapter in :mod:`nexus_core.data`, requests flow through
:func:`nexus_core.data.http.fetch_json`, so an injected ``httpx.Client`` wired
to an ``httpx.MockTransport`` makes the client hermetically testable with no
network and no credentials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.llama.fi"
_DEFAULT_TIMEOUT = 15.0


@dataclass
class DefiProtocol:
    """Aggregate TVL snapshot for one DeFi protocol."""

    name: str
    symbol: str
    tvl: float
    category: str
    chains: list[str]
    slug: str
    change_1d: float | None = None
    change_7d: float | None = None


class DefiLlamaClient:
    """DeFi TVL client backed by the keyless DefiLlama REST API.

    Args:
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._http_client = http_client
        self._timeout = timeout

    def _get(self, endpoint: str) -> Any | None:
        try:
            return fetch_json(
                f"{_BASE_URL}{endpoint}",
                headers={"Accept": "application/json"},
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("DefiLlama fetch %s failed: %s", endpoint, exc)
            return None

    @staticmethod
    def _as_float(value: Any, default: float | None = None) -> float | None:
        """Coerce a JSON value to ``float``; DefiLlama sends ``null`` TVLs."""
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def get_protocols(self, *, limit: int = 20) -> list[DefiProtocol]:
        """Return the top protocols by TVL, descending.

        Args:
            limit: Maximum number of protocols to return.
        """
        payload = self._get("/protocols")
        if not isinstance(payload, list):
            return []

        with_tvl = [
            entry
            for entry in payload
            if isinstance(entry, dict) and (self._as_float(entry.get("tvl")) or 0.0) > 0.0
        ]
        with_tvl.sort(key=lambda e: self._as_float(e.get("tvl")) or 0.0, reverse=True)

        protocols: list[DefiProtocol] = []
        for entry in with_tvl[: max(0, limit)]:
            chains = entry.get("chains")
            protocols.append(
                DefiProtocol(
                    name=entry.get("name") or "Unknown",
                    symbol=entry.get("symbol") or "",
                    tvl=self._as_float(entry.get("tvl")) or 0.0,
                    category=entry.get("category") or "Other",
                    chains=list(chains) if isinstance(chains, list) else [],
                    slug=entry.get("slug") or "",
                    change_1d=self._as_float(entry.get("change_1d")),
                    change_7d=self._as_float(entry.get("change_7d")),
                )
            )
        return protocols

    def get_protocol(self, slug: str) -> dict[str, Any] | None:
        """Return a single protocol's detail by its DefiLlama ``slug``."""
        payload = self._get(f"/protocol/{slug}")
        if not isinstance(payload, dict):
            return None
        tvl_field = payload.get("tvl")
        chains = payload.get("chains")
        return {
            "name": payload.get("name"),
            "symbol": payload.get("symbol"),
            "tvl": self._as_float(tvl_field) if not isinstance(tvl_field, list) else None,
            "chains": list(chains) if isinstance(chains, list) else [],
            "category": payload.get("category") or "Other",
            "url": payload.get("url") or "",
        }

    def get_chains(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return aggregate TVL per blockchain, descending."""
        payload = self._get("/v2/chains")
        if not isinstance(payload, list):
            return []
        chains = [
            {
                "name": entry.get("name") or "Unknown",
                "tvl": self._as_float(entry.get("tvl")) or 0.0,
                "token_symbol": entry.get("tokenSymbol") or "",
            }
            for entry in payload
            if isinstance(entry, dict) and (self._as_float(entry.get("tvl")) or 0.0) > 0.0
        ]
        chains.sort(key=lambda c: float(c["tvl"]), reverse=True)
        return chains[: max(0, limit)]


__all__ = ["DefiLlamaClient", "DefiProtocol"]
