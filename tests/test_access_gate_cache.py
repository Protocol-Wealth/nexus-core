# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""An authorized response on a gated path must never enter a SHARED cache.

The REST routes stamp ``Cache-Control: public, max-age=N`` — right for a ``public``
deployment, wrong in ``restricted`` mode, where ``public`` grants a CDN or proxy
permission to store the response and serve it to a caller who never presented a
key. An access decision made at the origin does not travel with a cached body.

These pin the fix at the gate, which is the only layer that knows a response was
released against a credential.
"""

from __future__ import annotations

import hashlib

import pytest

from nexus_core.app.access_gate import _privatize_cache_control

_KEY = "test-key"
_DIGEST = hashlib.sha256(_KEY.encode()).hexdigest()


def _headers(msg: dict[str, object]) -> dict[bytes, bytes]:
    return {k.lower(): v for (k, v) in msg["headers"]}  # type: ignore[union-attr,misc]


class TestPrivatizeCacheControl:
    def test_public_becomes_private(self) -> None:
        out = _privatize_cache_control(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"cache-control", b"public, max-age=3600")],
            }
        )
        cc = _headers(out)[b"cache-control"].decode()

        # The whole bug: `public` is what let the CDN store and re-serve it.
        assert "public" not in cc
        assert cc.startswith("private")
        # Freshness survives — client-side caching still works.
        assert "max-age=3600" in cc

    def test_s_maxage_is_dropped(self) -> None:
        """s-maxage is a SHARED-cache directive; it is meaningless once private."""
        out = _privatize_cache_control(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"cache-control", b"public, max-age=60, s-maxage=86400")],
            }
        )
        cc = _headers(out)[b"cache-control"].decode()

        assert "s-maxage" not in cc
        assert "max-age=60" in cc
        assert cc.startswith("private")

    def test_no_cache_control_still_gets_private(self) -> None:
        """A route that sets no header must not fall back to a cacheable default."""
        out = _privatize_cache_control(
            {"type": "http.response.start", "status": 200, "headers": [(b"x-a", b"b")]}
        )

        assert _headers(out)[b"cache-control"] == b"private"
        assert _headers(out)[b"x-a"] == b"b"  # other headers survive

    def test_already_private_is_idempotent(self) -> None:
        out = _privatize_cache_control(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"cache-control", b"private, max-age=900")],
            }
        )
        cc = _headers(out)[b"cache-control"].decode()

        assert cc.count("private") == 1
        assert "max-age=900" in cc

    def test_no_store_is_preserved(self) -> None:
        out = _privatize_cache_control(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"cache-control", b"no-store")],
            }
        )
        cc = _headers(out)[b"cache-control"].decode()

        assert "no-store" in cc
        assert "private" in cc


@pytest.mark.parametrize(
    "header",
    [b"public, max-age=3600", b"public, max-age=86400", b"public, s-maxage=900"],
)
def test_no_gated_response_can_be_shared_cached(header: bytes) -> None:
    """Whatever a route stamps, a shared cache must never be allowed to store it."""
    out = _privatize_cache_control(
        {"type": "http.response.start", "status": 200, "headers": [(b"cache-control", header)]}
    )
    cc = _headers(out)[b"cache-control"].decode().lower()

    assert "public" not in cc
    assert "s-maxage" not in cc
    assert "private" in cc
