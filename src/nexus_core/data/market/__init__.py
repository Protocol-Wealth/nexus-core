# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Market data integrations.

Concrete :class:`~nexus_core.data.providers.MarketDataProvider` implementations:

- :class:`YFinanceMarketData` — Yahoo Finance via ``yfinance``. Keyless.
- :class:`MboumMarketData` — MBOUM API. Yahoo-style symbols. Key required.
- :class:`MarketStackMarketData` — MarketStack v2 EOD. Key required.
- :class:`CoinGeckoMarketData` — CoinGecko crypto data. Key optional.
- :class:`CompositeMarketData` — ordered fallback across the above.

Third-party libraries (install with ``pip install nexus-core[market]``):

- yfinance (Apache 2.0) - https://github.com/ranaroussi/yfinance

The MBOUM / MarketStack / CoinGecko adapters are pure REST clients and need
only the core ``httpx`` dependency.

Reference architecture (not bundled):

- OpenBB Platform (AGPL-3.0) - data aggregation patterns
"""

from .coingecko_provider import CoinGeckoMarketData
from .composite import CompositeMarketData
from .marketstack_provider import MarketStackMarketData
from .mboum_provider import MboumMarketData
from .yfinance_provider import YFinanceMarketData

__all__ = [
    "CoinGeckoMarketData",
    "CompositeMarketData",
    "MarketStackMarketData",
    "MboumMarketData",
    "YFinanceMarketData",
]
