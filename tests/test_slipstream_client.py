# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the Aerodrome Slipstream on-chain RPC reader (hermetic).

A single ``httpx.MockTransport`` answers the Tatum ``eth_call`` JSON-RPC POSTs
by inspecting the selector + target, returning ABI-encoded results.
"""

from __future__ import annotations

import json

import httpx
import pytest

from nexus_core.data.onchain import SlipstreamClient, TatumClient

_WETH = "0x4200000000000000000000000000000000000006"
_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
_POOL = "0x00000000000000000000000000000000000000aa"
_MASK = (1 << 256) - 1


def _w_addr(a: str) -> str:
    return a[2:].rjust(64, "0")


def _w_int(v: int) -> str:
    return f"{v & _MASK:064x}"


def _handler(request: httpx.Request) -> httpx.Response:
    params = json.loads(request.read())["params"][0]
    to, data = params["to"].lower(), params["data"]
    sel = data[:10]
    if sel == "0x99fbab88":  # positions(uint256)
        words = (
            ["00" * 32, "00" * 32, _w_addr(_WETH), _w_addr(_USDC), _w_int(100)]
            + [_w_int(-1000), _w_int(1000), _w_int(10**18), "00" * 32, "00" * 32]
            + [_w_int(10**17), _w_int(5 * 10**6)]  # tokensOwed0 (0.1 WETH), tokensOwed1 (5 USDC)
        )
        return httpx.Response(200, json={"result": "0x" + "".join(words)})
    if sel == "0x28af8d0b":  # getPool(address,address,int24)
        return httpx.Response(200, json={"result": "0x" + _w_addr(_POOL)})
    if sel == "0x3850c7bd":  # slot0() → sqrtPriceX96=Q96 (tick 0), tick=0
        return httpx.Response(200, json={"result": "0x" + _w_int(2**96) + _w_int(0)})
    if sel == "0x313ce567":  # decimals()
        return httpx.Response(200, json={"result": _w_int(18 if to == _WETH.lower() else 6)})
    if sel == "0x95d89b41":  # symbol() → ABI string
        sym = ("WETH" if to == _WETH.lower() else "USDC").encode()
        return httpx.Response(
            200, json={"result": "0x" + _w_int(32) + _w_int(len(sym)) + sym.hex().ljust(64, "0")}
        )
    return httpx.Response(200, json={"result": "0x"})


def _slipstream(handler=_handler) -> SlipstreamClient:  # type: ignore[no-untyped-def]
    tatum = TatumClient(api_key="k", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return SlipstreamClient(tatum)


def test_fetch_position_decodes_full_path() -> None:
    res = _slipstream().fetch_position("123")
    assert res is not None
    pos, owed0, owed1 = res
    assert pos.chain == "base"
    assert pos.token0_symbol == "WETH" and pos.token1_symbol == "USDC"
    assert pos.decimals0 == 18 and pos.decimals1 == 6
    assert pos.tick_lower == -1000 and pos.tick_upper == 1000 and pos.current_tick == 0
    assert pos.liquidity == 10**18
    assert pos.pool_address.lower() == _POOL.lower()
    assert pos.sqrt_price_x96 == 2**96
    # on-chain-only: no deposit/TVL data
    assert pos.deposited0 == 0.0 and pos.deposited1 == 0.0 and pos.pool_tvl_usd == 0.0
    # uncollected fees decoded from tokensOwed0/1
    assert owed0 == pytest.approx(0.1)  # 1e17 / 1e18
    assert owed1 == pytest.approx(5.0)  # 5e6 / 1e6


def test_not_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TATUM_API_KEY", raising=False)
    assert SlipstreamClient(TatumClient(api_key=None)).fetch_position("1") is None


def test_bad_token_id_returns_none() -> None:
    assert _slipstream().fetch_position("not-a-number") is None


def test_missing_pool_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        sel = json.loads(request.read())["params"][0]["data"][:10]
        if sel == "0x99fbab88":
            return _handler(request)  # valid position
        if sel == "0x28af8d0b":
            return httpx.Response(200, json={"result": "0x" + _w_int(0)})  # getPool → 0 address
        return httpx.Response(200, json={"result": "0x"})

    assert _slipstream(handler).fetch_position("123") is None
