# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from nexus_core.data.providers import Quote


class StubMarketData:
    """Minimal market data adapter for unit tests."""

    def __init__(self, quotes: dict[str, float] | None = None) -> None:
        self.quotes = quotes or {
            "GC=F": 4550.0,
            "GLD": 450.0,
            "SPY": 540.0,
            "^VIX": 19.5,
            "UUP": 27.8,
            "ZB=F": 118.0,
            "TLT": 95.0,
        }

    def get_quote(self, symbol: str) -> Quote | None:
        price = self.quotes.get(symbol)
        return Quote(symbol=symbol, price=price) if price is not None else None

    def get_price_history(self, symbol, *, days=365, interval="1d"):  # noqa: ANN001
        return []


class StubFRED:
    """Minimal FRED adapter for unit tests."""

    def __init__(self, series: dict[str, float] | None = None) -> None:
        self.series = series or {
            "DTWEXBGS": 120.0,
            "DFII10": 1.85,
            "BAMLC0A4CBBB": 1.25,
            "BAMLH0A0HYM2": 3.80,
            "DGS10": 4.30,
            "DGS2": 4.10,
            "VIXCLS": 19.5,
        }

    def get_series(self, series_id: str) -> float | None:
        return self.series.get(series_id)

    def is_configured(self) -> bool:
        return True


@pytest.fixture
def stub_market() -> StubMarketData:
    return StubMarketData()


@pytest.fixture
def stub_fred() -> StubFRED:
    return StubFRED()
