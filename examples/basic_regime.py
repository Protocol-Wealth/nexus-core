# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Minimal regime detection example with stub data providers.

Run this file to see the regime engine classify a synthetic market snapshot.
In production, replace the stub providers with real adapters (FRED API,
a broker quote feed, your internal data service, etc.).

    python examples/basic_regime.py
"""

from __future__ import annotations

from nexus_core.data.providers import MacroDataProvider, MarketDataProvider, Quote
from nexus_core.engine.regime import RegimeEngine, RegimeThresholds


class StubMarketData:
    """Hand-rolled market data for demo purposes."""

    _quotes = {
        "GC=F": Quote(symbol="GC=F", price=4550.0),  # Gold futures
        "GLD": Quote(symbol="GLD", price=450.0),
        "SPY": Quote(symbol="SPY", price=540.0),
        "^VIX": Quote(symbol="^VIX", price=19.5),
        "UUP": Quote(symbol="UUP", price=27.8),
        "ZB=F": Quote(symbol="ZB=F", price=118.0),
    }

    def get_quote(self, symbol: str) -> Quote | None:
        return self._quotes.get(symbol)

    def get_price_history(self, symbol: str, *, days: int = 365, interval: str = "1d"):
        return []


class StubFRED:
    """Hand-rolled FRED data for demo purposes."""

    _series = {
        "DTWEXBGS": 120.0,  # ~100 after 0.83 conversion factor
        "DFII10": 1.85,  # 10Y TIPS
        "BAMLC0A4CBBB": 1.25,  # BBB OAS, 125bps
        "BAMLH0A0HYM2": 3.80,  # HY OAS
        "DGS10": 4.30,
        "DGS2": 4.10,
    }

    def get_series(self, series_id: str) -> float | None:
        return self._series.get(series_id)

    def is_configured(self) -> bool:
        return True


def main() -> None:
    # A firm wanting different defaults passes its own thresholds.
    thresholds = RegimeThresholds(
        gold_spx_growth_max=0.50,
        gold_spx_transition_max=0.70,
    )

    engine = RegimeEngine(
        market_data=StubMarketData(),
        macro_data=StubFRED(),
        thresholds=thresholds,
    )

    result = engine.classify()

    print(f"REGIME: {result.regime}")
    print(f"CONFIDENCE: {result.confidence_score}%")
    print(f"RATIONALE: {result.rationale}")
    print()
    print("SIGNALS:")
    for status in result.signal_statuses:
        print(
            f"  {status.name}: {status.current_value:.2f} "
            f"({status.status} → {status.supports_regime})"
        )

    # Serialize for downstream consumers (MCP, API, audit log).
    import json

    print()
    print("JSON payload:")
    print(json.dumps(result.to_dict(), indent=2, default=str)[:600] + "...")


if __name__ == "__main__":
    main()
