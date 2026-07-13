# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Optional API-key gate for nexus-core REST/JSON calculation surfaces.

The public native MCP transport can remain an open-source demo surface, while
production consumers use authenticated REST/JSON endpoints. This ASGI middleware
is deliberately small and stateless: when ``NEXUS_ACCESS_MODE=restricted``, it
requires a configured Nexus service key on protected paths. When the mode is
``public`` (the default), it is a no-op so local/dev and current public deploys
do not break until secrets are rolled.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any

_MODE_ENV = "NEXUS_ACCESS_MODE"
_KEYS_ENV = "NEXUS_API_KEYS"


def access_mode() -> str:
    """Current access mode: ``public`` or ``restricted``."""
    return os.environ.get(_MODE_ENV, "public").strip().lower() or "public"


def _key_digests() -> list[str]:
    """Configured key digests.

    ``NEXUS_API_KEYS`` accepts comma-separated raw keys for operational
    convenience, or ``sha256:<hex>`` entries when the deployment wants to avoid
    raw key material in env vars.
    """
    digests: list[str] = []
    for raw in os.environ.get(_KEYS_ENV, "").split(","):
        item = raw.strip()
        if not item:
            continue
        if item.lower().startswith("sha256:"):
            digest = item.split(":", 1)[1].strip().lower()
        else:
            digest = hashlib.sha256(item.encode("utf-8")).hexdigest()
        if digest:
            digests.append(digest)
    return digests


def _is_protected_path(path: str) -> bool:
    """Paths that are production calculation/data surfaces."""
    return path.startswith("/api/") or path == "/mcp/tools" or path.startswith("/mcp/tools/")


def _presented_key(headers: dict[bytes, bytes]) -> str:
    auth = headers.get(b"authorization", b"").decode("latin-1").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return headers.get(b"x-nexus-api-key", b"").decode("latin-1").strip()


def _authorized(headers: dict[bytes, bytes]) -> bool:
    key = _presented_key(headers)
    if not key:
        return False
    presented = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return any(hmac.compare_digest(presented, digest) for digest in _key_digests())


def _privatize_cache_control(message: dict[str, Any]) -> dict[str, Any]:
    """Force ``Cache-Control: private`` on an authorized response to a gated path.

    The REST routes stamp ``Cache-Control: public, max-age=N``. That is right for a
    ``public`` deployment, where the surface is open by design. It is wrong in
    ``restricted`` mode: ``public`` grants a SHARED cache (a CDN, a proxy) permission
    to store the response and hand it to a caller who never presented a key. An
    access decision made at the origin does not travel with a cached body, so a
    response released against a credential must not be shared-cacheable at all.

    ``private`` is the exactly-correct semantic here: produced for ONE authorized
    caller — a browser may keep it, a shared cache may not store it. Freshness
    (``max-age``) is preserved, so client-side caching still works; only the
    shared-cache permission is withdrawn. ``s-maxage`` is dropped because it
    addresses shared caches specifically and is meaningless once private.

    Applied centrally in the gate rather than per route: the gate is the only layer
    that knows a response was released against a credential, and a per-route fix is
    one a future route will forget to apply.
    """
    headers: list[tuple[bytes, bytes]] = [
        (k, v) for (k, v) in message.get("headers", []) if k.lower() != b"cache-control"
    ]
    existing = next(
        (v for (k, v) in message.get("headers", []) if k.lower() == b"cache-control"),
        b"",
    )
    directives = [
        d.strip()
        for d in existing.decode("latin-1").split(",")
        if d.strip() and d.strip().lower() not in ("public", "private")
    ]
    # s-maxage is a SHARED-cache directive; it has no meaning once the response is
    # private, and leaving it would invite a proxy to honor it anyway.
    directives = [d for d in directives if not d.lower().startswith("s-maxage")]
    value = ", ".join(["private", *directives]) if directives else "private"
    headers.append((b"cache-control", value.encode("latin-1")))
    message = dict(message)
    message["headers"] = headers
    return message


class NexusAccessGate:
    """Require an API key on protected REST/JSON surfaces in restricted mode.

    Also guarantees that a response released against a key is never stored in a
    shared cache — see :func:`_privatize_cache_control`.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        if (
            scope.get("type") != "http"
            or access_mode() != "restricted"
            or not _is_protected_path(path)
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        if _authorized(headers):

            async def _send(message: dict[str, Any]) -> None:
                if message.get("type") == "http.response.start":
                    message = _privatize_cache_control(message)
                await send(message)

            await self.app(scope, receive, _send)
            return

        body = json.dumps(
            {"error": "unauthorized", "error_description": "Nexus API key required"}
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


__all__ = ["NexusAccessGate", "access_mode"]
