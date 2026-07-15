# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the multi-oracle price historian (logic + real adapters)."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

import httpx

from nexus_core.data.onchain.defillama_prices import DefiLlamaPriceClient
from nexus_core.data.onchain.jupiter import JupiterClient
from nexus_core.engine.accounting import (
    DefiLlamaPriceSource,
    JupiterPriceSource,
    PriceHistorian,
    PricePoint,
    PriceQuery,
)


class _FakeSource:
    """A source that prices only the (coin, timestamp) pairs in its table."""

    def __init__(self, name: str, table: dict[tuple[str, int], float]) -> None:
        self.name = name
        self._table = table

    def historical_prices(self, coins: list[str], timestamp: int) -> dict[str, PricePoint]:
        out: dict[str, PricePoint] = {}
        for coin in coins:
            value = self._table.get((coin, timestamp))
            if value is not None:
                out[coin] = PricePoint(
                    coin=coin, price_usd=Decimal(str(value)), as_of=timestamp, source=self.name
                )
        return out


class _RaisingSource:
    name = "boom"

    def historical_prices(self, coins: list[str], timestamp: int) -> dict[str, PricePoint]:
        raise RuntimeError("upstream down")


def test_override_wins_over_sources() -> None:
    historian = PriceHistorian([_FakeSource("primary", {("eth:usdc", 100): 1.0})])
    results = historian.price(
        [PriceQuery("eth:usdc", 100)], overrides={("eth:usdc", 100): Decimal("0.98")}
    )
    assert results[0].status == "priced"
    assert results[0].price_usd == Decimal("0.98")
    assert results[0].source == "override"


def test_primary_prices_and_order_is_preserved() -> None:
    historian = PriceHistorian(
        [_FakeSource("primary", {("a", 1): 10.0, ("b", 1): 20.0})]
    )
    results = historian.price([PriceQuery("b", 1), PriceQuery("a", 1)])
    assert [r.coin for r in results] == ["b", "a"]
    assert results[0].price_usd == Decimal("20.0")
    assert results[0].source == "primary"


def test_falls_through_to_secondary_source() -> None:
    primary = _FakeSource("primary", {("a", 1): 10.0})  # prices a, not b
    secondary = _FakeSource("secondary", {("b", 1): 5.0})  # prices b
    historian = PriceHistorian([primary, secondary])
    results = historian.price([PriceQuery("a", 1), PriceQuery("b", 1)])
    assert results[0].source == "primary"
    assert results[1].source == "secondary"
    assert results[1].price_usd == Decimal("5.0")


def test_unpriced_is_an_explicit_gap_not_zero() -> None:
    historian = PriceHistorian([_FakeSource("primary", {})])
    results = historian.price([PriceQuery("nope", 1)])
    assert results[0].status == "unpriced"
    assert results[0].price_usd is None
    assert results[0].source is None
    assert results[0].reason == "no oracle coverage"


def test_a_raising_source_never_breaks_the_chain() -> None:
    historian = PriceHistorian([_RaisingSource(), _FakeSource("backup", {("a", 1): 7.0})])
    results = historian.price([PriceQuery("a", 1)])
    assert results[0].status == "priced"
    assert results[0].source == "backup"


def test_groups_across_timestamps() -> None:
    historian = PriceHistorian([_FakeSource("primary", {("a", 1): 1.0, ("a", 2): 2.0})])
    results = historian.price([PriceQuery("a", 1), PriceQuery("a", 2)])
    assert [str(r.price_usd) for r in results] == ["1.0", "2.0"]


# --- real adapters over MockTransport ----------------------------------------


def _defillama(handler: Callable[[httpx.Request], httpx.Response]) -> DefiLlamaPriceSource:
    client = DefiLlamaPriceClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return DefiLlamaPriceSource(client)


def _jupiter(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    now: int,
    tolerance: int = 86_400,
) -> JupiterPriceSource:
    client = JupiterClient(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return JupiterPriceSource(client, tolerance_seconds=tolerance, now=lambda: now)


def test_defillama_adapter_yields_decimal_pricepoints() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"coins": {"ethereum:0xA0b8": {"price": 1.0, "timestamp": 99}}}
        )

    out = _defillama(handler).historical_prices(["ethereum:0xA0b8"], 100)
    assert out["ethereum:0xA0b8"].price_usd == Decimal("1.0")
    assert out["ethereum:0xA0b8"].as_of == 99
    assert out["ethereum:0xA0b8"].source == "defillama"


def test_jupiter_adapter_prices_solana_mint_within_tolerance() -> None:
    mint = "So11111111111111111111111111111111111111112"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={mint: {"usdPrice": 150.0, "decimals": 9}})

    source = _jupiter(handler, now=1000)
    out = source.historical_prices([f"solana:{mint}"], 1000)
    assert out[f"solana:{mint}"].price_usd == Decimal("150.0")
    assert out[f"solana:{mint}"].source == "jupiter"


def test_jupiter_adapter_returns_nothing_outside_tolerance() -> None:
    mint = "So11111111111111111111111111111111111111112"

    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not fetch for an out-of-window timestamp")

    source = _jupiter(handler, now=10_000_000, tolerance=3600)
    assert source.historical_prices([f"solana:{mint}"], 1000) == {}
