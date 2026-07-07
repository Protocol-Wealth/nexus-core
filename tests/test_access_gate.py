# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the optional Nexus REST/JSON access gate."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.access_gate import NexusAccessGate


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/regime")
    def api() -> dict[str, bool]:
        return {"api": True}

    @app.post("/mcp/tools/glide_path")
    def legacy_planning() -> dict[str, bool]:
        return {"planning": True}

    @app.post("/mcp")
    def mcp() -> dict[str, bool]:
        return {"mcp": True}

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"health": True}

    app.add_middleware(NexusAccessGate)
    return app


def test_access_gate_is_noop_in_public_mode(monkeypatch) -> None:
    monkeypatch.delenv("NEXUS_ACCESS_MODE", raising=False)
    monkeypatch.delenv("NEXUS_API_KEYS", raising=False)
    c = TestClient(_app())
    assert c.get("/api/regime").status_code == 200
    assert c.post("/mcp/tools/glide_path").status_code == 200


def test_access_gate_restricts_api_and_planning_gateway(monkeypatch) -> None:
    monkeypatch.setenv("NEXUS_ACCESS_MODE", "restricted")
    monkeypatch.setenv("NEXUS_API_KEYS", "secret")
    c = TestClient(_app())
    assert c.get("/api/regime").status_code == 401
    assert c.post("/mcp/tools/glide_path").status_code == 401
    assert c.get("/api/regime", headers={"Authorization": "Bearer secret"}).status_code == 200
    assert c.post("/mcp/tools/glide_path", headers={"X-Nexus-Api-Key": "secret"}).status_code == 200


def test_access_gate_leaves_mcp_transport_and_health_open(monkeypatch) -> None:
    monkeypatch.setenv("NEXUS_ACCESS_MODE", "restricted")
    monkeypatch.setenv("NEXUS_API_KEYS", "secret")
    c = TestClient(_app())
    assert c.post("/mcp").status_code == 200
    assert c.get("/health").status_code == 200


def test_access_gate_accepts_sha256_digests(monkeypatch) -> None:
    monkeypatch.setenv("NEXUS_ACCESS_MODE", "restricted")
    monkeypatch.setenv(
        "NEXUS_API_KEYS",
        "sha256:2bb80d537b1da3e38bd30361aa855686bde0baea7e69d9291e0f8d"
        "5741a3a0d",
    )
    assert TestClient(_app()).get(
        "/api/regime", headers={"Authorization": "Bearer secret"}
    ).status_code == 200
