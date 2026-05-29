# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the EIA energy price client.

Hermetic — every request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.macro import EiaEnergyData


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _price_response(value: float) -> httpx.Response:
    return httpx.Response(200, json={"response": {"data": [{"period": "2026-01-05", "value": value}]}})


def test_not_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EIA_API_KEY", raising=False)
    provider = EiaEnergyData(api_key=None)
    assert provider.is_configured() is False
    assert provider.get_wti_spot() is None


def test_wti_and_brent_use_petroleum_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/petroleum/pri/spt/data/"
        assert request.url.params["api_key"] == "eia-key"
        series = request.url.params["facets[series][]"]
        return _price_response(72.5 if series == "RWTC" else 76.1)

    provider = EiaEnergyData(api_key="eia-key", http_client=_client(handler))
    assert provider.get_wti_spot() == 72.5
    assert provider.get_brent_spot() == 76.1


def test_natural_gas_uses_natgas_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/natural-gas/pri/fut/data/"
        return _price_response(3.21)

    assert EiaEnergyData(api_key="k", http_client=_client(handler)).get_natural_gas_price() == 3.21


def test_energy_summary_aggregates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _price_response(50.0)

    summary = EiaEnergyData(api_key="k", http_client=_client(handler)).get_energy_summary()
    assert set(summary) == {"wti_crude", "brent_crude", "natural_gas", "gasoline"}
    assert summary["wti_crude"] == 50.0


def test_empty_rows_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": {"data": []}})

    assert EiaEnergyData(api_key="k", http_client=_client(handler)).get_wti_spot() is None


def test_http_error_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    assert EiaEnergyData(api_key="k", http_client=_client(handler)).get_brent_spot() is None


def test_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EIA_API_KEY", "env-key")
    assert EiaEnergyData().is_configured() is True
