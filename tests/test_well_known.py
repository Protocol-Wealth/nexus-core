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


def test_mcp_server_card_sep() -> None:
    with _client() as client:
        r = client.get("/.well-known/mcp/server-card.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    card = r.json()
    assert card["serverInfo"]["name"] == "nexus-core"
    assert card["serverInfo"]["version"]  # non-empty, from the package
    assert card["transport"] == {"type": "streamable-http", "endpoint": "https://nexusmcp.site/mcp"}
    assert card["capabilities"]["tools"] is True
    assert "335298" in card["provider"]["registration"]
    # posture is the canonical disclaimer, not a hand-written string
    assert "not investment, tax, legal, or financial advice" in card["policy"]["posture"].lower()


def test_api_catalog_rfc9727() -> None:
    with _client() as client:
        r = client.get("/.well-known/api-catalog")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/linkset+json")
    entry = r.json()["linkset"][0]
    assert entry["anchor"] == "https://nexusmcp.site/"
    hrefs = [
        link["href"]
        for rel in ("service-desc", "service-doc", "status")
        for link in entry.get(rel, [])
    ]
    assert "https://nexusmcp.site/openapi.json" in hrefs
    assert "https://nexusmcp.site/.well-known/mcp/server-card.json" in hrefs
    assert "https://nexusmcp.site/health" in hrefs


def test_robots_txt_ai_rules_and_content_signal() -> None:
    with _client() as client:
        r = client.get("/robots.txt")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "User-agent: GPTBot" in body
    assert "User-agent: Google-Extended" in body
    assert "Content-Signal:" in body
    assert "Sitemap: https://nexusmcp.site/sitemap.xml" in body


def test_sitemap_xml() -> None:
    with _client() as client:
        r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "xml" in r.headers["content-type"]
    assert "<loc>https://nexusmcp.site/</loc>" in r.text


def test_landing_advertises_link_header() -> None:
    with _client() as client:
        r = client.get("/")
    assert r.status_code == 200
    assert 'rel="api-catalog"' in r.headers.get("link", "")
