# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Run nexus-core as an MCP server.

Requires::

    pip install nexus-core[mcp]

Then::

    python examples/mcp_server.py

By default connects via stdio (for Claude Desktop). For HTTP transport use
``server.run(transport="sse", port=8000)``.
"""

from __future__ import annotations

from nexus_core.data.providers import Quote
from nexus_core.engine.regime import RegimeEngine
from nexus_core.engine.scoring import ScoringFramework
from nexus_core.mcp.server import build_server


class StubMarketData:
    def get_quote(self, symbol: str) -> Quote | None:
        prices = {
            "GC=F": 4550.0,
            "GLD": 450.0,
            "SPY": 540.0,
            "^VIX": 19.5,
            "UUP": 27.8,
            "ZB=F": 118.0,
        }
        p = prices.get(symbol)
        return Quote(symbol=symbol, price=p) if p is not None else None

    def get_price_history(self, symbol, *, days=365, interval="1d"):
        return []


class StubFRED:
    _series = {
        "DTWEXBGS": 120.0,
        "DFII10": 1.85,
        "BAMLC0A4CBBB": 1.25,
        "DGS10": 4.30,
        "DGS2": 4.10,
    }

    def get_series(self, series_id):
        return self._series.get(series_id)

    def is_configured(self):
        return True


def main() -> None:
    regime_engine = RegimeEngine(market_data=StubMarketData(), macro_data=StubFRED())

    # Scoring framework left empty here for brevity. In production, pass a
    # ScoringFramework and a context factory mapping ticker -> ScoringContext.
    server = build_server(
        name="nexus-core-demo",
        regime_engine=regime_engine,
        scoring_framework=None,
    )
    server.run()


if __name__ == "__main__":
    main()
