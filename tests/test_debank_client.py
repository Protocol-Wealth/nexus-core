# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the DeBank anonymous wallet-balance client.

Hermetic — every request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.onchain import DeBankClient, is_evm_address

_ADDR = "0x" + "a" * 40


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_is_evm_address() -> None:
    assert is_evm_address(_ADDR)
    assert is_evm_address("0x" + "F" * 40)
    assert not is_evm_address("0x123")
    assert not is_evm_address("notanaddress")
    assert not is_evm_address("0x" + "g" * 40)


def test_not_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEBANK_API_KEY", raising=False)
    client = DeBankClient(api_key=None)
    assert client.is_configured() is False
    assert client.get_total_balance(_ADDR) is None


def test_get_total_balance_uses_accesskey_and_lowercases() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("AccessKey") == "k"
        assert request.url.path.endswith("/user/total_balance")
        assert request.url.params["id"] == _ADDR
        return httpx.Response(
            200,
            json={
                "total_usd_value": 12345.6,
                "chain_list": [
                    {"id": "eth", "usd_value": 10000.0},
                    {"id": "base", "usd_value": 2345.6},
                ],
            },
        )

    bal = DeBankClient(api_key="k", http_client=_client(handler)).get_total_balance(_ADDR)
    assert bal is not None
    assert bal["total_usd_value"] == 12345.6
    assert bal["chains"] == {"eth": 10000.0, "base": 2345.6}


def test_get_tokens_flat_with_dust_filter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {"id": "eth:1", "chain": "eth", "symbol": "ETH", "name": "Ether", "amount": 2.0, "price": 3000.0},
                {"id": "eth:2", "chain": "eth", "symbol": "DUST", "name": "Dust", "amount": 1.0, "price": 0.0001},
            ],
        )

    tokens = DeBankClient(api_key="k", http_client=_client(handler)).get_tokens(_ADDR)
    assert [t.symbol for t in tokens] == ["ETH"]  # dust (<$0.01) filtered
    assert tokens[0].usd_value == 6000.0


def test_get_tokens_dict_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "eth": [{"symbol": "ETH", "chain": "eth", "amount": 1.0, "price": 3000.0}],
                "base": [{"symbol": "USDC", "chain": "base", "amount": 100.0, "price": 1.0}],
            },
        )

    syms = {t.symbol for t in DeBankClient(api_key="k", http_client=_client(handler)).get_tokens(_ADDR)}
    assert syms == {"ETH", "USDC"}


def test_wallet_snapshot_combines_balance_and_tokens() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "total_balance" in str(request.url):
            return httpx.Response(
                200, json={"total_usd_value": 9000.0, "chain_list": [{"id": "eth", "usd_value": 9000.0}]}
            )
        return httpx.Response(200, json=[{"symbol": "ETH", "chain": "eth", "amount": 3.0, "price": 3000.0}])

    snap = DeBankClient(api_key="k", http_client=_client(handler)).wallet_snapshot(_ADDR)
    assert snap is not None
    assert snap["address"] == _ADDR
    assert snap["total_usd_value"] == 9000.0
    assert snap["token_count"] == 1
    assert snap["top_tokens"][0]["symbol"] == "ETH"


def test_invalid_address_degrades() -> None:
    client = DeBankClient(api_key="k")
    assert client.wallet_snapshot("0xbad") is None
    assert client.get_total_balance("0xbad") is None
    assert client.get_tokens("0xbad") == []


def test_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEBANK_API_KEY", "env-key")
    assert DeBankClient().is_configured() is True
