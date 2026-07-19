# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""In-memory per-IP rate limiting middleware.

A pure-ASGI sliding-window limiter. Pure ASGI (rather than
``BaseHTTPMiddleware``) so it passes streaming responses — notably the mounted
MCP transport — through untouched.

The limiter is in-process: each server instance counts independently. Behind a
horizontally-scaled deployment the effective limit is ``limit_per_min`` times
the instance count. That is acceptable for an abuse-prevention guard on a
public read-only API; a global limit would need a shared store (Redis).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_WINDOW_SECONDS = 60.0
#: Sweep stale per-IP buckets every N requests to bound memory use.
_SWEEP_EVERY = 500


class RateLimitMiddleware:
    """Reject a client IP once it exceeds ``limit_per_min`` requests / 60s.

    Args:
        app: The wrapped ASGI application.
        limit_per_min: Allowed requests per IP per 60-second window. A value
            of ``0`` or less disables the limiter.
        exempt_prefixes: Path prefixes excused from rate limiting (e.g. the
            health probe). A plain prefix match — use ``exempt_predicate`` when
            a prefix would over-exempt (e.g. ``/mcp`` must not also excuse the
            heavy ``/mcp/tools/*`` compute POST).
        exempt_predicate: Optional per-path predicate excused from rate
            limiting, applied in addition to ``exempt_prefixes``. Lets the
            caller reuse exact transport-path logic (e.g.
            ``mcp_oauth._is_transport_path``) that a coarse prefix cannot express.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        limit_per_min: int = 60,
        exempt_prefixes: Iterable[str] = (),
        exempt_predicate: Callable[[str], bool] | None = None,
    ) -> None:
        self._app = app
        self._limit = limit_per_min
        self._exempt = tuple(exempt_prefixes)
        self._exempt_predicate = exempt_predicate
        self._hits: dict[str, list[float]] = {}
        self._request_count = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._limit <= 0:
            await self._app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if any(path.startswith(prefix) for prefix in self._exempt) or (
            self._exempt_predicate is not None and self._exempt_predicate(path)
        ):
            await self._app(scope, receive, send)
            return

        now = time.monotonic()
        cutoff = now - _WINDOW_SECONDS
        self._request_count += 1
        if self._request_count % _SWEEP_EVERY == 0:
            self._sweep(cutoff)

        client_ip = _client_ip(scope)
        hits = self._hits.setdefault(client_ip, [])
        hits[:] = [stamp for stamp in hits if stamp > cutoff]

        if len(hits) >= self._limit:
            retry_after = max(1, int(_WINDOW_SECONDS - (now - hits[0])))
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Try again shortly."},
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        hits.append(now)
        await self._app(scope, receive, send)

    def _sweep(self, cutoff: float) -> None:
        """Drop per-IP buckets whose most recent hit is older than ``cutoff``."""
        stale = [
            ip for ip, hits in self._hits.items() if not any(stamp > cutoff for stamp in hits)
        ]
        for ip in stale:
            del self._hits[ip]


def _client_ip(scope: Scope) -> str:
    """Resolve a spoofing-resistant client key for rate limiting.

    This service runs on Cloud Run, fronted by Cloudflare for ``nexusmcp.site``.
    The previous implementation used the **leftmost** ``X-Forwarded-For`` entry,
    which is client-controlled — an attacker could rotate ``X-Forwarded-For``
    per request and never share a bucket, defeating the limiter. Instead:

    1. ``CF-Connecting-IP`` — set by Cloudflare to the real client on the
       primary (``nexusmcp.site``) path; use it when present.
    2. Otherwise the **rightmost** ``X-Forwarded-For`` entry: trusted
       infrastructure (the Cloud Run frontend) *appends* the caller, so the last
       hop is the real client and any client-prepended fakes sit to its left.
    3. Fall back to the transport peer.

    Residual: a caller hitting the ``run.app`` origin directly *and* spoofing
    ``CF-Connecting-IP`` could still rotate buckets. That path is mitigated by
    Cloudflare's edge rate-limit on the cost-bearing endpoints; this in-process
    limiter is a best-effort second layer, not a security boundary. Fully
    closing it requires restricting origin ingress to Cloudflare (infra).
    """
    cf_connecting_ip = ""
    forwarded_for = ""
    for name, value in scope.get("headers", []):
        if name == b"cf-connecting-ip":
            cf_connecting_ip = value.decode("latin-1").strip()
        elif name == b"x-forwarded-for":
            forwarded_for = value.decode("latin-1")

    if cf_connecting_ip:
        return cf_connecting_ip
    if forwarded_for:
        hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    client = scope.get("client")
    if client:
        return str(client[0])
    return "unknown"


__all__ = ["RateLimitMiddleware"]
