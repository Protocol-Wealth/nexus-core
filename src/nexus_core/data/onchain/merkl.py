# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Merkl v4 client for DeFi liquidity-incentive (reward) APR.

Merkl (api.merkl.xyz) publishes open, **keyless** reward-campaign data: for a
given chain it lists incentive "opportunities" keyed by an ``identifier`` (the
pool/vault address) with a reward ``apr`` (a percent). This is the incentive
layer that sits on top of an LP position's swap-fee APR — ``total APR ≈ fee APR
(The Graph) + reward APR (Merkl)``.

Public DeFi market data only; no wallet/account/client context. No API key.

Verified live against the v4 ``/opportunities`` shape (``apr`` is a percent,
``identifier`` is the pool/vault address, ``status`` is ``LIVE``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.merkl.xyz/v4"
_DEFAULT_TIMEOUT = 20.0
_USER_AGENT = "nexus-core/0.1 (+https://nexusmcp.site)"
_MAX_ITEMS = 100


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class RewardOpportunity:
    """A Merkl reward opportunity (incentive campaign) on a pool/vault."""

    identifier: str  # pool/vault address the campaign rewards
    name: str
    chain_id: int
    apr: float | None  # reward APR as a PERCENT (e.g. 3.27 = 3.27%)
    tvl_usd: float | None
    protocol: str | None
    status: str


class MerklClient:
    """Keyless Merkl v4 reward-incentive client.

    Args:
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self, *, http_client: httpx.Client | None = None, timeout: float = _DEFAULT_TIMEOUT
    ) -> None:
        self._http_client = http_client
        self._timeout = timeout

    def opportunities(
        self, chain_id: int, *, status: str = "LIVE", items: int = _MAX_ITEMS
    ) -> list[RewardOpportunity]:
        """Reward opportunities for ``chain_id`` (best-effort; empty on failure)."""
        params = {
            "chainId": str(chain_id),
            "status": status,
            "items": str(min(max(items, 1), _MAX_ITEMS)),
        }
        try:
            payload = fetch_json(
                f"{_BASE_URL}/opportunities",
                params=params,
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("Merkl fetch failed: %s", exc)
            return []
        if not isinstance(payload, list):
            return []

        out: list[RewardOpportunity] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            protocol = entry.get("protocol")
            out.append(
                RewardOpportunity(
                    identifier=str(entry.get("identifier") or ""),
                    name=str(entry.get("name") or ""),
                    chain_id=int(entry.get("chainId") or chain_id),
                    apr=_num(entry.get("apr")),
                    tvl_usd=_num(entry.get("tvl")),
                    protocol=protocol.get("name") if isinstance(protocol, dict) else None,
                    status=str(entry.get("status") or ""),
                )
            )
        return out

    def reward_apr_for_pool(self, chain_id: int, pool_address: str) -> float:
        """Best reward APR (percent) for a pool/vault address, or 0.0 if none.

        Matches Merkl opportunities by ``identifier`` (case-insensitive). When a
        pool has multiple live campaigns, returns the highest APR.
        """
        target = pool_address.strip().lower()
        if not target:
            return 0.0
        matches = [
            opp.apr
            for opp in self.opportunities(chain_id)
            if opp.identifier.lower() == target and opp.apr is not None
        ]
        return max(matches) if matches else 0.0


__all__ = ["MerklClient", "RewardOpportunity"]
