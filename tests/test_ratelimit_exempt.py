# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the rate-limiter exemption boundary.

Regression: the limiter previously exempted the coarse ``/mcp`` prefix, which
also excused the heavy ``/mcp/tools/*`` planning-compute POST (unauthenticated
in ``public`` mode) and the ``/mcp-guide`` HTML from throttling. The exemption
now matches ``mcp_oauth._is_transport_path`` — only the MCP transport itself
(``/mcp`` and ``/mcp/``) is exempt.
"""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from nexus_core.app.mcp_oauth import _is_transport_path
from nexus_core.app.ratelimit import RateLimitMiddleware


def _client() -> TestClient:
    routes = [
        Route(path, lambda _r: PlainTextResponse("ok"))
        for path in ("/health", "/mcp", "/mcp/tools/monte_carlo", "/mcp-guide")
    ]
    inner = Starlette(routes=routes)
    app = RateLimitMiddleware(
        inner,
        limit_per_min=1,
        exempt_prefixes=("/health",),
        exempt_predicate=_is_transport_path,
    )
    return TestClient(app)


def test_transport_path_predicate_boundary() -> None:
    assert _is_transport_path("/mcp") is True
    assert _is_transport_path("/mcp/") is True  # SSE transport, trailing slash
    assert _is_transport_path("/mcp/tools/monte_carlo") is False  # planning compute
    assert _is_transport_path("/mcp-guide") is False  # HTML guide


def test_mcp_transport_is_exempt() -> None:
    client = _client()
    # Well over the limit of 1 — the transport is never throttled.
    codes = [client.get("/mcp").status_code for _ in range(3)]
    assert codes == [200, 200, 200]


def test_health_prefix_is_exempt() -> None:
    client = _client()
    codes = [client.get("/health").status_code for _ in range(3)]
    assert codes == [200, 200, 200]


def test_mcp_tools_compute_is_rate_limited() -> None:
    client = _client()
    # The heavy planning-compute POST path is NOT exempt: second call is 429.
    codes = [client.get("/mcp/tools/monte_carlo").status_code for _ in range(2)]
    assert codes == [200, 429]


def test_mcp_guide_is_rate_limited() -> None:
    client = _client()
    codes = [client.get("/mcp-guide").status_code for _ in range(2)]
    assert codes == [200, 429]
