# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Jupiter price client — Solana SPL token USD prices (keyless).

Jupiter's Price API (v3) returns a derived USD price per Solana token **mint**,
aggregated from on-chain DEX liquidity — the practical price source for SPL
tokens that CoinGecko's coin-id catalogue doesn't cover. Public market data; no
wallet/account/client context, no API key.

Endpoint (verified live): ``https://lite-api.jup.ag/price/v3?ids=<mint>[,<mint>]``
→ ``{ "<mint>": { "usdPrice", "decimals", "priceChange24h", "liquidity", … } }``.
(The older ``price/v2`` and ``v4`` paths are retired.)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://lite-api.jup.ag/price/v3"
_DEFAULT_TIMEOUT = 15.0
_USER_AGENT = "nexus-core/0.1 (+https://nexusmcp.site)"
_MAX_IDS = 50  # Jupiter caps batch lookups; keep requests modest.
# base58 alphabet (Solana mints) — excludes 0, O, I, l.
_BASE58 = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def is_solana_mint(mint: str) -> bool:
    """True for a plausible Solana mint (base58, 32–44 chars)."""
    return 32 <= len(mint) <= 44 and all(c in _BASE58 for c in mint)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class JupiterPrice:
    """A Solana token's derived USD price."""

    mint: str
    usd_price: float
    decimals: int | None
    price_change_24h_pct: float | None
    liquidity_usd: float | None


class JupiterClient:
    """Keyless Jupiter v3 price client for Solana SPL tokens.

    Args:
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self, *, http_client: httpx.Client | None = None, timeout: float = _DEFAULT_TIMEOUT
    ) -> None:
        self._http_client = http_client
        self._timeout = timeout

    def get_prices(self, mints: list[str]) -> dict[str, JupiterPrice]:
        """USD prices for a batch of valid mints (best-effort; missing/invalid omitted)."""
        valid = [m for m in dict.fromkeys(mints) if is_solana_mint(m)][:_MAX_IDS]
        if not valid:
            return {}
        try:
            payload = fetch_json(
                _BASE_URL,
                params={"ids": ",".join(valid)},
                headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("Jupiter price fetch failed: %s", exc)
            return {}
        if not isinstance(payload, dict):
            return {}

        out: dict[str, JupiterPrice] = {}
        for mint, entry in payload.items():
            if not isinstance(entry, dict):
                continue
            usd = _num(entry.get("usdPrice"))
            if usd is None or usd <= 0:
                continue
            decimals = entry.get("decimals")
            out[mint] = JupiterPrice(
                mint=mint,
                usd_price=usd,
                decimals=int(decimals) if isinstance(decimals, int) else None,
                price_change_24h_pct=_num(entry.get("priceChange24h")),
                liquidity_usd=_num(entry.get("liquidity")),
            )
        return out

    def get_price(self, mint: str) -> JupiterPrice | None:
        """USD price for a single Solana mint, or ``None``."""
        return self.get_prices([mint]).get(mint)


__all__ = ["JupiterClient", "JupiterPrice", "is_solana_mint"]
