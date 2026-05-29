# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the vaults.fyi DeFi vault-discovery client.

Hermetic — every request is served by an ``httpx.MockTransport`` handler.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.onchain import VaultsFyiClient, chain_alias, is_supported_chain


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


_SAMPLE = {
    "data": [
        {
            "name": "Steakhouse USDC",
            "address": "0xabc",
            "network": "base",
            "protocol": {"name": "Morpho"},
            "apy": {"current": 0.085},
            "tvl": {"usd": 12_000_000.0},
            "asset": {"symbol": "USDC"},
            "id": "base-0xabc",
        },
        {
            "name": "Small Vault",
            "address": "0xdef",
            "network": "base",
            "protocol": {"name": "Spark"},
            "apy": {"current": 0.04},
            "tvl": {"usd": 3_000_000.0},
            "asset": {"symbol": "DAI"},
            "id": "base-0xdef",
        },
    ]
}


def test_chain_alias_and_support() -> None:
    assert chain_alias("ethereum") == "mainnet"
    assert chain_alias("BASE") == "base"
    assert is_supported_chain("ethereum")  # aliases to mainnet
    assert is_supported_chain("base")
    assert not is_supported_chain("solana")


def test_supported_chains_exposed() -> None:
    chains = VaultsFyiClient.supported_chains()
    assert "mainnet" in chains and "base" in chains
    assert "solana" not in chains


def test_not_configured_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAULTSFYI_API_KEY", raising=False)
    client = VaultsFyiClient(api_key=None)
    assert client.is_configured() is False
    assert client.search_vaults("base") == []


def test_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULTSFYI_API_KEY", "env-key")
    assert VaultsFyiClient().is_configured() is True


def test_search_vaults_params_and_parse() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-api-key") == "k"
        assert request.url.path == "/v2/detailed-vaults"
        params = request.url.params
        assert params["allowedNetworks"] == "mainnet"  # ethereum → mainnet
        assert params["minTvl"] == "5000000"
        assert params["perPage"] == "10"
        assert params["onlyTransactional"] == "true"
        return httpx.Response(200, json=_SAMPLE)

    vaults = VaultsFyiClient(api_key="k", http_client=_client(handler)).search_vaults(
        "ethereum", min_tvl_usd=5_000_000, per_page=10
    )
    assert [v.name for v in vaults] == ["Steakhouse USDC", "Small Vault"]  # sorted by TVL desc
    top = vaults[0]
    assert top.protocol == "Morpho"
    assert top.apy == pytest.approx(0.085)
    assert top.tvl_usd == pytest.approx(12_000_000.0)
    assert top.underlying_asset_symbol == "USDC"
    assert top.vault_id == "base-0xabc"


def test_per_page_clamped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["perPage"] == "200"  # clamped from 999
        return httpx.Response(200, json={"data": []})

    VaultsFyiClient(api_key="k", http_client=_client(handler)).search_vaults("base", per_page=999)


def test_unsupported_chain_returns_empty() -> None:
    # No HTTP call should be made for an unsupported chain.
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("should not issue a request for an unsupported chain")

    assert VaultsFyiClient(api_key="k", http_client=_client(handler)).search_vaults("solana") == []


def test_missing_fields_degrade_to_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"name": "Bare", "address": "0x1", "network": "base", "id": "x"}]}
        )

    vaults = VaultsFyiClient(api_key="k", http_client=_client(handler)).search_vaults("base")
    assert len(vaults) == 1
    v = vaults[0]
    assert v.protocol is None and v.apy is None and v.tvl_usd is None
    assert v.underlying_asset_symbol is None


def test_upstream_error_degrades_to_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    assert VaultsFyiClient(api_key="k", http_client=_client(handler)).search_vaults("base") == []


def test_non_dict_payload_degrades() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "a", "dict"])

    assert VaultsFyiClient(api_key="k", http_client=_client(handler)).search_vaults("base") == []
