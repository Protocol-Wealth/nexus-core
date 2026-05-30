# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the keyless Jupiter v3 Solana price client (hermetic)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.onchain import JupiterClient, is_solana_mint

_SOL = "So11111111111111111111111111111111111111112"
_USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_is_solana_mint() -> None:
    assert is_solana_mint(_SOL)
    assert is_solana_mint(_USDC)
    assert not is_solana_mint("0x123")  # too short / non-base58
    assert not is_solana_mint("0" * 40)  # '0' not in base58


def test_get_prices_parses_v3_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/price/v3")
        assert request.url.params["ids"] == f"{_SOL},{_USDC}"
        assert request.headers.get("User-Agent", "").startswith("nexus-core")
        return httpx.Response(
            200,
            json={
                _SOL: {"usdPrice": 82.23, "decimals": 9, "priceChange24h": 0.05, "liquidity": 6.8e8},
                _USDC: {"usdPrice": 0.9995, "decimals": 6, "priceChange24h": 0.0, "liquidity": 1e9},
            },
        )

    prices = JupiterClient(http_client=_client(handler)).get_prices([_SOL, _USDC])
    assert prices[_SOL].usd_price == pytest.approx(82.23)
    assert prices[_SOL].decimals == 9
    assert prices[_SOL].price_change_24h_pct == pytest.approx(0.05)
    assert prices[_SOL].liquidity_usd == pytest.approx(6.8e8)
    assert prices[_USDC].usd_price == pytest.approx(0.9995)


def test_get_price_single() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={_SOL: {"usdPrice": 80.0, "decimals": 9}})

    p = JupiterClient(http_client=_client(handler)).get_price(_SOL)
    assert p is not None
    assert p.usd_price == 80.0
    assert p.price_change_24h_pct is None  # absent → None


def test_invalid_mint_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request for an invalid mint")

    client = JupiterClient(http_client=_client(handler))
    assert client.get_prices(["0xbad"]) == {}
    assert client.get_price("notamint") is None


def test_zero_or_missing_price_omitted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={_SOL: {"usdPrice": 0}, _USDC: {"decimals": 6}})

    prices = JupiterClient(http_client=_client(handler)).get_prices([_SOL, _USDC])
    assert prices == {}  # zero price + missing price both dropped


def test_http_error_degrades() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="err")

    assert JupiterClient(http_client=_client(handler)).get_prices([_SOL]) == {}
