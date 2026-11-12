# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Optional API-key gate for nexus-core REST/JSON calculation surfaces.

The public native MCP transport can remain an open-source demo surface, while
production consumers use authenticated REST/JSON endpoints. This ASGI middleware
is deliberately small and stateless: when ``NEXUS_ACCESS_MODE=restricted``, it
requires a configured Nexus service key on protected paths. When the mode is
``public`` (the default), it is a no-op so local/dev and current public deploys
do not break until secrets are rolled.

``NEXUS_ACCESS_MODE=iam`` is for a private deployment that sits behind Cloud Run
IAM (no public invoker). Callers present a Google-signed ID token from their own
service account; no shared key exists. The platform checks the token before the
request arrives, and this gate checks it again (signature, issuer, audience,
verified email on an allow-list), so an accidental public invoker binding still
fails closed. In ``iam`` mode every path except ``/health`` is protected,
including the native ``/mcp`` transport.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
from typing import Any

from starlette.concurrency import run_in_threadpool

_MODE_ENV = "NEXUS_ACCESS_MODE"
_KEYS_ENV = "NEXUS_API_KEYS"
_IAM_AUDIENCE_ENV = "NEXUS_IAM_AUDIENCE"
_IAM_EMAILS_ENV = "NEXUS_IAM_ALLOWED_EMAILS"
_GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)
_MIN_RAW_KEY_LENGTH = 32
_AUDIT_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
logger = logging.getLogger(__name__)


def access_mode() -> str:
    """Current access mode: ``public``, ``restricted`` or ``iam``."""
    return os.environ.get(_MODE_ENV, "public").strip().lower() or "public"


def _iam_audience() -> str:
    return os.environ.get(_IAM_AUDIENCE_ENV, "").strip()


def _iam_allowed_emails() -> frozenset[str]:
    return frozenset(
        e.strip().lower() for e in os.environ.get(_IAM_EMAILS_ENV, "").split(",") if e.strip()
    )


# Process-wide JWKS client for Google's ID-token keys, built on first use.
_JWKS: dict[str, Any] = {"client": None}


def _google_jwks_client() -> Any:
    """Lazily built, cached JWKS client for Google's ID-token signing keys."""
    if _JWKS["client"] is None:
        import jwt  # PyJWT[crypto]

        _JWKS["client"] = jwt.PyJWKClient(_GOOGLE_CERTS_URL, cache_keys=True, lifespan=3600)
    return _JWKS["client"]


def _verified_iam_email(headers: dict[bytes, bytes]) -> str | None:
    """Email of a valid, allow-listed Google ID token in ``Authorization``, else None.

    Checks signature (Google's published keys), issuer, audience (exactly
    ``NEXUS_IAM_AUDIENCE``), expiry, ``email_verified`` and the allow-list. Any
    failure, including a key-fetch error, returns None: the caller refuses.
    """
    auth = headers.get(b"authorization", b"").decode("latin-1").strip()
    if not auth.lower().startswith("bearer "):
        return None
    token = auth[7:].strip()
    if not token:
        return None
    try:
        import jwt  # PyJWT[crypto]

        signing_key = _google_jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=_iam_audience(),
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
    except Exception:  # noqa: BLE001 - any verification failure refuses
        return None
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        return None
    if claims.get("email_verified") is not True:
        return None
    email = str(claims.get("email", "")).strip().lower()
    if not email or email not in _iam_allowed_emails():
        return None
    return email


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
            if not _SHA256_HEX_RE.fullmatch(digest):
                raise ValueError(f"{_KEYS_ENV} contains an invalid sha256 digest")
        else:
            if len(item) < _MIN_RAW_KEY_LENGTH:
                raise ValueError(f"{_KEYS_ENV} raw keys must be at least 32 characters")
            digest = hashlib.sha256(item.encode("utf-8")).hexdigest()
        digests.append(digest)
    return digests


def validate_access_keys() -> None:
    """Reject invalid access configuration during app construction."""
    mode = access_mode()
    if mode not in ("public", "restricted", "iam"):
        raise ValueError(f"{_MODE_ENV} must be public, restricted or iam (got {mode!r})")
    if mode == "restricted" and not _key_digests():
        raise ValueError(f"{_KEYS_ENV} requires at least one key in restricted mode")
    if mode == "iam":
        if not _iam_audience():
            raise ValueError(f"{_IAM_AUDIENCE_ENV} is required in iam mode")
        if not _iam_allowed_emails():
            raise ValueError(f"{_IAM_EMAILS_ENV} requires at least one email in iam mode")


def _is_protected_path(path: str) -> bool:
    """Paths that are production calculation/data surfaces."""
    return path.startswith("/api/") or path == "/mcp/tools" or path.startswith("/mcp/tools/")


def _presented_key(headers: dict[bytes, bytes]) -> str:
    auth = headers.get(b"authorization", b"").decode("latin-1").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return headers.get(b"x-nexus-api-key", b"").decode("latin-1").strip()


def _authorized_key_fingerprint(headers: dict[bytes, bytes]) -> str | None:
    key = _presented_key(headers)
    if not key:
        return None
    presented = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if any(hmac.compare_digest(presented, digest) for digest in _key_digests()):
        return presented[:12]
    return None


def _accounting_audit_id(path: str, headers: dict[bytes, bytes]) -> str | None:
    """Return the clean accounting audit id, or ``None`` when invalid/missing."""
    if not path.startswith("/api/accounting/"):
        return "not-applicable"
    value = headers.get(b"x-pw-audit-id", b"").decode("latin-1").strip()
    return value if _AUDIT_ID_RE.fullmatch(value) else None


async def _reject(send: Any, status: int, error: str, description: str) -> None:
    body = json.dumps({"error": error, "error_description": description}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


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
        mode = access_mode()
        protected = (mode == "iam" and path != "/health" and not path.startswith("/health/")) or (
            mode == "restricted" and _is_protected_path(path)
        )
        if scope.get("type") != "http" or not protected:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        if mode == "iam":
            email = await run_in_threadpool(_verified_iam_email, headers)
            key_fingerprint = None if email is None else "iam:" + email
        else:
            key_fingerprint = _authorized_key_fingerprint(headers)
        audit_id = _accounting_audit_id(path, headers)
        if key_fingerprint is not None and audit_id is not None:

            async def _send(message: dict[str, Any]) -> None:
                if message.get("type") == "http.response.start":
                    message = _privatize_cache_control(message)
                    response_headers = list(message.get("headers", []))
                    response_headers.append((b"x-nexus-authenticated", mode.encode("ascii")))
                    if audit_id != "not-applicable":
                        response_headers.append((b"x-pw-audit-id", audit_id.encode("ascii")))
                    message["headers"] = response_headers
                    if audit_id != "not-applicable":
                        logger.info(
                            "accounting request audit_id=%s path=%s key_fingerprint=%s status=%s",
                            audit_id,
                            path,
                            key_fingerprint,
                            message.get("status"),
                        )
                await send(message)

            await self.app(scope, receive, _send)
            return

        if key_fingerprint is not None:
            await _reject(
                send,
                400,
                "invalid_audit_id",
                "Accounting requests require a UUID x-pw-audit-id",
            )
            return
        if mode == "iam":
            await _reject(
                send, 401, "unauthorized", "Google ID token from an allowed caller required"
            )
            return
        await _reject(send, 401, "unauthorized", "Nexus API key required")


__all__ = ["NexusAccessGate", "access_mode"]
