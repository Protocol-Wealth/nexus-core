# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Keyless DefiLlama **coins** price client (``coins.llama.fi``).

Distinct from the TVL client in :mod:`.defillama` (``api.llama.fi``): this is the
token *price* surface, the primary historical source for the onchain-accounting
price historian. It prices arbitrary tokens by a DefiLlama coin id:

- ``{chain}:{address}`` for an EVM token (e.g. ``ethereum:0xA0b8...``),
- ``solana:{mint}`` for a Solana token,
- ``coingecko:{id}`` for a coin by CoinGecko id.

``searchWidth`` lets DefiLlama return the nearest price within a window of the
requested timestamp, so a block with no exact tick still resolves. Coin ids go
literally in the request path (``:`` and ``,`` are valid path characters);
smoke-test the live path after any transport change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://coins.llama.fi"
_DEFAULT_TIMEOUT = 15.0
#: How far around the requested timestamp DefiLlama may search for a price.
_DEFAULT_SEARCH_WIDTH = "4h"


@dataclass(frozen=True)
class CoinPrice:
    """A token's USD price at (or near) a requested time."""

    coin: str
    price_usd: float
    timestamp: int
    symbol: str | None = None
    decimals: int | None = None
    confidence: float | None = None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _as_positive_float(value: Any) -> float | None:
    parsed = _as_float(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _parse_coins(payload: Any) -> dict[str, CoinPrice]:
    if not isinstance(payload, dict):
        return {}
    coins = payload.get("coins")
    if not isinstance(coins, dict):
        return {}
    out: dict[str, CoinPrice] = {}
    for coin, data in coins.items():
        if not isinstance(coin, str) or not isinstance(data, dict):
            continue
        price = _as_positive_float(data.get("price"))
        ts = _as_int(data.get("timestamp"))
        if price is None or ts is None:
            continue
        symbol = data.get("symbol")
        out[coin] = CoinPrice(
            coin=coin,
            price_usd=price,
            timestamp=ts,
            symbol=symbol if isinstance(symbol, str) else None,
            decimals=_as_int(data.get("decimals")),
            confidence=_as_float(data.get("confidence")),
        )
    return out


class DefiLlamaPriceClient:
    """Keyless historical token-price client backed by ``coins.llama.fi``.

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

    def historical_prices(
        self,
        coins: list[str],
        timestamp: int,
        *,
        search_width: str = _DEFAULT_SEARCH_WIDTH,
    ) -> dict[str, CoinPrice]:
        """USD prices for ``coins`` at ``timestamp`` (unix seconds).

        Missing coins are omitted (not an error). Degrades to ``{}`` on any
        transport or parse failure — it never raises and never fabricates a
        price.
        """
        wanted = [c for c in dict.fromkeys(coins) if c]
        if not wanted:
            return {}
        joined = ",".join(wanted)
        try:
            payload = fetch_json(
                f"{_BASE_URL}/prices/historical/{int(timestamp)}/{joined}",
                params={"searchWidth": search_width},
                headers={"Accept": "application/json"},
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("DefiLlama coins historical fetch failed: %s", exc)
            return {}
        return _parse_coins(payload)


__all__ = ["CoinPrice", "DefiLlamaPriceClient"]
