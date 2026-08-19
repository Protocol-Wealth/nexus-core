# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the DeFi vault-discovery REST surface."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from nexus_core.app.vaults import build_vaults_router
from nexus_core.data.onchain.vaultsfyi import Vault, VaultsFyiClient

_FULL = Vault(
    name="Steakhouse USDC",
    address="0xaaa",
    chain="base",
    protocol="morpho",
    apy=0.0812,
    apy_breakdown={"1day": 0.08, "7day": 0.0812, "30day": 0.079},
    tvl_usd=12_500_000.0,
    underlying_asset_symbol="USDC",
    curator="Steakhouse",
    vault_url="https://example.invalid/vault",
    vault_id="v1",
)

# Every nullable field exercised at once — the shape a vault takes when the
# provider knows almost nothing about it.
_SPARSE = Vault(
    name="Unknown",
    address="0xbbb",
    chain="base",
    protocol=None,
    apy=None,
    apy_breakdown={},
    tvl_usd=None,
    underlying_asset_symbol=None,
    curator=None,
    vault_url=None,
    vault_id="v2",
)


class _FakeVaultsFyi:
    def __init__(self, *, configured: bool = True, vaults: list[Vault] | None = None) -> None:
        self._configured = configured
        self._vaults = vaults if vaults is not None else [_FULL, _SPARSE]

    def is_configured(self) -> bool:
        return self._configured

    def search_vaults(self, chain: str, *, min_tvl_usd: int = 0, per_page: int = 50) -> list[Vault]:
        return self._vaults

    @staticmethod
    def supported_chains() -> tuple[str, ...]:
        return VaultsFyiClient.supported_chains()


def _client(vaultsfyi: _FakeVaultsFyi) -> TestClient:
    app = FastAPI()
    app.include_router(build_vaults_router(vaultsfyi=vaultsfyi))  # type: ignore[arg-type]
    return TestClient(app)


def test_search_returns_vaults_for_a_supported_chain() -> None:
    body = _client(_FakeVaultsFyi()).get("/api/vaults?chain=base").json()
    assert body["chain"] == "base"
    assert body["vault_count"] == 2
    assert "not investment, tax, legal, or financial advice" in body["disclaimer"].lower()


def test_unsupported_chain_400() -> None:
    assert _client(_FakeVaultsFyi()).get("/api/vaults?chain=nowhere").status_code == 400


def test_unconfigured_client_503() -> None:
    r = _client(_FakeVaultsFyi(configured=False)).get("/api/vaults?chain=base")
    assert r.status_code == 503


def test_chains_lists_supported_networks() -> None:
    body = _client(_FakeVaultsFyi()).get("/api/vaults/chains").json()
    assert list(body.keys()) == ["chains", "disclaimer"]
    assert "base" in body["chains"]


def test_absent_metrics_serialize_as_null_and_are_never_omitted() -> None:
    """A vault with no APY or TVL must still carry those keys, valued null.

    Omitting a null is a wire-shape change: a consumer reading ``vault["apy"]``
    gets a KeyError instead of ``None``. This is the specific hazard of typing a
    response whose source dataclass has six nullable fields.
    """
    body = _client(_FakeVaultsFyi(vaults=[_SPARSE])).get("/api/vaults?chain=base").json()
    row = body["vaults"][0]
    for field in (
        "protocol",
        "apy",
        "tvl_usd",
        "underlying_asset_symbol",
        "curator",
        "vault_url",
    ):
        assert field in row, f"{field} was omitted rather than emitted as null"
        assert row[field] is None


def test_vault_field_order_is_unchanged() -> None:
    """Field order is part of the wire output, so it is pinned."""
    body = _client(_FakeVaultsFyi(vaults=[_FULL])).get("/api/vaults?chain=base").json()
    assert list(body.keys()) == ["chain", "vault_count", "vaults", "disclaimer"]
    assert list(body["vaults"][0].keys()) == [
        "name",
        "address",
        "chain",
        "protocol",
        "apy",
        "apy_breakdown",
        "tvl_usd",
        "underlying_asset_symbol",
        "curator",
        "vault_url",
        "vault_id",
    ]


def test_apy_breakdown_keys_are_preserved() -> None:
    """The breakdown windows come from the provider; the model must not narrow them."""
    breakdown = {"1day": 0.01, "7day": 0.02, "30day": 0.03, "90day": 0.04}
    vault = Vault(**{**_FULL.__dict__, "apy_breakdown": breakdown})
    body = _client(_FakeVaultsFyi(vaults=[vault])).get("/api/vaults?chain=base").json()
    assert body["vaults"][0]["apy_breakdown"] == breakdown


def test_an_unmodelled_vault_field_fails_loudly() -> None:
    """Producer drift must not vanish silently from the response."""
    with pytest.raises(ValidationError):
        from nexus_core.app.vaults import VaultRow

        VaultRow(**{**_FULL.__dict__, "newly_added": "surprise"})
