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
import time
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
_DEFAULT_TIMEOUT = 10.0

#: FRED encodes a missing observation as a literal ``"."``.
_MISSING_VALUES = frozenset({None, ".", ""})

#: Retries (after the first attempt) on a 429. The regime engine fetches several
#: FRED series in quick succession; a burst can trip FRED's rate limit and a 429
#: would otherwise silently null a signal. A short backoff lets the burst recover.
_MAX_FRED_RETRIES = 2
_RETRY_BASE_DELAY = 0.5


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse a ``Retry-After`` header (integer seconds), if present and valid."""
    raw = response.headers.get("Retry-After", "").strip()
    if raw.isdigit():
        return float(raw)
    return None


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
        observation = self.get_series_observation(series_id)
        return observation[0] if observation is not None else None

    def get_series_observation(self, series_id: str) -> tuple[float, str] | None:
        """Return the latest ``(value, observation_date)`` for ``series_id``, or ``None``.

        The observation date is the data point's own date (e.g. ``2026-05-28``),
        which lets callers surface real provenance instead of the fetch time.
        """
        if self._api_key is None:
            return None
        payload = self._fetch_observations(series_id)
        observations = payload.get("observations") if isinstance(payload, dict) else None
        if not isinstance(observations, list):
            return None
        for observation in observations:
            if not isinstance(observation, dict):
                continue
            value: Any = observation.get("value")
            if value in _MISSING_VALUES:
                continue
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                continue
            date = observation.get("date")
            return parsed, str(date) if date else ""
        return None

    def _fetch_observations(self, series_id: str) -> Any | None:
        """Fetch raw observations for ``series_id``, retrying on a 429.

        Returns the parsed JSON payload, or ``None`` if the request fails after
        retries (the caller degrades gracefully to a neutral prior).
        """
        params = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 10,
        }
        for attempt in range(_MAX_FRED_RETRIES + 1):
            try:
                return fetch_json(
                    _OBSERVATIONS_URL,
                    params=params,
                    client=self._http_client,
                    timeout=self._timeout,
                )
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status == 429 and attempt < _MAX_FRED_RETRIES:
                    delay = _retry_after_seconds(exc.response) or _RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "FRED rate-limited (429) for %s; retry %d/%d in %.1fs",
                        series_id,
                        attempt + 1,
                        _MAX_FRED_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                # Non-retryable 4xx/5xx (or exhausted 429 retries). A 4xx usually
                # means an invalid/expired FRED_API_KEY — log at WARNING so the
                # cause is visible rather than surfacing as generic "No data".
                logger.warning(
                    "FRED upstream %s for %s — check FRED_API_KEY: %s",
                    status,
                    series_id,
                    exc.response.text[:200],
                )
                return None
            except (httpx.HTTPError, ValueError) as exc:
                logger.debug("FRED fetch for %s failed: %s", series_id, exc)
                return None
        return None


__all__ = ["FredMacroData"]
