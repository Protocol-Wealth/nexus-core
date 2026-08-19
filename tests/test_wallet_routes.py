# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the anonymous wallet-balance REST surface."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

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


def test_wallet_response_keys_and_order_are_unchanged() -> None:
    """The typed response must serialize exactly as the previous hand-built dict.

    Field order is part of the wire output. This is the regression guard for
    typing a live public endpoint: a model that reorders or renames fields is a
    breaking change even when every value is correct.
    """
    snap = {
        "address": _ADDR,
        "total_usd_value": 9000.0,
        "chains": {"eth": 9000.0},
        "token_count": 1,
        "top_tokens": [{"symbol": "ETH", "chain": "eth", "usd_value": 9000.0}],
    }
    r = _client(_FakeDeBank(snapshot=snap)).get(f"/api/wallet/{_ADDR}")
    assert list(r.json().keys()) == [
        "address",
        "total_usd_value",
        "chains",
        "token_count",
        "top_tokens",
        "disclaimer",
    ]


def test_wallet_preserves_every_chain_key() -> None:
    """`chains` keys come from the provider, so the model must not narrow them.

    Modelling chains as fixed fields would silently drop any chain the model did
    not happen to name — the failure mode that makes a typed response worse than
    an untyped one.
    """
    chains = {"eth": 1.0, "base": 2.0, "arb": 0.0, "op": 3.5, "unknown-l2": 0.25}
    snap = {
        "address": _ADDR,
        "total_usd_value": 6.75,
        "chains": chains,
        "token_count": 0,
        "top_tokens": [],
    }
    body = _client(_FakeDeBank(snapshot=snap)).get(f"/api/wallet/{_ADDR}").json()
    assert body["chains"] == chains


def test_wallet_rejects_an_unmodelled_field_rather_than_dropping_it() -> None:
    """Producer drift must fail loudly, not vanish from the response.

    `wallet_snapshot` builds a fixed dict in this repo, so an unexpected key can
    only appear when someone edits it. Failing here is how they find out.
    """
    snap = {
        "address": _ADDR,
        "total_usd_value": 1.0,
        "chains": {},
        "token_count": 0,
        "top_tokens": [],
        "newly_added_field": "surprise",
    }
    with pytest.raises(ValidationError):
        _client(_FakeDeBank(snapshot=snap)).get(f"/api/wallet/{_ADDR}")
