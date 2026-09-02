# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the anonymous native-balance REST surface."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.chain import build_chain_router
from nexus_core.data.onchain.tatum import NativeBalance, TatumClient

_ADDR = "0x" + "a" * 40

# 1.5 ETH in wei — 19 digits. The magnitude is the point: this is the value that
# exposes an int/float mistake in the response model.
_WEI = 1_500_000_000_000_000_000
_ETH = NativeBalance(chain="ethereum", symbol="ETH", address=_ADDR, balance=1.5, raw=_WEI)
_BASE = NativeBalance(
    chain="base", symbol="ETH", address=_ADDR, balance=0.0002, raw=200_000_000_000_000
)


class _FakeTatum:
    def __init__(self, *, configured: bool = True, balance: NativeBalance | None = _ETH) -> None:
        self._configured = configured
        self._balance = balance

    def is_configured(self) -> bool:
        return self._configured

    def native_balance(self, chain: str, address: str) -> NativeBalance | None:
        return self._balance

    def multi_chain_native(self, address: str) -> dict[str, NativeBalance]:
        return {"ethereum": _ETH, "base": _BASE} if self._balance else {}

    @staticmethod
    def chain_info(chain: str) -> dict[str, object] | None:
        return TatumClient.chain_info(chain)

    @staticmethod
    def supported_chains() -> tuple[str, ...]:
        return TatumClient.supported_chains()


def _client(tatum: _FakeTatum) -> TestClient:
    app = FastAPI()
    app.include_router(build_chain_router(tatum=tatum))  # type: ignore[arg-type]
    return TestClient(app)


def test_chains_lists_supported_networks() -> None:
    body = _client(_FakeTatum()).get("/api/chain/chains").json()
    assert list(body.keys()) == ["chains", "disclaimer"]
    assert {"chain", "family", "symbol"} == set(body["chains"][0].keys())
    assert any(c["chain"] == "ethereum" for c in body["chains"])


def test_balance_returns_a_native_balance() -> None:
    body = _client(_FakeTatum()).get(f"/api/chain/balance/ethereum/{_ADDR}").json()
    assert body["symbol"] == "ETH"
    assert body["balance"] == 1.5
    assert "not investment, tax, legal, or financial advice" in body["disclaimer"].lower()


def test_raw_balance_stays_an_integer_not_scientific_notation() -> None:
    """`raw` is wei, so it must serialize as an integer literal.

    Declaring it `float` renders 1500000000000000000 as 1.5e+18 — a silent wire
    change, and a precision loss, since a float cannot represent every integer
    at that magnitude. This test reads the raw response text on purpose: parsing
    the JSON first would hide the difference behind Python's own float handling.
    """
    text = _client(_FakeTatum()).get(f"/api/chain/balance/ethereum/{_ADDR}").text
    assert f'"raw":{_WEI}' in text
    assert "e+" not in text


def test_unsupported_chain_400() -> None:
    assert _client(_FakeTatum()).get(f"/api/chain/balance/nowhere/{_ADDR}").status_code == 400


def test_unconfigured_client_503() -> None:
    r = _client(_FakeTatum(configured=False)).get(f"/api/chain/balance/ethereum/{_ADDR}")
    assert r.status_code == 503


def test_missing_balance_404() -> None:
    r = _client(_FakeTatum(balance=None)).get(f"/api/chain/balance/ethereum/{_ADDR}")
    assert r.status_code == 404


def test_sweep_preserves_every_chain_key_and_field_order() -> None:
    """`balances` is keyed by chain name; the model must not narrow it."""
    body = _client(_FakeTatum()).get(f"/api/chain/native/{_ADDR}").json()
    assert list(body.keys()) == ["address", "balances", "chain_count", "disclaimer"]
    assert set(body["balances"].keys()) == {"ethereum", "base"}
    assert body["chain_count"] == 2
    assert list(body["balances"]["ethereum"].keys()) == [
        "chain",
        "symbol",
        "address",
        "balance",
        "raw",
    ]
