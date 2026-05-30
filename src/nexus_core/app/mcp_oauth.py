# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Transparent OAuth 2.1 for the MCP transport.

nexus-core is a public, read-only, no-PII service, but claude.ai's custom-connector
flow requires the MCP authorization handshake (OAuth 2.1 + PKCE + Dynamic Client
Registration, per the MCP authorization spec). This module provides exactly that
handshake while keeping access **effectively public**: any client can register and
obtain a token without a login ("transparent" / anonymous OAuth). It exists to
satisfy the connector handshake, not to gate the (public) data.

Design (stateless, so it works across Cloud Run instances):

- All artifacts — the DCR ``client_id``, authorization codes, access/refresh tokens
  — are **HMAC-signed compact tokens** carrying their own claims. Nothing is stored
  server-side; verification is by signature + expiry. The signing key comes from
  ``MCP_OAUTH_SIGNING_KEY``; when it is absent the whole feature is disabled and the
  ``/mcp`` transport stays open (local dev / unkeyed deploys are unchanged).
- The ``client_id`` encodes the registered ``redirect_uris`` (signed), so DCR is
  stateless yet ``/authorize`` and ``/token`` still enforce an **exact** redirect-URI
  match (open-redirect protection) without a client store.
- PKCE **S256** is required. Authorization codes are short-lived (60s) and bound to
  the PKCE challenge, redirect URI, and resource. Access tokens are short-lived (1h)
  and **audience-bound** to this server's canonical resource URI (RFC 8707); the gate
  rejects tokens whose audience is not this resource. Refresh tokens rotate.

Security note: because the data is public, a replayed authorization code only ever
yields another public-scope token — there is no privilege to escalate. Tokens grant
nothing beyond what an anonymous caller could already read.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

_ENV_KEY = "MCP_OAUTH_SIGNING_KEY"
_CODE_TTL = 60  # seconds — authorization code lifetime
_ACCESS_TTL = 3600  # seconds — access token lifetime
_REFRESH_TTL = 60 * 60 * 24 * 30  # 30 days
_SCOPE = "mcp"


def signing_key() -> bytes | None:
    """The HMAC signing key from the environment, or ``None`` when OAuth is off."""
    raw = os.environ.get(_ENV_KEY)
    return raw.encode("utf-8") if raw else None


def is_enabled() -> bool:
    """Whether transparent OAuth is configured (signing key present)."""
    return signing_key() is not None


# --- signed compact tokens -------------------------------------------------


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(key: bytes, payload: str) -> str:
    return _b64u(hmac.new(key, payload.encode("ascii"), hashlib.sha256).digest())


def make_token(key: bytes, claims: dict[str, Any]) -> str:
    """Return a ``payload.signature`` HMAC-signed compact token."""
    payload = _b64u(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    return f"{payload}.{_sign(key, payload)}"


def read_token(key: bytes, token: str, *, typ: str) -> dict[str, Any] | None:
    """Verify signature, type, and expiry; return claims or ``None``."""
    try:
        payload, sig = token.split(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sign(key, payload)):
        return None
    try:
        claims: dict[str, Any] = json.loads(_b64u_decode(payload))
    except (ValueError, json.JSONDecodeError):
        return None
    if claims.get("typ") != typ:
        return None
    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and time.time() > exp:
        return None
    return claims


def _pkce_ok(verifier: str, challenge: str) -> bool:
    """Verify a PKCE S256 verifier against its challenge."""
    if not verifier or not challenge:
        return False
    expected = _b64u(hashlib.sha256(verifier.encode("ascii")).digest())
    return hmac.compare_digest(expected, challenge)


# --- request-derived identifiers -------------------------------------------


def _issuer(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _resource(request: Request) -> str:
    return f"{_issuer(request)}/mcp"


def _valid_redirect_uri(uri: str) -> bool:
    """Redirect URIs MUST be https, or http on localhost (OAuth 2.1 §1.5)."""
    if uri.startswith("https://"):
        return True
    return uri.startswith("http://localhost") or uri.startswith("http://127.0.0.1")


# --- token-gate helpers (used by the ASGI gate) ----------------------------


def access_token_audience(key: bytes, token: str) -> str | None:
    """Return the audience of a valid access token, or ``None`` if invalid."""
    claims = read_token(key, token, typ="access")
    return claims.get("aud") if claims else None


# --- OAuth endpoints -------------------------------------------------------


def build_oauth_router() -> APIRouter:
    """Build the (always-open) OAuth metadata + DCR + authorize + token router."""
    router = APIRouter(tags=["oauth"], include_in_schema=False)

    def _protected_resource(request: Request) -> dict[str, Any]:
        return {
            "resource": _resource(request),
            "authorization_servers": [_issuer(request)],
            "scopes_supported": [_SCOPE],
            "bearer_methods_supported": ["header"],
        }

    @router.get("/.well-known/oauth-protected-resource")
    def protected_resource_root(request: Request) -> dict[str, Any]:
        return _protected_resource(request)

    @router.get("/.well-known/oauth-protected-resource/mcp")
    def protected_resource_mcp(request: Request) -> dict[str, Any]:
        return _protected_resource(request)

    @router.get("/.well-known/oauth-authorization-server")
    def authorization_server_metadata(request: Request) -> dict[str, Any]:
        issuer = _issuer(request)
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "registration_endpoint": f"{issuer}/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [_SCOPE],
        }

    @router.post("/register", response_model=None)
    async def register(request: Request) -> JSONResponse:
        key = signing_key()
        if key is None:
            return JSONResponse({"error": "registration_not_supported"}, status_code=404)
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid_client_metadata"}, status_code=400)
        redirect_uris = body.get("redirect_uris") if isinstance(body, dict) else None
        if (
            not isinstance(redirect_uris, list)
            or not redirect_uris
            or not all(isinstance(u, str) and _valid_redirect_uri(u) for u in redirect_uris)
        ):
            return JSONResponse(
                {
                    "error": "invalid_redirect_uri",
                    "error_description": "redirect_uris must be a non-empty list of https (or localhost) URIs",
                },
                status_code=400,
            )
        client_id = make_token(
            key, {"typ": "client", "ruris": redirect_uris, "iat": int(time.time())}
        )
        return JSONResponse(
            {
                "client_id": client_id,
                "client_id_issued_at": int(time.time()),
                "redirect_uris": redirect_uris,
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_name": body.get("client_name") if isinstance(body, dict) else None,
            },
            status_code=201,
        )

    @router.get("/authorize", response_model=None)
    def authorize(request: Request) -> Response:
        key = signing_key()
        if key is None:
            return JSONResponse({"error": "temporarily_unavailable"}, status_code=404)
        q = request.query_params
        client_id = q.get("client_id", "")
        redirect_uri = q.get("redirect_uri", "")

        # Validate the client + redirect URI BEFORE trusting the redirect target.
        client = read_token(key, client_id, typ="client")
        if client is None or redirect_uri not in client.get("ruris", []):
            return JSONResponse(
                {"error": "invalid_request", "error_description": "unknown client or redirect_uri"},
                status_code=400,
            )

        state = q.get("state")

        def _redirect_error(code: str, desc: str) -> RedirectResponse:
            params = {"error": code, "error_description": desc}
            if state is not None:
                params["state"] = state
            return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)

        if q.get("response_type") != "code":
            return _redirect_error("unsupported_response_type", "only response_type=code is supported")
        challenge = q.get("code_challenge", "")
        if not challenge or q.get("code_challenge_method") != "S256":
            return _redirect_error("invalid_request", "PKCE with code_challenge_method=S256 is required")

        # Transparent approval — public data, no interactive login.
        code = make_token(
            key,
            {
                "typ": "code",
                "cid": client_id,
                "ruri": redirect_uri,
                "chal": challenge,
                "res": q.get("resource") or _resource(request),
                "exp": int(time.time()) + _CODE_TTL,
                "nonce": secrets.token_urlsafe(8),
            },
        )
        params = {"code": code}
        if state is not None:
            params["state"] = state
        return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)

    def _issue_tokens(key: bytes, audience: str) -> dict[str, Any]:
        now = int(time.time())
        access = make_token(
            key, {"typ": "access", "aud": audience, "scope": _SCOPE, "iat": now, "exp": now + _ACCESS_TTL}
        )
        refresh = make_token(
            key, {"typ": "refresh", "aud": audience, "iat": now, "exp": now + _REFRESH_TTL}
        )
        return {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": _ACCESS_TTL,
            "refresh_token": refresh,
            "scope": _SCOPE,
        }

    @router.post("/token", response_model=None)
    async def token(request: Request) -> JSONResponse:
        key = signing_key()
        if key is None:
            return JSONResponse({"error": "temporarily_unavailable"}, status_code=404)
        form = await request.form()
        grant_type = form.get("grant_type")

        if grant_type == "authorization_code":
            code = read_token(key, str(form.get("code", "")), typ="code")
            if code is None:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            if code.get("cid") != form.get("client_id") or code.get("ruri") != form.get("redirect_uri"):
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            if not _pkce_ok(str(form.get("code_verifier", "")), str(code.get("chal", ""))):
                return JSONResponse({"error": "invalid_grant", "error_description": "PKCE failed"}, status_code=400)
            return JSONResponse(_issue_tokens(key, str(code.get("res"))), headers={"Cache-Control": "no-store"})

        if grant_type == "refresh_token":
            refresh = read_token(key, str(form.get("refresh_token", "")), typ="refresh")
            if refresh is None:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            return JSONResponse(_issue_tokens(key, str(refresh.get("aud"))), headers={"Cache-Control": "no-store"})

        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    return router


# --- ASGI gate for the MCP transport ---------------------------------------


def _is_transport_path(path: str) -> bool:
    """True for the FastMCP transport (``/mcp``, ``/mcp/``) but not the planning
    gateway (``/mcp/tools...``) or the human guide (``/mcp-guide``)."""
    if path == "/mcp":
        return True
    return path.startswith("/mcp/") and not path.startswith("/mcp/tools")


class MCPAuthGate:
    """Pure-ASGI gate: require a valid, audience-bound Bearer token on the MCP
    transport when OAuth is enabled. Implemented at the ASGI layer (not
    ``BaseHTTPMiddleware``) so it never buffers the transport's SSE stream.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        key = signing_key()
        if scope.get("type") != "http" or key is None or not _is_transport_path(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        host = headers.get(b"host", b"").decode("latin-1")
        resource = f"{scope.get('scheme', 'https')}://{host}/mcp"

        token = auth[7:] if auth.lower().startswith("bearer ") else ""
        if token and access_token_audience(key, token) == resource:
            await self.app(scope, receive, send)
            return

        issuer = f"{scope.get('scheme', 'https')}://{host}"
        www_auth = (
            f'Bearer resource_metadata="{issuer}/.well-known/oauth-protected-resource/mcp"'
        )
        body = json.dumps({"error": "invalid_token", "error_description": "MCP access token required"}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"www-authenticate", www_auth.encode("latin-1")),
                    (b"content-type", b"application/json"),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


__all__ = [
    "MCPAuthGate",
    "access_token_audience",
    "build_oauth_router",
    "is_enabled",
    "make_token",
    "read_token",
    "signing_key",
]
