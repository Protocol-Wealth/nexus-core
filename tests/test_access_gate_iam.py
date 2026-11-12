# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""NEXUS_ACCESS_MODE=iam: Google ID tokens instead of shared keys.

Stated cases (pw-coordinator, 2026-11-12, "go nexus plan"):
I1 no token is refused on every path but /health, the /mcp transport included;
I2 a valid token from an allow-listed service account passes;
I3 a token for another audience is refused;
I4 a valid token from an email not on the allow-list is refused;
I5 a token without email_verified is refused;
I6 a shared API key is refused in iam mode;
I7 iam mode without audience or allow-list, or an unknown mode, fails at start;
I8 an accounting request with a valid token still needs a UUID audit id.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app import access_gate
from nexus_core.app.access_gate import NexusAccessGate, validate_access_keys

AUD = "https://nexus-core-internal.test"
CALLER = "pw-api-service@pwllc-prod.iam.gserviceaccount.com"
AUDIT_ID = "11111111-2222-3333-4444-555555555555"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class _FakeJwks:
    def get_signing_key_from_jwt(self, token: str):  # noqa: ANN201
        class _K:
            key = _KEY.public_key()

        return _K()


def _token(**overrides: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": "https://accounts.google.com",
        "aud": AUD,
        "email": CALLER,
        "email_verified": True,
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)
    return jwt.encode(claims, _KEY, algorithm="RS256")


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/regime")
    def api() -> dict[str, bool]:
        return {"api": True}

    @app.get("/api/accounting/tools")
    def accounting() -> dict[str, bool]:
        return {"accounting": True}

    @app.post("/mcp")
    def mcp() -> dict[str, bool]:
        return {"mcp": True}

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"health": True}

    app.add_middleware(NexusAccessGate)
    return app


@pytest.fixture
def iam(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("NEXUS_ACCESS_MODE", "iam")
    monkeypatch.setenv("NEXUS_IAM_AUDIENCE", AUD)
    monkeypatch.setenv("NEXUS_IAM_ALLOWED_EMAILS", CALLER)
    monkeypatch.setitem(access_gate._JWKS, "client", _FakeJwks())
    return TestClient(_app())


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_i1_no_token_is_refused_except_health(iam: TestClient) -> None:
    assert iam.get("/api/regime").status_code == 401
    assert iam.post("/mcp").status_code == 401
    assert iam.get("/health").status_code == 200


def test_i2_valid_allowlisted_token_passes(iam: TestClient) -> None:
    r = iam.get("/api/regime", headers=_bearer(_token()))
    assert r.status_code == 200
    assert r.headers["x-nexus-authenticated"] == "iam"
    assert "private" in r.headers.get("cache-control", "private")


def test_i3_wrong_audience_is_refused(iam: TestClient) -> None:
    assert (
        iam.get("/api/regime", headers=_bearer(_token(aud="https://nexusmcp.site"))).status_code
        == 401
    )


def test_i4_email_not_on_allowlist_is_refused(iam: TestClient) -> None:
    t = _token(email="someone-else@pwllc-prod.iam.gserviceaccount.com")
    assert iam.get("/api/regime", headers=_bearer(t)).status_code == 401


def test_i5_unverified_email_is_refused(iam: TestClient) -> None:
    assert iam.get("/api/regime", headers=_bearer(_token(email_verified=False))).status_code == 401


def test_i6_shared_api_key_is_refused(iam: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    key = "synthetic-key-with-at-least-32-characters"
    monkeypatch.setenv("NEXUS_API_KEYS", key)
    assert iam.get("/api/regime", headers=_bearer(key)).status_code == 401
    assert iam.get("/api/regime", headers={"X-Nexus-Api-Key": key}).status_code == 401


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"NEXUS_ACCESS_MODE": "iam", "NEXUS_IAM_ALLOWED_EMAILS": CALLER}, "NEXUS_IAM_AUDIENCE"),
        ({"NEXUS_ACCESS_MODE": "iam", "NEXUS_IAM_AUDIENCE": AUD}, "NEXUS_IAM_ALLOWED_EMAILS"),
        ({"NEXUS_ACCESS_MODE": "iamm"}, "NEXUS_ACCESS_MODE"),
    ],
)
def test_i7_bad_iam_configuration_fails_at_start(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], message: str
) -> None:
    for name in ("NEXUS_ACCESS_MODE", "NEXUS_IAM_AUDIENCE", "NEXUS_IAM_ALLOWED_EMAILS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=message):
        validate_access_keys()


def test_i8_accounting_still_needs_audit_id(iam: TestClient) -> None:
    assert iam.get("/api/accounting/tools", headers=_bearer(_token())).status_code == 400
    ok = iam.get(
        "/api/accounting/tools",
        headers={**_bearer(_token()), "X-Pw-Audit-Id": AUDIT_ID},
    )
    assert ok.status_code == 200
