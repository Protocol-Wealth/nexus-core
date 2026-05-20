# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the yfinance market data provider.

Hermetic — a fake ticker factory is injected, so no network call is made.
"""

from __future__ import annotations

import pandas as pd

from nexus_core.data.market import YFinanceMarketData
from nexus_core.data.providers import PriceBar, Quote


class FakeTicker:
    """Stand-in for ``yfinance.Ticker`` with caller-supplied data."""

    def __init__(self, *, fast_info: dict | None = None, frame: pd.DataFrame | None = None) -> None:
        self.fast_info = fast_info if fast_info is not None else {}
        self._frame = frame if frame is not None else pd.DataFrame()

    def history(self, **kwargs: object) -> pd.DataFrame:
        return self._frame


def _ohlcv_frame() -> pd.DataFrame:
    index = pd.to_datetime(["2026-01-02", "2026-01-03"])
    return pd.DataFrame(
        {
            "Open": [100.0, 102.0],
            "High": [103.0, 104.0],
            "Low": [99.0, 101.0],
            "Close": [102.0, 103.5],
            "Volume": [1_000_000.0, 1_200_000.0],
        },
        index=index,
    )


def test_get_quote_from_fast_info() -> None:
    ticker = FakeTicker(fast_info={"lastPrice": 542.13})
    provider = YFinanceMarketData(ticker_factory=lambda symbol: ticker)
    quote = provider.get_quote("SPY")
    assert isinstance(quote, Quote)
    assert quote.symbol == "SPY"
    assert quote.price == 542.13


def test_get_quote_falls_back_to_recent_close() -> None:
    ticker = FakeTicker(fast_info={}, frame=_ohlcv_frame())
    provider = YFinanceMarketData(ticker_factory=lambda symbol: ticker)
    quote = provider.get_quote("SPY")
    assert quote is not None
    assert quote.price == 103.5


def test_get_quote_missing_returns_none() -> None:
    ticker = FakeTicker(fast_info={}, frame=pd.DataFrame())
    provider = YFinanceMarketData(ticker_factory=lambda symbol: ticker)
    assert provider.get_quote("NOPE") is None


def test_get_quote_swallows_exceptions() -> None:
    def boom(symbol: str) -> FakeTicker:
        raise RuntimeError("network down")

    provider = YFinanceMarketData(ticker_factory=boom)
    assert provider.get_quote("SPY") is None


def test_get_price_history_maps_frame_to_bars() -> None:
    ticker = FakeTicker(frame=_ohlcv_frame())
    provider = YFinanceMarketData(ticker_factory=lambda symbol: ticker)
    bars = provider.get_price_history("SPY", days=30)
    assert len(bars) == 2
    assert all(isinstance(bar, PriceBar) for bar in bars)
    assert bars[0].open == 100.0
    assert bars[1].close == 103.5
    assert bars[0].volume == 1_000_000.0


def test_get_price_history_empty_frame() -> None:
    ticker = FakeTicker(frame=pd.DataFrame())
    provider = YFinanceMarketData(ticker_factory=lambda symbol: ticker)
    assert provider.get_price_history("SPY") == []
