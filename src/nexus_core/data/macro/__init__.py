# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Macro / economic data integrations.

Concrete clients (all pure REST over the core ``httpx`` dependency):

- :class:`FredMacroData` — Federal Reserve Economic Data (FRED) series; the
  primary macro source for the regime engine. Implements
  :class:`~nexus_core.data.providers.MacroDataProvider`.
- :class:`EiaEnergyData` — EIA v2 energy spot prices (WTI, Brent, natural gas,
  gasoline).
- :class:`BeaMacroData` — BEA NIPA national accounts (real GDP, PCE, personal
  income).
- :class:`TreasuryData` — Treasury.gov yield curve + FiscalData TGA balance
  (keyless).

Each keyed client requires its own free API key (``FRED_API_KEY``,
``EIA_API_KEY``, ``BEA_API_KEY``); ``TreasuryData`` needs none. Missing keys
degrade gracefully to ``None`` rather than raising.
"""

from .bea import BeaMacroData
from .eia import EiaEnergyData
from .fred import FredMacroData
from .treasury import TreasuryData

__all__ = ["BeaMacroData", "EiaEnergyData", "FredMacroData", "TreasuryData"]
