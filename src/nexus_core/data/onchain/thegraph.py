# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""The Graph gateway client for Uniswap V3 LP position data.

Queries The Graph's decentralized-network gateway
(``https://gateway.thegraph.com/api/{key}/subgraphs/id/{id}``) for a Uniswap V3
position + its pool state — the inputs the pure ``engine.lp`` math needs
(liquidity, ticks, deposited amounts, pool sqrtPrice/tick/feeTier/TVL/volume).

This is **anonymous public on-chain data** — input is a chain + NFT tokenId,
output is position/pool state. No identity or client linkage. Requires
``THEGRAPH_API_KEY`` (free tier ~100K queries/mo, then metered — cache upstream).

Built referencing the pw-onchain subgraph queries (no copy); the gateway is
plain POST GraphQL with the key in the URL path and a ``User-Agent`` header
(the gateway rejects an absent/default agent).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

_GATEWAY = "https://gateway.thegraph.com/api/{key}/subgraphs/id/{subgraph_id}"
_TIMEOUT = 20.0
_USER_AGENT = "nexus-core/0.1 (+https://nexusmcp.site)"

# Uniswap V3 subgraphs by chain. Mainnet (official, code at Uniswap/v3-subgraph)
# is wired first; Base is pinned but disabled until its ID is provenance-verified.
_V3_SUBGRAPHS: dict[str, str] = {
    "ethereum": "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV",
}

# Chain → EVM chainId (for downstream reward-APR matching, etc.).
CHAIN_IDS: dict[str, int] = {
    "ethereum": 1,
    "base": 8453,
    "arbitrum": 42161,
    "optimism": 10,
    "polygon": 137,
}

_V3_POSITION_QUERY = """
query Position($id: String!) {
  position(id: $id) {
    id
    owner
    liquidity
    depositedToken0
    depositedToken1
    tickLower { tickIdx }
    tickUpper { tickIdx }
    pool {
      id
      sqrtPrice
      tick
      feeTier
      liquidity
      totalValueLockedUSD
      volumeUSD
      token0 { id symbol decimals }
      token1 { id symbol decimals }
      poolDayData(first: 7, orderBy: date, orderDirection: desc) { volumeUSD }
    }
  }
}
"""


@dataclass(frozen=True)
class RawV3Position:
    """A Uniswap V3 position + pool state from the subgraph (parsed, typed)."""

    token_id: str
    chain: str
    owner: str
    liquidity: int
    tick_lower: int
    tick_upper: int
    deposited0: float
    deposited1: float

    pool_address: str
    current_tick: int
    sqrt_price_x96: int
    fee_tier: int
    pool_liquidity: int
    pool_tvl_usd: float
    pool_avg_daily_volume_usd: float

    token0_address: str
    token1_address: str
    token0_symbol: str
    token1_symbol: str
    decimals0: int
    decimals1: int


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class TheGraphClient:
    """Uniswap V3 position/pool reader over The Graph gateway.

    Args:
        api_key: Gateway key. Falls back to ``THEGRAPH_API_KEY`` env var.
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _TIMEOUT,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("THEGRAPH_API_KEY")
        self._http = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    def supported_chains() -> tuple[str, ...]:
        """Chains with a wired Uniswap V3 subgraph."""
        return tuple(_V3_SUBGRAPHS)

    def _query(self, subgraph_id: str, query: str, variables: dict[str, Any]) -> Any | None:
        """POST a GraphQL query to the gateway; ``None`` on any failure."""
        if not self.is_configured():
            return None
        url = _GATEWAY.format(key=self._api_key, subgraph_id=subgraph_id)
        headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        client = self._http or httpx.Client(timeout=self._timeout)
        try:
            resp = client.post(url, json={"query": query, "variables": variables}, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            return None
        finally:
            if self._http is None:
                client.close()
        if not isinstance(data, dict) or data.get("errors") or "data" not in data:
            return None
        return data["data"]

    def fetch_v3_position(self, chain: str, token_id: str) -> RawV3Position | None:
        """Fetch a Uniswap V3 position + its pool for ``chain``/``token_id``."""
        subgraph_id = _V3_SUBGRAPHS.get(chain.lower())
        if subgraph_id is None:
            return None
        data = self._query(subgraph_id, _V3_POSITION_QUERY, {"id": str(token_id)})
        if not isinstance(data, dict):
            return None
        pos = data.get("position")
        if not isinstance(pos, dict) or not isinstance(pos.get("pool"), dict):
            return None
        pool = pos["pool"]
        t0, t1 = pool.get("token0") or {}, pool.get("token1") or {}

        day_data = pool.get("poolDayData") or []
        volumes = [_to_float(d.get("volumeUSD")) for d in day_data if isinstance(d, dict)]
        if volumes:
            avg_daily_volume = sum(volumes) / len(volumes)
        else:
            avg_daily_volume = _to_float(pool.get("volumeUSD")) / 365

        return RawV3Position(
            token_id=str(pos.get("id") or token_id),
            chain=chain.lower(),
            owner=str(pos.get("owner") or ""),
            liquidity=_to_int(pos.get("liquidity")),
            tick_lower=_to_int((pos.get("tickLower") or {}).get("tickIdx")),
            tick_upper=_to_int((pos.get("tickUpper") or {}).get("tickIdx")),
            deposited0=_to_float(pos.get("depositedToken0")),
            deposited1=_to_float(pos.get("depositedToken1")),
            pool_address=str(pool.get("id") or ""),
            current_tick=_to_int(pool.get("tick")),
            sqrt_price_x96=_to_int(pool.get("sqrtPrice")),
            fee_tier=_to_int(pool.get("feeTier"), 3000),
            pool_liquidity=_to_int(pool.get("liquidity")),
            pool_tvl_usd=_to_float(pool.get("totalValueLockedUSD")),
            pool_avg_daily_volume_usd=avg_daily_volume,
            token0_address=str(t0.get("id") or ""),
            token1_address=str(t1.get("id") or ""),
            token0_symbol=str(t0.get("symbol") or "?"),
            token1_symbol=str(t1.get("symbol") or "?"),
            decimals0=_to_int(t0.get("decimals"), 18),
            decimals1=_to_int(t1.get("decimals"), 18),
        )


__all__ = ["CHAIN_IDS", "RawV3Position", "TheGraphClient"]
