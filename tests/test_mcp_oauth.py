# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the transparent MCP OAuth flow + the /mcp transport gate."""

from __future__ import annotations

import base64
import hashlib
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.mcp_oauth import (
    MCPAuthGate,
    access_token_audience,
    build_oauth_router,
    make_token,
    read_token,
)

_KEY = "unit-test-signing-key-0123456789abcdef"


@pytest.fixture(autouse=True)
def _enable_oauth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_OAUTH_SIGNING_KEY", _KEY)


def _pkce() -> tuple[str, str]:
    verifier = "verifier-0123456789-abcdefghijklmnopqrstuvwxyz-0123456789"
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    return verifier, challenge


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(build_oauth_router())
    return TestClient(app)


# --- signed tokens ---------------------------------------------------------


def test_token_roundtrip_and_tamper_detection() -> None:
    key = _KEY.encode()
    tok = make_token(key, {"typ": "access", "aud": "x", "exp": int(time.time()) + 60})
    assert read_token(key, tok, typ="access") is not None
    assert read_token(key, tok, typ="code") is None  # type mismatch
    assert read_token(b"different-key", tok, typ="access") is None  # bad signature
    payload, sig = tok.split(".", 1)
    assert read_token(key, f"{payload}x.{sig}", typ="access") is None  # tampered payload


def test_expired_token_rejected() -> None:
    key = _KEY.encode()
    tok = make_token(key, {"typ": "access", "aud": "x", "exp": int(time.time()) - 1})
    assert read_token(key, tok, typ="access") is None


# --- discovery metadata ----------------------------------------------------


def test_protected_resource_metadata() -> None:
    for path in ("/.well-known/oauth-protected-resource", "/.well-known/oauth-protected-resource/mcp"):
        body = _client().get(path).json()
        assert body["resource"].endswith("/mcp")
        assert body["authorization_servers"]


def test_authorization_server_metadata() -> None:
    body = _client().get("/.well-known/oauth-authorization-server").json()
    assert body["registration_endpoint"].endswith("/register")
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert "authorization_code" in body["grant_types_supported"]


# --- DCR + authorize + token flow -----------------------------------------


def test_register_requires_valid_redirect_uris() -> None:
    c = _client()
    assert c.post("/register", json={"redirect_uris": ["ftp://nope"]}).status_code == 400
    assert c.post("/register", json={}).status_code == 400
    ok = c.post("/register", json={"redirect_uris": ["https://claude.ai/cb"]})
    assert ok.status_code == 201
    assert ok.json()["client_id"]
    assert ok.json()["token_endpoint_auth_method"] == "none"


def test_authorize_rejects_unknown_redirect_uri() -> None:
    c = _client()
    client_id = c.post("/register", json={"redirect_uris": ["https://claude.ai/cb"]}).json()["client_id"]
    _, challenge = _pkce()
    r = c.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://evil.example/cb",  # not registered
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400  # never redirects to an unregistered URI


def test_full_authorization_code_flow() -> None:
    c = _client()
    redirect_uri = "https://claude.ai/cb"
    client_id = c.post("/register", json={"redirect_uris": [redirect_uri]}).json()["client_id"]
    verifier, challenge = _pkce()

    auth = c.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "resource": "http://testserver/mcp",
        },
        follow_redirects=False,
    )
    assert auth.status_code == 302
    loc = urlparse(auth.headers["location"])
    qs = parse_qs(loc.query)
    assert qs["state"] == ["xyz"]
    code = qs["code"][0]

    tok = c.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert tok.status_code == 200
    body = tok.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] > 0
    assert access_token_audience(_KEY.encode(), body["access_token"]) == "http://testserver/mcp"
    # Refresh works.
    refreshed = c.post("/token", data={"grant_type": "refresh_token", "refresh_token": body["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]


def test_token_rejects_bad_pkce() -> None:
    c = _client()
    redirect_uri = "https://claude.ai/cb"
    client_id = c.post("/register", json={"redirect_uris": [redirect_uri]}).json()["client_id"]
    _, challenge = _pkce()
    auth = c.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]
    bad = c.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": "the-wrong-verifier",
        },
    )
    assert bad.status_code == 400


# --- the transport gate ----------------------------------------------------


def _gated_app() -> FastAPI:
    app = FastAPI()

    @app.get("/mcp")
    @app.post("/mcp")
    @app.get("/mcp/")
    @app.post("/mcp/")
    def mcp() -> dict[str, bool]:
        return {"transport": True}

    @app.get("/mcp/tools")
    def tools() -> dict[str, bool]:
        return {"tools": True}

    @app.get("/api/regime")
    def api() -> dict[str, bool]:
        return {"api": True}

    app.add_middleware(MCPAuthGate)
    return app


def test_gate_challenges_unauthenticated_transport() -> None:
    r = TestClient(_gated_app()).get("/mcp")
    assert r.status_code == 401
    assert "resource_metadata" in r.headers.get("www-authenticate", "")


def test_gate_allows_valid_audience_bound_token() -> None:
    token = make_token(
        _KEY.encode(),
        {"typ": "access", "aud": "http://testserver/mcp", "exp": int(time.time()) + 60},
    )
    r = TestClient(_gated_app()).get("/mcp", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_gate_rejects_wrong_audience() -> None:
    token = make_token(
        _KEY.encode(),
        {"typ": "access", "aud": "http://other.example/mcp", "exp": int(time.time()) + 60},
    )
    r = TestClient(_gated_app()).get("/mcp", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_gate_does_not_touch_planning_or_rest() -> None:
    c = TestClient(_gated_app())
    assert c.get("/mcp/tools").status_code == 200  # planning gateway stays open
    assert c.get("/api/regime").status_code == 200  # REST stays open


def test_gate_disabled_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_OAUTH_SIGNING_KEY", raising=False)
    r = TestClient(_gated_app()).get("/mcp")
    assert r.status_code == 200  # open when OAuth is not configured
