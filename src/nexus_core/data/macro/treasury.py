# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""US Treasury liquidity client (yield curve + TGA).

Two keyless public sources:

- **Treasury.gov** daily yield curve XML — par rates from 1-month to 30-year.
  The 10y-2y / 10y-3m spreads and the inversion flag are recession indicators
  the regime engine references.
- **FiscalData** Daily Treasury Statement — the Treasury General Account (TGA)
  operating cash balance. A rising TGA drains market liquidity; a falling one
  adds it.

No API key for either service. Public macro data only — no client context.
Requests flow through an injectable ``httpx.Client`` so the client is
hermetically testable with ``httpx.MockTransport``.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_YIELD_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
)
_TGA_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
    "/v1/accounting/dts/operating_cash_balance"
)
_DEFAULT_TIMEOUT = 15.0

#: Yield-curve tenor → Treasury XML field.
_TENORS = {
    "month_1": "BC_1MONTH",
    "month_3": "BC_3MONTH",
    "month_6": "BC_6MONTH",
    "year_1": "BC_1YEAR",
    "year_2": "BC_2YEAR",
    "year_3": "BC_3YEAR",
    "year_5": "BC_5YEAR",
    "year_7": "BC_7YEAR",
    "year_10": "BC_10YEAR",
    "year_20": "BC_20YEAR",
    "year_30": "BC_30YEAR",
}
_DATE_RE = re.compile(r"<d:NEW_DATE[^>]*>(\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def _round(value: float | None, ndigits: int) -> float | None:
    return round(value, ndigits) if value is not None else None


class TreasuryData:
    """Treasury yield-curve + TGA liquidity client (keyless).

    Args:
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds.
        year: Yield-curve query year. Defaults to the current UTC year.
    """

    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        year: int | None = None,
    ) -> None:
        self._http_client = http_client
        self._timeout = timeout
        self._year = year

    def _get_text(self, url: str, params: dict[str, Any] | None = None) -> str | None:
        try:
            if self._http_client is not None:
                response = self._http_client.get(url, params=params, timeout=self._timeout)
                response.raise_for_status()
                return response.text
            with httpx.Client(timeout=self._timeout) as owned:
                response = owned.get(url, params=params)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as exc:
            logger.debug("Treasury text fetch failed: %s", exc)
            return None

    def get_yield_curve(self) -> dict[str, Any] | None:
        """Return the most recent Treasury par yield curve, or ``None``."""
        year = self._year if self._year is not None else datetime.now(UTC).year
        text = self._get_text(
            _YIELD_URL,
            params={"data": "daily_treasury_yield_curve", "field_tdr_date_value": year},
        )
        if not text:
            return None
        entries = text.split("<m:properties>")[1:]
        if not entries:
            return None
        latest = entries[-1]  # most recent observation

        curve: dict[str, Any] = {}
        for tenor, field in _TENORS.items():
            match = re.search(rf"<d:{field}[^>]*>([\d.]+)</d:{field}>", latest, re.IGNORECASE)
            curve[tenor] = float(match.group(1)) if match else None

        spread_10y_2y = (
            curve["year_10"] - curve["year_2"]
            if curve["year_10"] is not None and curve["year_2"] is not None
            else None
        )
        spread_10y_3m = (
            curve["year_10"] - curve["month_3"]
            if curve["year_10"] is not None and curve["month_3"] is not None
            else None
        )
        date_match = _DATE_RE.search(latest)
        curve.update(
            {
                "spread_10y_2y": _round(spread_10y_2y, 3),
                "spread_10y_3m": _round(spread_10y_3m, 3),
                "is_inverted": spread_10y_2y is not None and spread_10y_2y < 0,
                "as_of_date": date_match.group(1) if date_match else None,
            }
        )
        return curve

    def get_tga_balance(self, *, days: int = 30) -> dict[str, Any] | None:
        """Return the latest TGA operating cash balance + 30-day change."""
        try:
            payload = fetch_json(
                _TGA_URL,
                params={
                    "sort": "-record_date",
                    "format": "json",
                    "page[number]": 1,
                    "page[size]": max(1, days),
                },
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("FiscalData TGA fetch failed: %s", exc)
            return None

        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            return None

        balances: list[tuple[float, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                balances.append((float(row.get("open_today_bal", 0)), row.get("record_date", "")))
            except (TypeError, ValueError):
                continue
        if not balances:
            return None

        latest_millions, record_date = balances[0]
        latest_billions = round(latest_millions / 1000, 2)
        change_30d_billions = (
            round((balances[0][0] - balances[-1][0]) / 1000, 2) if len(balances) >= 2 else None
        )
        return {
            "balance_millions": latest_millions,
            "balance_billions": latest_billions,
            "record_date": record_date,
            "change_30d_billions": change_30d_billions,
            "signal": _tga_signal(latest_billions),
        }


def _tga_signal(balance_billions: float) -> str:
    """Descriptive liquidity classification of the TGA balance."""
    if balance_billions < 100:
        return "critical_low"
    if balance_billions < 300:
        return "low"
    if balance_billions < 600:
        return "normal"
    if balance_billions < 800:
        return "elevated"
    return "high"


__all__ = ["TreasuryData"]
