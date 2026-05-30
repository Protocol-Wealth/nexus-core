# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Baseline security-response headers.

Pure-ASGI (not ``BaseHTTPMiddleware``) so it never buffers the mounted MCP SSE
stream, consistent with :mod:`.ratelimit` and the MCP auth gate. Adds headers
that are safe for a public, read-only API plus the two HTML pages:

- ``X-Content-Type-Options: nosniff`` — block MIME sniffing.
- ``X-Frame-Options: DENY`` + CSP ``frame-ancestors 'none'`` — the pages are
  never meant to be framed.
- ``Referrer-Policy: strict-origin-when-cross-origin``.
- ``Content-Security-Policy`` — applied ONLY to ``text/html`` responses. It
  allows inline styles (the landing page and MCP guide use inline ``<style>`` +
  ``style=`` attributes) and the jsdelivr CDN that FastAPI's default ``/docs``
  Swagger UI loads from; JSON API responses get no CSP, so nothing client-side
  can break.

HSTS is intentionally NOT set here: TLS terminates at Cloudflare/Cloud Run, so
HSTS belongs at the edge (see DEPLOY.md). Setting it in-app would be redundant
and could misfire if the origin is ever reached over plain HTTP.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

_BASE_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
)

# CSP for HTML only. Allows inline styles (landing + guide) and the jsdelivr CDN
# that the default /docs Swagger UI pulls JS/CSS from. ``frame-ancestors 'none'``
# mirrors X-Frame-Options: DENY for modern browsers.
_HTML_CSP = (
    b"default-src 'self'; "
    b"img-src 'self' data: https://fastapi.tiangolo.com; "
    b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    b"script-src 'self' https://cdn.jsdelivr.net; "
    b"connect-src 'self'; "
    b"base-uri 'self'; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    """Append baseline security headers to every HTTP response (CSP for HTML)."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = list(message.get("headers") or [])
                present = {name.lower() for name, _ in headers}
                for name, value in _BASE_HEADERS:
                    if name not in present:
                        headers.append((name, value))
                content_type = b""
                for name, value in headers:
                    if name.lower() == b"content-type":
                        content_type = value.lower()
                        break
                if content_type.startswith(b"text/html") and b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", _HTML_CSP))
                message = {**message, "headers": headers}
            await send(message)

        await self._app(scope, receive, _send)


__all__ = ["SecurityHeadersMiddleware"]
