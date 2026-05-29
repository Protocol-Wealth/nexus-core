# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the BEA national-accounts client.

Hermetic — every request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.macro import BeaMacroData


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _nipa(rows: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, json={"BEAAPI": {"Results": {"Data": rows}}})


def test_not_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BEA_API_KEY", raising=False)
    provider = BeaMacroData(api_key=None)
    assert provider.is_configured() is False
    assert provider.get_gdp_growth() is None


def test_gdp_growth_latest_and_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["TableName"] == "T10101"
        assert request.url.params["UserID"] == "bea-key"
        return _nipa(
            [
                {"LineNumber": "1", "TimePeriod": "2026Q1", "DataValue": "2.5"},
                {"LineNumber": "1", "TimePeriod": "2025Q4", "DataValue": "2.0"},
                {"LineNumber": "2", "TimePeriod": "2026Q1", "DataValue": "9.9"},
            ]
        )

    result = BeaMacroData(api_key="bea-key", http_client=_client(handler)).get_gdp_growth()
    assert result is not None
    assert result["value"] == 2.5
    assert result["period"] == "2026Q1"
    assert result["change_percent"] == 25.0  # (2.5-2.0)/2.0*100


def test_pce_year_over_year_change() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _nipa(
            [
                {"TimePeriod": "2026M03", "DataValue": "125.0"},
                {"TimePeriod": "2025M03", "DataValue": "120.0"},
            ]
        )

    result = BeaMacroData(api_key="k", http_client=_client(handler)).get_pce_inflation()
    assert result is not None
    assert result["value"] == 125.0
    assert result["change_percent"] == pytest.approx(4.17, abs=0.01)


def test_bea_api_error_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"BEAAPI": {"Results": {"Error": {"ErrorDetail": "bad table"}}}})

    assert BeaMacroData(api_key="k", http_client=_client(handler)).get_gdp_growth() is None


def test_insufficient_rows_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _nipa([{"LineNumber": "1", "TimePeriod": "2026Q1", "DataValue": "2.5"}])

    assert BeaMacroData(api_key="k", http_client=_client(handler)).get_gdp_growth() is None
