# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for spoofing-resistant client-IP resolution in the rate limiter.

Regression: the limiter previously keyed on the LEFTMOST X-Forwarded-For entry,
which is client-controlled — an attacker rotating it per request never shared a
bucket and bypassed the limit entirely.
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from nexus_core.app.ratelimit import RateLimitMiddleware, _client_ip


def _scope(headers: list[tuple[bytes, bytes]], client: tuple[str, int] | None = None) -> dict[str, Any]:
    return {"type": "http", "headers": headers, "client": client}


def test_prefers_cf_connecting_ip() -> None:
    ip = _client_ip(_scope([
        (b"cf-connecting-ip", b"203.0.113.7"),
        (b"x-forwarded-for", b"1.1.1.1, 2.2.2.2"),
    ]))
    assert ip == "203.0.113.7"


def test_rightmost_xff_when_no_cf() -> None:
    # Trusted frontend appends the real client → rightmost is trustworthy.
    ip = _client_ip(_scope([(b"x-forwarded-for", b"9.9.9.9, 8.8.8.8, 5.5.5.5")]))
    assert ip == "5.5.5.5"


def test_rotating_leftmost_xff_resolves_to_same_ip() -> None:
    # The attack: rotate the leftmost (spoofable) entry; the real client (rightmost) is fixed.
    ips = {
        _client_ip(_scope([(b"x-forwarded-for", f"9.9.9.{n}, 5.5.5.5".encode())]))
        for n in range(5)
    }
    assert ips == {"5.5.5.5"}  # all map to one key — no bucket escape


def test_peer_fallback() -> None:
    assert _client_ip(_scope([], client=("10.0.0.1", 1234))) == "10.0.0.1"
    assert _client_ip(_scope([])) == "unknown"


def test_rotating_leftmost_xff_does_not_escape_limit() -> None:
    inner = Starlette(routes=[Route("/x", lambda _r: PlainTextResponse("ok"))])
    client = TestClient(RateLimitMiddleware(inner, limit_per_min=2))
    # Same real client (rightmost 5.5.5.5), rotating spoofed leftmost → one bucket.
    codes = [
        client.get("/x", headers={"X-Forwarded-For": f"9.9.9.{i}, 5.5.5.5"}).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]


def test_distinct_real_clients_get_separate_buckets() -> None:
    inner = Starlette(routes=[Route("/x", lambda _r: PlainTextResponse("ok"))])
    client = TestClient(RateLimitMiddleware(inner, limit_per_min=1))
    a = client.get("/x", headers={"X-Forwarded-For": "1.1.1.1"}).status_code
    b = client.get("/x", headers={"X-Forwarded-For": "2.2.2.2"}).status_code
    assert a == 200 and b == 200  # different real clients → independent limits
