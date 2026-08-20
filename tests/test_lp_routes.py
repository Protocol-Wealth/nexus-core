# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Integration tests for the /api/lp router (real clients + MockTransport)."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.lp import build_lp_router
from nexus_core.data.market import CoinGeckoMarketData
from nexus_core.data.onchain import MerklClient, SlipstreamClient, TatumClient, TheGraphClient

_POSITION_DATA = {
    "data": {
        "position": {
            "id": "123",
            "owner": "0xowner",
            "liquidity": "1000000000000000000",
            "depositedToken0": "1000",
            "depositedToken1": "0.5",
            "tickLower": {"tickIdx": "100"},
            "tickUpper": {"tickIdx": "300"},
            "pool": {
                "id": "0xpool",
                "sqrtPrice": "793073905181059963158917209204",  # ~tick 200
                "tick": "200",
                "feeTier": "3000",
                "liquidity": "1000000000000000000",
                "totalValueLockedUSD": "10000000",
                "volumeUSD": "365000000",
                "token0": {"id": "0xt0", "symbol": "USDC", "decimals": "6"},
                "token1": {"id": "0xt1", "symbol": "WETH", "decimals": "18"},
                "poolDayData": [{"volumeUSD": "1000000"}],
            },
        }
    }
}


def _mk(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _graph_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.read())
    if "PositionsByOwner" in body.get("query", ""):
        # The by-owner query returns a list under `positions`.
        return httpx.Response(
            200, json={"data": {"positions": [_POSITION_DATA["data"]["position"]]}}
        )
    return httpx.Response(200, json=_POSITION_DATA)


def _tatum_handler(request: httpx.Request) -> httpx.Response:
    words = ["00" * 32] * 10 + [f"{1_000_000:064x}", f"{10**15:064x}"]
    return httpx.Response(200, json={"result": "0x" + "".join(words)})


def _merkl_handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json=[{"identifier": "0xpool", "name": "R", "chainId": 1, "apr": 4.0, "status": "LIVE"}],
    )


# CoinGecko OHLC for the benchmark series: close 2000 → 3000 (+50%).
_OHLC = [[1_000_000, 2000, 2100, 1900, 2000], [2_000_000, 2900, 3100, 2800, 3000]]


def _cg() -> CoinGeckoMarketData:
    return CoinGeckoMarketData(http_client=_mk(lambda _req: httpx.Response(200, json=_OHLC)))


_WETH = "0x4200000000000000000000000000000000000006"
_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
_M = (1 << 256) - 1


def _slip_handler(request: httpx.Request) -> httpx.Response:
    """Tatum eth_call mock for the Slipstream on-chain sequence (WETH/USDC, tick 0)."""
    p = json.loads(request.read())["params"][0]
    to, sel = p["to"].lower(), p["data"][:10]

    def wi(v: int) -> str:
        return f"{v & _M:064x}"

    if sel == "0x99fbab88":  # positions
        words = (
            ["00" * 32, "00" * 32, _WETH[2:].rjust(64, "0"), _USDC[2:].rjust(64, "0"), wi(100)]
            + [wi(-1000), wi(1000), wi(10**18), "00" * 32, "00" * 32, wi(10**17), wi(5 * 10**6)]
        )
        return httpx.Response(200, json={"result": "0x" + "".join(words)})
    if sel == "0x28af8d0b":  # getPool
        return httpx.Response(200, json={"result": "0x" + "aa".rjust(64, "0")})
    if sel == "0x3850c7bd":  # slot0
        return httpx.Response(200, json={"result": "0x" + wi(2**96) + wi(0)})
    if sel == "0x313ce567":  # decimals
        return httpx.Response(200, json={"result": wi(18 if to == _WETH.lower() else 6)})
    if sel == "0x95d89b41":  # symbol → ABI string
        sym = ("WETH" if to == _WETH.lower() else "USDC").encode()
        return httpx.Response(
            200, json={"result": "0x" + wi(32) + wi(len(sym)) + sym.hex().ljust(64, "0")}
        )
    return httpx.Response(200, json={"result": "0x"})


def _slip() -> SlipstreamClient:
    return SlipstreamClient(TatumClient(api_key="k", http_client=_mk(_slip_handler)))


def _app(*, graph_key: str | None = "k") -> FastAPI:
    app = FastAPI()
    app.include_router(
        build_lp_router(
            thegraph=TheGraphClient(api_key=graph_key, http_client=_mk(_graph_handler)),
            tatum=TatumClient(api_key="k", http_client=_mk(_tatum_handler)),
            merkl=MerklClient(http_client=_mk(_merkl_handler)),
            coingecko=_cg(),
            slipstream=_slip(),
        )
    )
    return app


def test_lp_chains() -> None:
    r = TestClient(_app()).get("/api/lp/chains")
    assert r.status_code == 200
    assert {"chain": "ethereum", "protocol": "uniswap", "version": "v3"} in r.json()["chains"]


def test_lp_analytics_fields() -> None:
    client = TestClient(_app())
    r = client.get("/api/lp/uniswap-v3/ethereum/123/analytics?price_token0_usd=1&price_token1_usd=2000")
    assert r.status_code == 200
    body = r.json()
    assert body["token_id"] == "123"
    assert body["in_range"] is True
    assert body["reward_apr"] == 4.0  # from Merkl
    assert body["uncollected_fees_source"] == "rpc_tokens_owed"
    # uncollected: 1_000_000/1e6 USDC = 1.0 USDC; 1e15/1e18 WETH = 0.001 WETH
    assert body["uncollected_fees0"] == 1.0
    assert body["uncollected_fees1"] == 0.001
    assert body["total_apr_estimate"] >= body["reward_apr"]
    assert "disclaimer" in body


def test_lp_bad_chain_400() -> None:
    r = TestClient(_app()).get("/api/lp/uniswap-v3/solana/1/analytics?price_token0_usd=1&price_token1_usd=1")
    assert r.status_code == 400


# Synthetic, documentation-only address. This repository is PUBLIC and these
# tests run entirely against MockTransport, so a fixture owner needs only to be
# FORMAT-valid — any 0x + 40 hex will do, and `test_lp_positions_bad_owner_400`
# below covers the invalid-format case. Never put a real wallet address in a
# fixture: it is an identifier, it outlives the test in git history, and no
# assertion here can tell the difference.
_OWNER = "0x00000000000000000000000000000000decafbad"


def test_lp_positions_by_owner() -> None:
    r = TestClient(_app()).get(f"/api/lp/uniswap-v3/ethereum/positions?owner={_OWNER}")
    assert r.status_code == 200
    body = r.json()
    assert body["owner"] == _OWNER
    assert body["count"] == 1
    pos = body["positions"][0]
    assert pos["token_id"] == "123"
    assert pos["in_range"] is True  # tick 200 in [100, 300]
    assert pos["fee_tier"] == 3000
    assert pos["token0"]["symbol"] == "USDC"
    assert pos["token1"]["decimals"] == 18
    # token amounts are present (price-independent) + uncollected fees from RPC
    assert pos["amount0"] >= 0
    assert pos["amount1"] >= 0
    assert pos["uncollected_fees"]["source"] == "rpc_tokens_owed"
    assert pos["uncollected_fees"]["token0"] == 1.0  # 1_000_000 / 1e6
    assert "disclaimer" in body


def test_lp_positions_bad_owner_400() -> None:
    r = TestClient(_app()).get("/api/lp/uniswap-v3/ethereum/positions?owner=not-an-address")
    assert r.status_code == 400


def test_lp_positions_bad_chain_400() -> None:
    r = TestClient(_app()).get(f"/api/lp/uniswap-v3/solana/positions?owner={_OWNER}")
    assert r.status_code == 400


def test_lp_unconfigured_503() -> None:
    r = TestClient(_app(graph_key=None)).get(
        "/api/lp/uniswap-v3/ethereum/1/analytics?price_token0_usd=1&price_token1_usd=1"
    )
    assert r.status_code == 503


def test_lp_missing_price_params_422() -> None:
    r = TestClient(_app()).get("/api/lp/uniswap-v3/ethereum/123/analytics")
    assert r.status_code == 422  # required query params


def test_lp_missing_position_404() -> None:
    app = FastAPI()
    app.include_router(
        build_lp_router(
            thegraph=TheGraphClient(
                api_key="k",
                http_client=_mk(lambda req: httpx.Response(200, json={"data": {"position": None}})),
            ),
            tatum=TatumClient(api_key="k", http_client=_mk(_tatum_handler)),
            merkl=MerklClient(http_client=_mk(_merkl_handler)),
            coingecko=_cg(),
            slipstream=_slip(),
        )
    )
    r = TestClient(app).get("/api/lp/uniswap-v3/ethereum/999/analytics?price_token0_usd=1&price_token1_usd=1")
    assert r.status_code == 404


def test_lp_aerodrome_onchain() -> None:
    client = TestClient(_app())
    r = client.get("/api/lp/aerodrome/123/analytics?price_token0_usd=3000&price_token1_usd=1")
    assert r.status_code == 200
    body = r.json()
    assert body["protocol"] == "aerodrome-slipstream"
    assert body["data_mode"] == "onchain_rpc"
    assert body["chain"] == "base"
    assert body["in_range"] is True  # tick 0 in [-1000, 1000]
    assert body["token0_symbol"] == "WETH" and body["token1_symbol"] == "USDC"
    # uncollected: 0.1 WETH * $3000 + 5 USDC * $1 = $305
    assert body["uncollected_fees_usd"] == pytest.approx(305.0)
    # on-chain-only: IL null, fee/reward APR 0
    assert body["impermanent_loss_pct"] is None
    assert body["fee_apr_estimate"] == 0.0 and body["reward_apr"] == 0.0


def test_lp_aerodrome_unconfigured_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TATUM_API_KEY", raising=False)
    app = FastAPI()
    app.include_router(
        build_lp_router(
            thegraph=TheGraphClient(api_key="k", http_client=_mk(_graph_handler)),
            tatum=TatumClient(api_key="k", http_client=_mk(_tatum_handler)),
            merkl=MerklClient(http_client=_mk(_merkl_handler)),
            coingecko=_cg(),
            slipstream=SlipstreamClient(TatumClient(api_key=None)),
        )
    )
    r = TestClient(app).get("/api/lp/aerodrome/1/analytics?price_token0_usd=1&price_token1_usd=1")
    assert r.status_code == 503


def test_lp_vs_benchmark() -> None:
    client = TestClient(_app())
    r = client.get(
        "/api/lp/uniswap-v3/ethereum/123/vs-benchmark?price_token0_usd=1&price_token1_usd=2000&days=90"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["position"]["token_id"] == "123"
    assert body["position"]["reward_apr"] == 4.0
    assert body["position"]["uncollected_fees_source"] == "rpc_tokens_owed"
    # Benchmarks from the OHLC (+50% ETH): ETH ~+50%, 50/50 ETH-USDC ~+25%.
    returns = body["benchmarks"]["returns_pct"]
    assert returns["ETH"] == 50.0
    assert returns["ETH-USDC 50/50"] == 25.0
    comp = body["comparison"]
    assert comp["position_total_apr_estimate"] == body["position"]["total_apr_estimate"]
    assert "note" in comp


# --- Wire-shape guards for the typed response models -------------------------
#
# Each of these fails if a model change alters the bytes on the wire. They are
# written against the raw response TEXT where the hazard is a serialization
# format (quoted vs unquoted, int vs float, null vs absent) — parsing the JSON
# first would hide exactly the difference being asserted.

_ANALYTICS_KEYS = [
    "token_id", "chain", "pool", "token0_symbol", "token1_symbol", "fee_tier",
    "in_range", "current_tick", "tick_lower", "tick_upper", "liquidity",
    "amount0", "amount1", "position_value_usd",
    "uncollected_fees0", "uncollected_fees1", "uncollected_fees_usd",
    "fee_apr_estimate", "reward_apr", "total_apr_estimate",
    "impermanent_loss_usd", "impermanent_loss_pct",
    "range_width_pct", "current_price", "price_token0_usd", "price_token1_usd",
]


def test_lp_liquidity_stays_a_quoted_string() -> None:
    """Uniswap V3 liquidity is a uint128 and must not be unquoted into a number.

    A typical value (1e18) is two orders of magnitude past JSON's safely
    representable integer range, so every client that parses with a double —
    which is every JavaScript client — would silently round it. Declaring
    ``liquidity: int`` on the response model is the mistake this catches.
    """
    assert 1_000_000_000_000_000_000 > 2**53  # the reason it is quoted at all
    client = TestClient(_app())
    for url in (
        f"/api/lp/uniswap-v3/ethereum/positions?owner={_OWNER}",
        "/api/lp/uniswap-v3/ethereum/123/analytics?price_token0_usd=1&price_token1_usd=2000",
    ):
        text = client.get(url).text
        assert '"liquidity":"1000000000000000000"' in text
        assert '"liquidity":1000000000000000000' not in text


def test_lp_aerodrome_reports_null_il_rather_than_dropping_the_key() -> None:
    """On-chain-only mode has no deposit baseline, so IL is a documented null.

    ``response_model_exclude_none`` would drop both keys and turn a stated "not
    available" into a missing field — a breaking change for any client reading
    ``body["impermanent_loss_pct"]``.
    """
    r = TestClient(_app()).get(
        "/api/lp/aerodrome/123/analytics?price_token0_usd=3000&price_token1_usd=1"
    )
    assert '"impermanent_loss_usd":null' in r.text
    assert '"impermanent_loss_pct":null' in r.text
    body = r.json()
    assert "impermanent_loss_usd" in body and "impermanent_loss_pct" in body


def test_lp_benchmark_returns_keep_every_composition_key() -> None:
    """``returns_pct`` is keyed by benchmark name, so it stays a free-form map.

    The names carry spaces and slashes ("ETH-USDC 60/40"). A fixed model would
    drop any composition it did not declare, silently and without an error.
    """
    body = TestClient(_app()).get(
        "/api/lp/uniswap-v3/ethereum/123/vs-benchmark"
        "?price_token0_usd=1&price_token1_usd=2000&days=90"
    ).json()
    expected = {"BTC", "ETH", "SOL", "ETH-USDC 50/50", "ETH-BTC 50/50",
                "ETH-USDC 60/40", "ETH-USDC 70/30"}
    assert set(body["benchmarks"]["returns_pct"]) == expected
    assert set(body["comparison"]["benchmark_returns_pct"]) == expected


def test_lp_integer_fields_do_not_become_floats() -> None:
    """Ticks, fee tiers, decimals, counts and the window are ints on the wire.

    Asserted with ``type(v) is int``, not a substring of the response text: the
    text ``"fee_tier":3000`` is a prefix of ``"fee_tier":3000.0``, so a literal
    ``in`` check passes for exactly the mutation it claims to catch. Python's
    JSON parser does distinguish the two, so the type is the honest assertion.
    """
    client = TestClient(_app())

    def assert_int(value: object, label: str) -> None:
        # bool is a subclass of int; exclude it so a True never reads as 1
        assert type(value) is int, f"{label} serialized as {type(value).__name__}: {value!r}"

    positions = client.get(f"/api/lp/uniswap-v3/ethereum/positions?owner={_OWNER}").json()
    assert_int(positions["count"], "count")
    row = positions["positions"][0]
    for key in ("fee_tier", "tick_lower", "tick_upper", "current_tick"):
        assert_int(row[key], f"positions[0].{key}")
    for side in ("token0", "token1"):
        assert_int(row[side]["decimals"], f"positions[0].{side}.decimals")

    # zero and negative are where an int/float slip shows up first
    aero = client.get(
        "/api/lp/aerodrome/123/analytics?price_token0_usd=3000&price_token1_usd=1"
    ).json()
    assert aero["fee_tier"] == 0 and aero["current_tick"] == 0 and aero["tick_lower"] == -1000
    for key in ("fee_tier", "current_tick", "tick_lower", "tick_upper"):
        assert_int(aero[key], f"aerodrome.{key}")

    bench = client.get(
        "/api/lp/uniswap-v3/ethereum/123/vs-benchmark"
        "?price_token0_usd=1&price_token1_usd=2000&days=90"
    ).json()
    assert_int(bench["benchmarks"]["days"], "benchmarks.days")


def test_lp_float_fields_do_not_become_ints() -> None:
    """The mirror: a zero-valued float must not render as a bare ``0``."""
    text = TestClient(_app()).get(
        "/api/lp/uniswap-v3/ethereum/123/analytics?price_token0_usd=1&price_token1_usd=2000"
    ).text
    assert '"amount0":0.0' in text
    assert '"amount0":0,' not in text


def test_lp_response_key_order_is_unchanged() -> None:
    """Key order is part of the wire output, and models can reorder it."""
    client = TestClient(_app())
    analytics = client.get(
        "/api/lp/uniswap-v3/ethereum/123/analytics?price_token0_usd=1&price_token1_usd=2000"
    ).json()
    assert list(analytics) == [*_ANALYTICS_KEYS, "uncollected_fees_source", "disclaimer"]

    aero = client.get(
        "/api/lp/aerodrome/123/analytics?price_token0_usd=3000&price_token1_usd=1"
    ).json()
    assert list(aero) == [*_ANALYTICS_KEYS, "protocol", "data_mode", "note", "disclaimer"]

    bench = client.get(
        "/api/lp/uniswap-v3/ethereum/123/vs-benchmark"
        "?price_token0_usd=1&price_token1_usd=2000&days=90"
    ).json()
    assert list(bench) == ["position", "benchmarks", "comparison", "disclaimer"]
    assert list(bench["position"]) == [*_ANALYTICS_KEYS, "uncollected_fees_source"]
    assert list(bench["benchmarks"]) == ["days", "returns_pct"]
    assert list(bench["comparison"]) == [
        "position_il_pct", "position_total_apr_estimate", "benchmark_returns_pct", "note",
    ]

    positions = client.get(f"/api/lp/uniswap-v3/ethereum/positions?owner={_OWNER}").json()
    assert list(positions) == ["chain", "owner", "count", "positions", "note", "disclaimer"]
    assert list(positions["positions"][0]) == [
        "token_id", "chain", "pool_address", "fee_tier", "token0", "token1",
        "tick_lower", "tick_upper", "current_tick", "in_range", "liquidity",
        "amount0", "amount1", "uncollected_fees",
    ]
    assert list(positions["positions"][0]["token0"]) == ["address", "symbol", "decimals"]
    assert list(positions["positions"][0]["uncollected_fees"]) == ["token0", "token1", "source"]


def test_lp_model_mirrors_the_dataclass_field_for_field() -> None:
    """A field added to ``PositionAnalytics`` must be added to the model too.

    The routes spread ``asdict(result)`` into a model configured
    ``extra="forbid"``, so a new dataclass field raises at request time. This
    test moves that failure into CI, where it names the missing field instead of
    surfacing as a 500 in production.
    """
    from dataclasses import fields

    from nexus_core.app.lp import PositionAnalyticsBody
    from nexus_core.engine.lp import PositionAnalytics

    assert [f.name for f in fields(PositionAnalytics)] == list(
        PositionAnalyticsBody.model_fields
    ), "PositionAnalyticsBody must mirror PositionAnalytics in name AND order"
