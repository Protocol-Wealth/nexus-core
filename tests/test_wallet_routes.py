# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the anonymous wallet-balance REST surface."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.wallet import build_wallet_router

_ADDR = "0x" + "a" * 40


class _FakeDeBank:
    def __init__(self, *, configured: bool = True, snapshot: dict[str, Any] | None = None) -> None:
        self._configured = configured
        self._snapshot = snapshot

    def is_configured(self) -> bool:
        return self._configured

    def wallet_snapshot(self, address: str, *, top_n: int = 20) -> dict[str, Any] | None:
        return self._snapshot


def _client(debank: _FakeDeBank) -> TestClient:
    app = FastAPI()
    app.include_router(build_wallet_router(debank=debank))  # type: ignore[arg-type]
    return TestClient(app)


def test_wallet_ok() -> None:
    snap = {
        "address": _ADDR,
        "total_usd_value": 9000.0,
        "chains": {"eth": 9000.0},
        "token_count": 1,
        "top_tokens": [{"symbol": "ETH", "chain": "eth", "usd_value": 9000.0}],
    }
    r = _client(_FakeDeBank(snapshot=snap)).get(f"/api/wallet/{_ADDR}")
    assert r.status_code == 200
    body = r.json()
    assert body["total_usd_value"] == 9000.0
    assert "not investment, tax, legal, or financial advice" in body["disclaimer"].lower()
    assert r.headers["cache-control"] == "public, max-age=300"


def test_wallet_invalid_address_400() -> None:
    assert _client(_FakeDeBank()).get("/api/wallet/0xbad").status_code == 400


def test_wallet_not_configured_503() -> None:
    assert _client(_FakeDeBank(configured=False)).get(f"/api/wallet/{_ADDR}").status_code == 503


def test_wallet_no_data_404() -> None:
    assert _client(_FakeDeBank(snapshot=None)).get(f"/api/wallet/{_ADDR}").status_code == 404
