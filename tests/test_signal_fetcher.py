# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the breadth + precious-metals signal computations."""

from __future__ import annotations

from nexus_core.data.providers import PriceBar
from nexus_core.engine.regime.signal_fetcher import _SECTOR_ETFS, SignalFetcher


def _bars(closes: list[float]) -> list[PriceBar]:
    return [PriceBar(timestamp=f"d{i}", open=c, high=c, low=c, close=c) for i, c in enumerate(closes)]


def _up() -> list[float]:
    return [100.0] * 209 + [120.0]  # latest well above the 200-day mean


def _down() -> list[float]:
    return [100.0] * 209 + [80.0]  # latest below the 200-day mean


class _FakeMarket:
    def __init__(self, closes_by_symbol: dict[str, list[float]]) -> None:
        self._m = closes_by_symbol

    def get_quote(self, symbol: str) -> None:
        return None

    def get_price_history(self, symbol: str, *, days: int = 365, interval: str = "1d") -> list[PriceBar]:
        return _bars(self._m.get(symbol, []))


def test_breadth_is_pct_of_sectors_above_200dma() -> None:
    # 8 of 11 sectors above their 200DMA → breadth 72.7%.
    above, below = _SECTOR_ETFS[:8], _SECTOR_ETFS[8:]
    closes = {s: _up() for s in above} | {s: _down() for s in below}
    fetcher = SignalFetcher(market_data=_FakeMarket(closes))  # type: ignore[arg-type]
    assert fetcher._fetch_breadth() == round(100.0 * 8 / 11, 1)


def test_breadth_requires_quorum() -> None:
    # Only 5 of 11 sectors have enough history → below the 6-sector quorum → None.
    closes = {s: _up() for s in _SECTOR_ETFS[:5]}  # the rest return empty history
    fetcher = SignalFetcher(market_data=_FakeMarket(closes))  # type: ignore[arg-type]
    assert fetcher._fetch_breadth() is None


def test_precious_metals_signal_from_gld_200dma() -> None:
    assert (
        SignalFetcher(market_data=_FakeMarket({"GLD": _up()}))._fetch_precious_metals_signal()  # type: ignore[arg-type]
        == "bullish"
    )
    assert (
        SignalFetcher(market_data=_FakeMarket({"GLD": _down()}))._fetch_precious_metals_signal()  # type: ignore[arg-type]
        == "bearish"
    )
    neutral = [100.0] * 209 + [100.5]  # within ±2% of the 200-day mean
    assert (
        SignalFetcher(market_data=_FakeMarket({"GLD": neutral}))._fetch_precious_metals_signal()  # type: ignore[arg-type]
        == "neutral"
    )


def test_signals_degrade_to_none_without_history() -> None:
    fetcher = SignalFetcher(market_data=_FakeMarket({}))  # type: ignore[arg-type]
    assert fetcher._fetch_breadth() is None
    assert fetcher._fetch_precious_metals_signal() is None
