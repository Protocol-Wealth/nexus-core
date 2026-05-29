# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Derivatives market-data integrations.

Concrete clients:

- :class:`DeribitClient` — keyless Deribit public v2 REST client for listed
  option instruments, per-instrument tickers (mark price, implied vol, greeks,
  top-of-book), and the spot index price for BTC / ETH / SOL. Public market
  data only; no account/wallet/client context. Needs only the core ``httpx``
  dependency.

Everything here is an educational view of publicly listed option *structures*
and their observable market data — never individualized advice.
"""

from .deribit import (
    DISCLAIMER,
    DeribitClient,
    OptionInstrument,
    OptionTicker,
)

__all__ = ["DISCLAIMER", "DeribitClient", "OptionInstrument", "OptionTicker"]
