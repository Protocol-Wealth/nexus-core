# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Optional Upstash Redis cache over the REST API.

**Cache-free by default.** When ``UPSTASH_REDIS_REST_URL`` /
``UPSTASH_REDIS_REST_TOKEN`` are unset — local development, the hermetic test
suite, any deployment that has not opted in — :meth:`UpstashCache.is_configured`
is ``False`` and every operation is a no-op. Callers fall through to the
upstream provider. A cache is a performance optimisation, never a dependency,
and an engine that cannot start without one is worse than an engine with no
cache at all.

**Every failure is swallowed.** A cache that raises turns a degraded dependency
into an outage. Timeouts, malformed payloads and non-200 responses all resolve
to "miss" and are logged at warning level. The caller cannot tell the difference
between an empty cache and a broken one, which is the point.

Uses the REST API over ``httpx`` — already a dependency — rather than a Redis
wire-protocol client, so this adds no package and works from serverless and
egress-restricted environments where a raw TCP connection would not.

Handlers here are sync, per the repo convention: REST handlers are sync ``def``
and FastAPI threadpools them.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 2.0
_CONNECT_TIMEOUT = 1.0

__all__ = ["UpstashCache"]


class UpstashCache:
    """Thin sync wrapper over the Upstash Redis REST API.

    Args:
        url: REST endpoint. Defaults to ``UPSTASH_REDIS_REST_URL``.
        token: Bearer token. Defaults to ``UPSTASH_REDIS_REST_TOKEN``.
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Total request timeout in seconds.
    """

    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        raw_url = url if url is not None else os.getenv("UPSTASH_REDIS_REST_URL")
        self._url = raw_url.rstrip("/") if raw_url else None
        self._token = token if token is not None else os.getenv("UPSTASH_REDIS_REST_TOKEN")
        self._http = http_client
        self._timeout = httpx.Timeout(timeout, connect=_CONNECT_TIMEOUT)

    def is_configured(self) -> bool:
        """Whether both a URL and a token are present."""
        return bool(self._url and self._token)

    def _command(self, command: list[str]) -> Any | None:
        """Issue one Redis command; ``None`` on any failure or when unconfigured."""
        if not self.is_configured():
            return None
        headers = {"Authorization": f"Bearer {self._token}"}
        client = self._http or httpx.Client(timeout=self._timeout)
        try:
            resp = client.post(self._url or "", json=command, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            # A cache miss and a broken cache are the same thing to the caller.
            log.warning("cache %s failed: %s", command[0].lower(), exc)
            return None
        finally:
            if self._http is None:
                client.close()
        if not isinstance(payload, dict):
            return None
        return payload.get("result")

    def get(self, key: str) -> str | None:
        """Cached value for ``key``, or ``None`` on a miss, error, or no config."""
        result = self._command(["GET", key])
        return result if isinstance(result, str) else None

    def set(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        """Store ``value`` under ``key`` with a TTL. ``True`` only on a confirmed write.

        A TTL is required rather than optional. An unbounded key in a shared
        cache outlives whatever made it correct, and the resulting stale answer
        is indistinguishable from a fresh one.
        """
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive; an unbounded cache entry goes stale")
        result = self._command(["SET", key, value, "EX", str(ttl_seconds)])
        return result == "OK"
