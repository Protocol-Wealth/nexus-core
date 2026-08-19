# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the Tatum multi-chain native-balance client.

Hermetic — every JSON-RPC request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.onchain import TatumClient, is_solana_address

_EVM = "0x" + "a" * 40
_TRANSFER_TOPIC = "0x" + "d" * 64
_SOL = "GsbwXfJraMomNxBcjK7xK2xQx5MQgQ3rEXrx2nKw1234"  # plausible base58


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_is_solana_address() -> None:
    assert is_solana_address(_SOL)
    assert not is_solana_address("0x123")  # too short
    assert not is_solana_address("0" * 40)  # contains '0' (not base58)
    assert not is_solana_address("I" * 40)  # contains 'I' (not base58)


def test_supported_chains_and_info() -> None:
    chains = TatumClient.supported_chains()
    assert "ethereum" in chains
    assert "solana" in chains
    assert TatumClient.chain_info("ethereum") == {
        "chain": "ethereum",
        "family": "evm",
        "symbol": "ETH",
    }
    assert TatumClient.chain_info("solana")["family"] == "solana"
    assert TatumClient.chain_info("dogecoin") is None  # not in the curated set


def test_not_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TATUM_API_KEY", raising=False)
    client = TatumClient(api_key=None)
    assert client.is_configured() is False
    assert client.native_balance("ethereum", _EVM) is None


def test_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TATUM_API_KEY", "env-key")
    assert TatumClient().is_configured() is True


def test_evm_native_balance_uses_apikey_and_gateway() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-api-key") == "k"
        assert request.url.host == "ethereum-mainnet.gateway.tatum.io"
        body = request.read().decode()
        assert "eth_getBalance" in body
        assert _EVM in body
        # 1.5 ETH = 1.5e18 wei = 0x14d1120d7b160000
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x14d1120d7b160000"})

    bal = TatumClient(api_key="k", http_client=_client(handler)).native_balance("ethereum", _EVM)
    assert bal is not None
    assert bal.symbol == "ETH"
    assert bal.raw == 1_500_000_000_000_000_000
    assert bal.balance == pytest.approx(1.5)


def test_solana_balance_unwraps_value() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "solana-mainnet.gateway.tatum.io"
        assert "getBalance" in request.read().decode()
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"context": {"slot": 1}, "value": 2_500_000_000},
            },
        )

    bal = TatumClient(api_key="k", http_client=_client(handler)).native_balance("solana", _SOL)
    assert bal is not None
    assert bal.symbol == "SOL"
    assert bal.raw == 2_500_000_000
    assert bal.balance == pytest.approx(2.5)


def test_invalid_address_per_family_degrades() -> None:
    client = TatumClient(api_key="k")
    assert client.native_balance("ethereum", "0xbad") is None  # bad EVM
    assert client.native_balance("solana", "0x" + "a" * 40) is None  # EVM addr on Solana
    assert client.native_balance("not-a-chain", _EVM) is None  # unknown chain


def test_evm_bad_hex_result_degrades() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "not-hex"})

    assert (
        TatumClient(api_key="k", http_client=_client(handler)).native_balance("ethereum", _EVM)
        is None
    )


def test_rpc_error_payload_degrades() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000}})

    assert (
        TatumClient(api_key="k", http_client=_client(handler)).native_balance("ethereum", _EVM)
        is None
    )


def test_multi_chain_native_filters_zero_and_non_evm() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        # Only base reports a non-zero balance; the rest are zero.
        if host == "base-mainnet.gateway.tatum.io":
            return httpx.Response(200, json={"result": "0xde0b6b3a7640000"})  # 1 ETH
        return httpx.Response(200, json={"result": "0x0"})

    balances = TatumClient(api_key="k", http_client=_client(handler)).multi_chain_native(_EVM)
    assert set(balances) == {"base"}
    assert balances["base"].balance == pytest.approx(1.0)


def test_multi_chain_native_rejects_non_evm_address() -> None:
    assert TatumClient(api_key="k").multi_chain_native(_SOL) == {}


def test_nfpm_tokens_owed_decodes() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "ethereum-mainnet.gateway.tatum.io"
        body = request.read().decode()
        assert "eth_call" in body and "0x99fbab88" in body
        # positions() returns 12 words; tokensOwed0/1 are words[10], [11].
        words = ["00" * 32] * 10 + [f"{1_500_000:064x}", f"{2 * 10**18:064x}"]
        return httpx.Response(200, json={"result": "0x" + "".join(words)})

    owed = TatumClient(api_key="k", http_client=_client(handler)).nfpm_tokens_owed(
        "ethereum", 123, decimals0=6, decimals1=18
    )
    assert owed is not None
    assert owed[0] == pytest.approx(1.5)  # 1_500_000 / 10**6
    assert owed[1] == pytest.approx(2.0)  # 2e18 / 10**18


def test_nfpm_tokens_owed_unsupported_chain() -> None:
    assert TatumClient(api_key="k").nfpm_tokens_owed("solana", 1) is None


def test_nfpm_tokens_owed_short_result_degrades() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"result": "0x" + "00" * 32})  # only 1 word

    assert (
        TatumClient(api_key="k", http_client=_client(handler)).nfpm_tokens_owed("ethereum", 1)
        is None
    )


def test_get_logs_builds_the_filter_and_returns_rows() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read().decode())
        assert body["method"] == "eth_getLogs"
        (log_filter,) = body["params"]
        assert log_filter == {
            "fromBlock": "0x12d687",
            "toBlock": "latest",
            "address": _EVM,
            "topics": [_TRANSFER_TOPIC],
        }
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": [{"address": _EVM, "data": "0x"}]},
        )

    rows = TatumClient(api_key="k", http_client=_client(handler)).get_logs(
        "ethereum",
        from_block=1_234_567,
        to_block="latest",
        address=_EVM,
        topics=[_TRANSFER_TOPIC],
    )
    assert rows == [{"address": _EVM, "data": "0x"}]


def test_get_logs_omits_optional_filter_keys() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        (log_filter,) = json.loads(request.read().decode())["params"]
        assert log_filter == {"fromBlock": "0x1", "toBlock": "0x2"}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": []})

    rows = TatumClient(api_key="k", http_client=_client(handler)).get_logs(
        "ethereum", from_block=1, to_block=2
    )
    assert rows == []


def test_get_logs_rejects_non_evm_chains() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request should be issued for a non-EVM chain")

    assert (
        TatumClient(api_key="k", http_client=_client(handler)).get_logs(
            "solana", from_block=1, to_block=2
        )
        is None
    )


def test_get_logs_returns_none_when_the_result_is_not_a_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xdeadbeef"})

    assert (
        TatumClient(api_key="k", http_client=_client(handler)).get_logs(
            "ethereum", from_block=1, to_block=2
        )
        is None
    )
