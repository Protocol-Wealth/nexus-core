# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the composite market data provider with ordered fallback."""

from __future__ import annotations

from nexus_core.data.market import CompositeMarketData
from nexus_core.data.providers import PriceBar, Quote


class _StaticProvider:
    """A market data provider that returns fixed values (or raises)."""

    def __init__(
        self,
        *,
        quote: Quote | None = None,
        bars: list[PriceBar] | None = None,
        raises: bool = False,
    ) -> None:
        self._quote = quote
        self._bars = bars if bars is not None else []
        self._raises = raises

    def get_quote(self, symbol: str) -> Quote | None:
        if self._raises:
            raise RuntimeError("provider down")
        return self._quote

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        if self._raises:
            raise RuntimeError("provider down")
        return self._bars


def test_returns_first_available_quote() -> None:
    composite = CompositeMarketData(
        [
            _StaticProvider(quote=None),
            _StaticProvider(quote=Quote(symbol="SPY", price=540.0)),
        ]
    )
    quote = composite.get_quote("SPY")
    assert quote is not None
    assert quote.price == 540.0


def test_skips_raising_provider() -> None:
    composite = CompositeMarketData(
        [
            _StaticProvider(raises=True),
            _StaticProvider(quote=Quote(symbol="SPY", price=1.0)),
        ]
    )
    quote = composite.get_quote("SPY")
    assert quote is not None
    assert quote.price == 1.0


def test_all_miss_returns_none() -> None:
    composite = CompositeMarketData([_StaticProvider(), _StaticProvider()])
    assert composite.get_quote("SPY") is None


def test_returns_first_non_empty_history() -> None:
    bars = [PriceBar(timestamp="2026-01-02", open=1.0, high=2.0, low=0.5, close=1.5)]
    composite = CompositeMarketData(
        [
            _StaticProvider(bars=[]),
            _StaticProvider(bars=bars),
        ]
    )
    assert composite.get_price_history("SPY", days=10) == bars


def test_empty_history_when_all_miss() -> None:
    composite = CompositeMarketData([_StaticProvider(), _StaticProvider()])
    assert composite.get_price_history("SPY") == []
