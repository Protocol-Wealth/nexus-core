# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""FRED-backed macro data provider.

Implements :class:`~nexus_core.data.providers.MacroDataProvider` against the
Federal Reserve Economic Data (FRED) REST API
(https://fred.stlouisfed.org/docs/api/fred/). FRED serves the macro series the
regime engine consumes — real rates (``DFII10``), the dollar index
(``DTWEXBGS``), credit spreads (``BAMLC0A4CBBB``), treasury yields
(``DGS2`` / ``DGS10``), and more.

A free API key is required — request one at
https://fredaccount.stlouisfed.org/apikeys — and supplied via the
``FRED_API_KEY`` environment variable or the ``api_key`` argument. When no key
is configured, ``is_configured()`` returns ``False`` and the regime engine
falls back to neutral macro priors; the deployment still runs, just with
reduced macro precision.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
_DEFAULT_TIMEOUT = 10.0

#: FRED encodes a missing observation as a literal ``"."``.
_MISSING_VALUES = frozenset({None, ".", ""})


class FredMacroData:
    """Macro data provider backed by the FRED REST API.

    Args:
        api_key: FRED API key. Falls back to the ``FRED_API_KEY`` env var.
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or os.environ.get("FRED_API_KEY") or None
        self._http_client = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        """Whether an API key is available to serve requests."""
        return self._api_key is not None

    def get_series(self, series_id: str) -> float | None:
        """Return the latest observed value for ``series_id``, or ``None``."""
        if self._api_key is None:
            return None
        try:
            payload = fetch_json(
                _OBSERVATIONS_URL,
                params={
                    "series_id": series_id,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 10,
                },
                client=self._http_client,
                timeout=self._timeout,
            )
        except httpx.HTTPStatusError as exc:
            # A 4xx here usually means an invalid/expired FRED_API_KEY (FRED
            # returns 400 for a bad key). Log it at WARNING so the cause is
            # visible instead of silently surfacing as generic "No data".
            logger.warning(
                "FRED upstream %s for %s — check FRED_API_KEY: %s",
                exc.response.status_code,
                series_id,
                exc.response.text[:200],
            )
            return None
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("FRED fetch for %s failed: %s", series_id, exc)
            return None

        observations = payload.get("observations") if isinstance(payload, dict) else None
        if not isinstance(observations, list):
            return None
        for observation in observations:
            value: Any = observation.get("value") if isinstance(observation, dict) else None
            if value in _MISSING_VALUES:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None


__all__ = ["FredMacroData"]
