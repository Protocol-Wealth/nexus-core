# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EIA-backed energy price client.

A REST client over the U.S. Energy Information Administration v2 API
(https://www.eia.gov/opendata/) for energy *market* spot prices — WTI and
Brent crude, Henry Hub natural gas, and regular gasoline. The regime engine's
energy signal consumes Brent; the rest are macro context. Public market data
only — no client context.

A free API key is required (https://www.eia.gov/opendata/register.php) supplied
via the ``EIA_API_KEY`` environment variable or the ``api_key`` argument. With
no key, :meth:`is_configured` returns ``False`` and every getter returns
``None`` — the deployment still runs, without energy prices.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.eia.gov/v2"
_DEFAULT_TIMEOUT = 15.0

#: EIA series ids.
_SERIES_WTI = "RWTC"  # WTI crude spot, $/barrel
_SERIES_BRENT = "RBRTE"  # Brent crude spot, $/barrel
_SERIES_GASOLINE = "EMM_EPMR_PTE_NUS_DPG"  # US regular gasoline, $/gallon
_SERIES_NATGAS = "RNGWHHD"  # Henry Hub natural gas, $/MMBtu

#: Dataset path per series family.
_PETROLEUM_PATH = "/petroleum/pri/spt/data/"
_NATGAS_PATH = "/natural-gas/pri/fut/data/"


class EiaEnergyData:
    """Energy spot-price client backed by the EIA v2 REST API.

    Args:
        api_key: EIA API key. Falls back to the ``EIA_API_KEY`` env var.
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
        self._api_key = api_key or os.environ.get("EIA_API_KEY") or None
        self._http_client = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        """Whether an API key is available to serve requests."""
        return self._api_key is not None

    def _latest_value(self, dataset_path: str, series: str) -> float | None:
        if self._api_key is None:
            return None
        params: dict[str, str | int] = {
            "api_key": self._api_key,
            "frequency": "daily",
            "data[0]": "value",
            "facets[series][]": series,
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "offset": 0,
            "length": 1,
        }
        try:
            payload = fetch_json(
                f"{_BASE_URL}{dataset_path}",
                params=params,
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("EIA fetch for %s failed: %s", series, exc)
            return None

        rows: Any = payload.get("response", {}).get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            return None
        value = rows[0].get("value") if isinstance(rows[0], dict) else None
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def get_wti_spot(self) -> float | None:
        """Latest WTI crude spot price ($/barrel)."""
        return self._latest_value(_PETROLEUM_PATH, _SERIES_WTI)

    def get_brent_spot(self) -> float | None:
        """Latest Brent crude spot price ($/barrel) — the regime energy signal."""
        return self._latest_value(_PETROLEUM_PATH, _SERIES_BRENT)

    def get_gasoline_price(self) -> float | None:
        """Latest US regular gasoline price ($/gallon)."""
        return self._latest_value(_PETROLEUM_PATH, _SERIES_GASOLINE)

    def get_natural_gas_price(self) -> float | None:
        """Latest Henry Hub natural gas spot price ($/MMBtu)."""
        return self._latest_value(_NATGAS_PATH, _SERIES_NATGAS)

    def get_energy_summary(self) -> dict[str, float | None]:
        """Return WTI, Brent, natural gas, and gasoline in one call.

        Each field is ``None`` if its individual fetch failed.
        """
        return {
            "wti_crude": self.get_wti_spot(),
            "brent_crude": self.get_brent_spot(),
            "natural_gas": self.get_natural_gas_price(),
            "gasoline": self.get_gasoline_price(),
        }


__all__ = ["EiaEnergyData"]
