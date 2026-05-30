# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the FRED macro data provider.

Hermetic — every request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.macro import FredMacroData


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_not_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    provider = FredMacroData(api_key=None)
    assert provider.is_configured() is False
    assert provider.get_series("DGS10") is None


def test_get_series_latest_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["series_id"] == "DGS10"
        assert request.url.params["api_key"] == "fred-key"
        return httpx.Response(
            200,
            json={
                "observations": [
                    {"date": "2026-01-05", "value": "4.31"},
                    {"date": "2026-01-04", "value": "4.28"},
                ]
            },
        )

    provider = FredMacroData(api_key="fred-key", http_client=_client(handler))
    assert provider.is_configured() is True
    assert provider.get_series("DGS10") == 4.31


def test_get_series_skips_missing_observation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "observations": [
                    {"date": "2026-01-05", "value": "."},
                    {"date": "2026-01-04", "value": "4.28"},
                ]
            },
        )

    provider = FredMacroData(api_key="k", http_client=_client(handler))
    assert provider.get_series("DGS10") == 4.28


def test_get_series_http_error_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    provider = FredMacroData(api_key="k", http_client=_client(handler))
    assert provider.get_series("BOGUS") is None


def test_get_series_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    # FRED rate-limits a burst with 429; a retry after backoff should recover
    # the value rather than nulling the signal.
    monkeypatch.setattr("nexus_core.data.macro.fred.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error_code": 429, "error_message": "Too Many Requests"})
        return httpx.Response(200, json={"observations": [{"date": "2026-05-28", "value": "2.72"}]})

    provider = FredMacroData(api_key="k", http_client=_client(handler))
    assert provider.get_series("BAMLH0A0HYM2") == 2.72
    assert calls["n"] == 2  # one 429, one retry


def test_get_series_persistent_429_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nexus_core.data.macro.fred.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"error_code": 429})

    provider = FredMacroData(api_key="k", http_client=_client(handler))
    assert provider.get_series("DGS10") is None
    assert calls["n"] == 3  # initial + 2 retries, then give up (graceful)


def test_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", "env-key")
    provider = FredMacroData()
    assert provider.is_configured() is True
