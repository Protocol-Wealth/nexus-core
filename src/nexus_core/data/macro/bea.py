# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""BEA-backed national-accounts client.

A REST client over the Bureau of Economic Analysis NIPA API
(https://apps.bea.gov/api/) for headline U.S. macro series — real GDP growth,
the PCE price index (the Fed's preferred inflation gauge), and personal income.
Public macro data only — no client context.

A free API key is required (https://apps.bea.gov/API/signup/) supplied via the
``BEA_API_KEY`` environment variable or the ``api_key`` argument. With no key,
:meth:`is_configured` returns ``False`` and every getter returns ``None``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://apps.bea.gov/api/data"
_DEFAULT_TIMEOUT = 15.0

#: NIPA table ids.
_TABLE_GDP = "T10101"  # real GDP, % change
_TABLE_PCE = "T20804"  # PCE price index
_TABLE_PERSONAL_INCOME = "T20100"  # personal income


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


class BeaMacroData:
    """National-accounts client backed by the BEA NIPA REST API.

    Args:
        api_key: BEA API key. Falls back to the ``BEA_API_KEY`` env var.
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
        self._api_key = api_key or os.environ.get("BEA_API_KEY") or None
        self._http_client = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        """Whether an API key is available to serve requests."""
        return self._api_key is not None

    def _fetch_nipa(self, table_name: str, frequency: str) -> list[dict[str, Any]] | None:
        if self._api_key is None:
            return None
        params: dict[str, str] = {
            "UserID": self._api_key,
            "method": "GetData",
            "datasetname": "NIPA",
            "TableName": table_name,
            "Frequency": frequency,
            "Year": "X",  # most recent
            "ResultFormat": "json",
        }
        try:
            payload = fetch_json(
                _BASE_URL,
                params=params,
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("BEA fetch for %s failed: %s", table_name, exc)
            return None

        results = payload.get("BEAAPI", {}).get("Results", {}) if isinstance(payload, dict) else {}
        if not isinstance(results, dict) or "Error" in results:
            return None
        data = results.get("Data")
        return data if isinstance(data, list) else None

    @staticmethod
    def _latest_two_by_line(rows: list[dict[str, Any]], line: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        series = [r for r in rows if isinstance(r, dict) and r.get("LineNumber") == line]
        if len(series) < 2:
            return None
        series.sort(key=lambda r: r.get("TimePeriod", ""), reverse=True)
        return series[0], series[1]

    def get_gdp_growth(self) -> dict[str, Any] | None:
        """Latest real GDP growth (annualized quarterly), line 1."""
        rows = self._fetch_nipa(_TABLE_GDP, "Q")
        if not rows:
            return None
        pair = self._latest_two_by_line(rows, "1")
        if pair is None:
            return None
        latest, previous = pair
        value, prev = _to_float(latest.get("DataValue")), _to_float(previous.get("DataValue"))
        if value is None:
            return None
        change = ((value - prev) / prev * 100.0) if prev else None
        return {
            "value": round(value, 2),
            "period": latest.get("TimePeriod", ""),
            "change_percent": round(change, 2) if change is not None else None,
        }

    def get_pce_inflation(self) -> dict[str, Any] | None:
        """Latest PCE price index with year-over-year change."""
        rows = self._fetch_nipa(_TABLE_PCE, "M")
        if not rows:
            return None
        ordered = sorted(
            (r for r in rows if isinstance(r, dict)),
            key=lambda r: r.get("TimePeriod", ""),
            reverse=True,
        )
        if not ordered:
            return None
        latest = ordered[0]
        value = _to_float(latest.get("DataValue"))
        if value is None:
            return None
        period = latest.get("TimePeriod", "")
        change: float | None = None
        if len(period) >= 4 and period[:4].isdigit():
            target = f"{int(period[:4]) - 1}{period[4:]}"
            for row in ordered:
                if row.get("TimePeriod") == target:
                    prev = _to_float(row.get("DataValue"))
                    if prev:
                        change = (value - prev) / prev * 100.0
                    break
        return {
            "value": round(value, 2),
            "period": period,
            "change_percent": round(change, 2) if change is not None else None,
        }

    def get_personal_income(self) -> dict[str, Any] | None:
        """Latest personal income growth, line 1."""
        rows = self._fetch_nipa(_TABLE_PERSONAL_INCOME, "M")
        if not rows:
            return None
        pair = self._latest_two_by_line(rows, "1")
        if pair is None:
            return None
        latest, previous = pair
        value, prev = _to_float(latest.get("DataValue")), _to_float(previous.get("DataValue"))
        if value is None:
            return None
        change = ((value - prev) / prev * 100.0) if prev else None
        return {
            "value": round(value, 2),
            "period": latest.get("TimePeriod", ""),
            "change_percent": round(change, 2) if change is not None else None,
        }


__all__ = ["BeaMacroData"]
