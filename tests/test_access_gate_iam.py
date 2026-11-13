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

Added from the accepted pw-review findings on PR #341 (adjudication, 2026-11-13):
I1 also covers /health/db (only the exact /health path is open);
I2 requires a Cache-Control header that is present and private;
I9 a token from another issuer is refused;
I10 an expired token is refused;
I11 a token signed with another algorithm (HS256, none) is refused;
I12 a token issued up to 30 s in the container's future (clock skew) passes.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.responses import JSONResponse
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
    def api() -> JSONResponse:
        return JSONResponse({"api": True}, headers={"Cache-Control": "public, max-age=60"})

    @app.get("/api/accounting/tools")
    def accounting() -> dict[str, bool]:
        return {"accounting": True}

    @app.post("/mcp")
    def mcp() -> dict[str, bool]:
        return {"mcp": True}

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"health": True}

    @app.get("/health/db")
    def health_db() -> dict[str, bool]:
        return {"db": True}

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
    assert iam.get("/health/db").status_code == 401
    assert iam.get("/health").status_code == 200


def test_i2_valid_allowlisted_token_passes(iam: TestClient) -> None:
    r = iam.get("/api/regime", headers=_bearer(_token()))
    assert r.status_code == 200
    assert r.headers["x-nexus-authenticated"] == "iam"
    assert "cache-control" in r.headers
    directives = [d.strip() for d in r.headers["cache-control"].split(",")]
    assert "private" in directives
    assert "public" not in directives


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


def test_i9_wrong_issuer_is_refused(iam: TestClient) -> None:
    t = _token(iss="https://evil.example")
    assert iam.get("/api/regime", headers=_bearer(t)).status_code == 401


def test_i10_expired_token_is_refused(iam: TestClient) -> None:
    now = int(time.time())
    t = _token(iat=now - 3600, exp=now - 600)
    assert iam.get("/api/regime", headers=_bearer(t)).status_code == 401


def test_i11_other_algorithms_are_refused(iam: TestClient) -> None:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": AUD,
        "email": CALLER,
        "email_verified": True,
        "iat": now,
        "exp": now + 600,
    }
    hs256 = jwt.encode(claims, "a-shared-secret-of-at-least-32-bytes!!", algorithm="HS256")
    unsigned = jwt.encode(claims, None, algorithm="none")
    assert iam.get("/api/regime", headers=_bearer(hs256)).status_code == 401
    assert iam.get("/api/regime", headers=_bearer(unsigned)).status_code == 401


def test_i12_token_issued_slightly_in_the_future_passes(iam: TestClient) -> None:
    t = _token(iat=int(time.time()) + 20)
    assert iam.get("/api/regime", headers=_bearer(t)).status_code == 200
