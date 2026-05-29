# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the Treasury yield-curve + TGA client.

Hermetic — every request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from nexus_core.data.macro import TreasuryData

_YIELD_XML = """
<feed>
  <entry><content><m:properties>
    <d:NEW_DATE>2026-01-02</d:NEW_DATE>
    <d:BC_3MONTH>4.10</d:BC_3MONTH>
    <d:BC_2YEAR>4.00</d:BC_2YEAR>
    <d:BC_10YEAR>3.90</d:BC_10YEAR>
  </m:properties></content></entry>
  <entry><content><m:properties>
    <d:NEW_DATE>2026-01-05</d:NEW_DATE>
    <d:BC_3MONTH>4.20</d:BC_3MONTH>
    <d:BC_2YEAR>4.35</d:BC_2YEAR>
    <d:BC_10YEAR>4.30</d:BC_10YEAR>
    <d:BC_30YEAR>4.55</d:BC_30YEAR>
  </m:properties></content></entry>
</feed>
"""


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_yield_curve_parses_latest_entry() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "home.treasury.gov"
        return httpx.Response(200, text=_YIELD_XML)

    curve = TreasuryData(http_client=_client(handler), year=2026).get_yield_curve()
    assert curve is not None
    # last <m:properties> entry wins
    assert curve["as_of_date"] == "2026-01-05"
    assert curve["year_10"] == 4.30
    assert curve["year_2"] == 4.35
    assert curve["spread_10y_2y"] == -0.05
    assert curve["is_inverted"] is True
    assert curve["spread_10y_3m"] == 0.10
    assert curve["year_30"] == 4.55
    assert curve["year_5"] is None  # absent in fixture


def test_yield_curve_http_error_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    assert TreasuryData(http_client=_client(handler)).get_yield_curve() is None


def test_tga_balance_and_30d_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.fiscaldata.treasury.gov"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"record_date": "2026-01-30", "open_today_bal": "750000"},
                    {"record_date": "2026-01-02", "open_today_bal": "600000"},
                ]
            },
        )

    tga = TreasuryData(http_client=_client(handler)).get_tga_balance(days=30)
    assert tga is not None
    assert tga["balance_billions"] == 750.0
    assert tga["change_30d_billions"] == 150.0  # (750000-600000)/1000
    assert tga["signal"] == "elevated"
    assert tga["record_date"] == "2026-01-30"


def test_tga_empty_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    assert TreasuryData(http_client=_client(handler)).get_tga_balance() is None
