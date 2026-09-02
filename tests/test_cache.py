# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the optional Upstash Redis cache.

Hermetic — every REST request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.cache import UpstashCache

_URL = "https://example.upstash.io"
_TOKEN = "t0ken"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _cache(handler: Callable[[httpx.Request], httpx.Response]) -> UpstashCache:
    return UpstashCache(_URL, _TOKEN, http_client=_client(handler))


def _never_called(request: httpx.Request) -> httpx.Response:  # pragma: no cover
    raise AssertionError("no request should be issued when the cache is unconfigured")


def test_is_configured_requires_both_url_and_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    assert UpstashCache().is_configured() is False
    assert UpstashCache(_URL, None).is_configured() is False
    assert UpstashCache(None, _TOKEN).is_configured() is False
    assert UpstashCache(_URL, _TOKEN).is_configured() is True


def test_unconfigured_cache_is_a_silent_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine must run cache-free, not fail closed, when Upstash is absent."""
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    cache = UpstashCache(http_client=_client(_never_called))
    assert cache.get("k") is None
    assert cache.set("k", "v", ttl_seconds=60) is False


def test_get_returns_the_cached_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {_TOKEN}"
        assert json.loads(request.read().decode()) == ["GET", "regime:eth"]
        return httpx.Response(200, json={"result": "expansion"})

    assert _cache(handler).get("regime:eth") == "expansion"


def test_get_treats_a_missing_key_as_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": None})

    assert _cache(handler).get("absent") is None


def test_set_sends_an_expiry_and_confirms_the_write() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.read().decode()) == ["SET", "k", "v", "EX", "300"]
        return httpx.Response(200, json={"result": "OK"})

    assert _cache(handler).set("k", "v", ttl_seconds=300) is True


def test_set_refuses_an_unbounded_entry() -> None:
    """A TTL-less key outlives whatever made it correct."""
    with pytest.raises(ValueError, match="ttl_seconds must be positive"):
        _cache(_never_called).set("k", "v", ttl_seconds=0)


def test_a_broken_cache_reads_as_a_miss_and_never_raises() -> None:
    """A cache that raises turns a degraded dependency into an outage."""

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("upstream unreachable")

    def server_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    def malformed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    for handler in (timeout, server_error, malformed):
        assert _cache(handler).get("k") is None
        assert _cache(handler).set("k", "v", ttl_seconds=60) is False
