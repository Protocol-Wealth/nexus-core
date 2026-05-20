# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Macro / economic data integrations.

Concrete :class:`~nexus_core.data.providers.MacroDataProvider` implementations:

- :class:`FredMacroData` — Federal Reserve Economic Data (FRED) REST API.

The FRED adapter is a pure REST client and needs only the core ``httpx``
dependency. A free FRED API key is required for live calls
(https://fredaccount.stlouisfed.org/apikeys).
"""

from .fred import FredMacroData

__all__ = ["FredMacroData"]
