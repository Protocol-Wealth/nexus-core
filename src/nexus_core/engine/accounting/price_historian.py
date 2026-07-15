# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Multi-oracle historical price resolution for the onchain-accounting engine.

Given ``(coin, timestamp)`` queries, resolve a USD price through an ordered
oracle chain, honouring caller-supplied manual overrides first. A coin that no
source can price is returned as an **explicit** unpriced result — never a silent
``0`` and never a stale carry-forward, so a downstream cost-basis figure is
honestly gapped rather than fabricated.

Coin ids are DefiLlama-style: ``{chain}:{address}`` (EVM), ``solana:{mint}``, or
``coingecko:{id}``. Solana LSTs and JLP are SPL tokens, so they price by mint via
DefiLlama / Jupiter; native-stake exchange rates and staking APY (Marinade,
Sanctum) are a decoding/valuation concern for P2, not spot pricing here.

Clean-room: standard price-oracle-fallback method, re-derived. No AGPL code.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from ...data.onchain.defillama_prices import DefiLlamaPriceClient
from ...data.onchain.jupiter import JupiterClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PricePoint:
    """A resolved price from one source."""

    coin: str
    price_usd: Decimal
    as_of: int  # the actual unix-seconds timestamp of the returned price
    source: str
    confidence: float | None = None


@dataclass(frozen=True)
class PriceQuery:
    """A request for one coin's USD price at one time."""

    coin: str
    timestamp: int


@dataclass(frozen=True)
class PriceResult:
    """The historian's answer for one query: priced (with provenance) or gapped."""

    coin: str
    timestamp: int
    status: str  # "priced" | "unpriced"
    price_usd: Decimal | None = None
    source: str | None = None
    as_of: int | None = None
    confidence: float | None = None
    reason: str | None = None


class PriceSource(Protocol):
    """An oracle: given coins + a timestamp, return the subset it can price."""

    name: str

    def historical_prices(self, coins: list[str], timestamp: int) -> dict[str, PricePoint]: ...


def _to_decimal(value: float) -> Decimal:
    # via str so the float's decimal representation, not its binary artefact, is kept
    return Decimal(str(value))


class DefiLlamaPriceSource:
    """Primary historical source: DefiLlama coins API (EVM / Solana / coingecko id)."""

    name = "defillama"

    def __init__(self, client: DefiLlamaPriceClient) -> None:
        self._client = client

    def historical_prices(self, coins: list[str], timestamp: int) -> dict[str, PricePoint]:
        raw = self._client.historical_prices(coins, timestamp)
        return {
            coin: PricePoint(
                coin=coin,
                price_usd=_to_decimal(cp.price_usd),
                as_of=cp.timestamp,
                source=self.name,
                confidence=cp.confidence,
            )
            for coin, cp in raw.items()
        }


class JupiterPriceSource:
    """Near-now Solana fallback: Jupiter v3 spot price for ``solana:{mint}`` coins.

    Jupiter has no historical endpoint, so it answers only when the requested
    timestamp is within ``tolerance_seconds`` of now; otherwise it returns
    nothing and the query falls through to a gap. Covers SPL tokens including
    LSTs and JLP.
    """

    name = "jupiter"

    def __init__(
        self,
        client: JupiterClient,
        *,
        tolerance_seconds: int = 86_400,
        now: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self._tolerance = tolerance_seconds
        self._now = now or (lambda: int(datetime.now(UTC).timestamp()))

    def historical_prices(self, coins: list[str], timestamp: int) -> dict[str, PricePoint]:
        now = self._now()
        if abs(now - timestamp) > self._tolerance:
            return {}
        mint_to_coin: dict[str, str] = {}
        for coin in coins:
            prefix, sep, mint = coin.partition(":")
            if sep and prefix == "solana" and mint:
                mint_to_coin[mint] = coin
        if not mint_to_coin:
            return {}
        raw = self._client.get_prices(list(mint_to_coin))
        out: dict[str, PricePoint] = {}
        for mint, jp in raw.items():
            matched_coin = mint_to_coin.get(mint)
            if matched_coin is not None:
                out[matched_coin] = PricePoint(
                    coin=matched_coin,
                    price_usd=_to_decimal(jp.usd_price),
                    as_of=now,
                    source=self.name,
                )
        return out


class PriceHistorian:
    """Resolve historical USD prices via an ordered oracle chain + overrides.

    Overrides win. Then each source is tried in order for the still-unpriced
    coins at each timestamp (queries are grouped by timestamp so a batch source
    resolves them in one call). A source that raises is skipped, never fatal.
    """

    def __init__(self, sources: Sequence[PriceSource]) -> None:
        self._sources = list(sources)

    def price(
        self,
        queries: Sequence[PriceQuery],
        overrides: dict[tuple[str, int], Decimal] | None = None,
    ) -> list[PriceResult]:
        override_map = overrides or {}
        resolved: dict[tuple[str, int], PriceResult] = {}

        # 1. Overrides win outright.
        pending: list[PriceQuery] = []
        for query in queries:
            key = (query.coin, query.timestamp)
            if key in override_map:
                resolved[key] = PriceResult(
                    coin=query.coin,
                    timestamp=query.timestamp,
                    status="priced",
                    price_usd=override_map[key],
                    source="override",
                    as_of=query.timestamp,
                )
            elif key not in resolved:
                pending.append(query)

        # 2. Oracle chain, grouped by timestamp.
        by_ts: dict[int, list[str]] = {}
        for query in pending:
            by_ts.setdefault(query.timestamp, [])
            if query.coin not in by_ts[query.timestamp]:
                by_ts[query.timestamp].append(query.coin)

        for ts, coins in by_ts.items():
            remaining = list(coins)
            for source in self._sources:
                if not remaining:
                    break
                try:
                    points = source.historical_prices(remaining, ts)
                except Exception:  # a flaky source never breaks the chain
                    logger.debug("price source %r failed at ts=%s", source.name, ts)
                    continue
                still: list[str] = []
                for coin in remaining:
                    point = points.get(coin)
                    if point is not None:
                        resolved[(coin, ts)] = PriceResult(
                            coin=coin,
                            timestamp=ts,
                            status="priced",
                            price_usd=point.price_usd,
                            source=point.source,
                            as_of=point.as_of,
                            confidence=point.confidence,
                        )
                    else:
                        still.append(coin)
                remaining = still

        # 3. Anything unresolved is an explicit gap — never a fabricated price.
        return [
            resolved.get(
                (query.coin, query.timestamp),
                PriceResult(
                    coin=query.coin,
                    timestamp=query.timestamp,
                    status="unpriced",
                    reason="no oracle coverage",
                ),
            )
            for query in queries
        ]


def build_default_historian() -> PriceHistorian:
    """The production oracle chain: DefiLlama primary, Jupiter near-now Solana."""
    return PriceHistorian(
        [
            DefiLlamaPriceSource(DefiLlamaPriceClient()),
            JupiterPriceSource(JupiterClient()),
        ]
    )


__all__ = [
    "DefiLlamaPriceSource",
    "JupiterPriceSource",
    "PriceHistorian",
    "PricePoint",
    "PriceQuery",
    "PriceResult",
    "PriceSource",
    "build_default_historian",
]
