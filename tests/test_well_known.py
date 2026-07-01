# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for /llms.txt, /.well-known/security.txt, and security headers."""

from __future__ import annotations

from fastapi.testclient import TestClient

from nexus_core.app import create_app
from nexus_core.data.providers import Quote


class _FakeMarket:
    def get_quote(self, symbol: str) -> Quote | None:
        return Quote(symbol=symbol, price=100.0)

    def get_price_history(self, symbol: str, *, days: int = 365, interval: str = "1d") -> list:
        return []


class _FakeMacro:
    def get_series(self, series_id: str) -> float | None:
        return 4.3

    def is_configured(self) -> bool:
        return True


def _client() -> TestClient:
    return TestClient(create_app(market=_FakeMarket(), macro=_FakeMacro(), enable_mcp=False))


def test_llms_txt_served() -> None:
    with _client() as client:
        r = client.get("/llms.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    body = r.text
    assert "# Nexus Core" in body
    assert "nexusmcp.site/mcp" in body
    assert "not investment, tax, legal, or financial advice" in body.lower()
    assert "BTC-USD" in body  # symbology trap documented
    assert "analyze_goals" in body
    assert "build_planning_report" in body


def test_security_txt_rfc9116() -> None:
    with _client() as client:
        r = client.get("/.well-known/security.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "Contact: mailto:security@protocolwealthllc.com" in body
    assert "Expires:" in body  # RFC 9116 mandatory field
    assert "Canonical: https://nexusmcp.site/.well-known/security.txt" in body
    assert "Policy: https://github.com/Protocol-Wealth/nexus-core/blob/main/SECURITY.md" in body
    assert "Preferred-Languages: en" in body


def test_security_headers_on_html_and_json() -> None:
    with _client() as client:
        html = client.get("/")
        api = client.get("/health")
    # Base headers on every response.
    for resp in (html, api):
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert "referrer-policy" in resp.headers
    # CSP only on HTML; JSON API responses must NOT carry it.
    assert "content-security-policy" in html.headers
    assert "unsafe-inline" in html.headers["content-security-policy"]  # inline styles must work
    assert "content-security-policy" not in api.headers
