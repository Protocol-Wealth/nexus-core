# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for MCP tool registration in ``build_server``.

Verifies the conditional tool groups (regime / market / macro / DeFi / options)
register when their providers are supplied. Skipped if ``fastmcp`` is absent.
"""

from __future__ import annotations

import asyncio
import time

import pytest

pytest.importorskip("fastmcp")

from nexus_core.data.derivatives import OptionInstrument, OptionTicker  # noqa: E402
from nexus_core.data.providers import PriceBar, Quote  # noqa: E402
from nexus_core.mcp.server import build_server  # noqa: E402


class _RegimeResult:
    regime = "GROWTH"  # EMF code -> generic "expansion"

    def to_dict(self) -> dict[str, str]:
        return {"regime": "GROWTH"}


class _FakeRegime:
    def classify(self) -> _RegimeResult:
        return _RegimeResult()

    def fetch_signals(self) -> _RegimeResult:
        return _RegimeResult()


class _FakeMarket:
    def get_quote(self, symbol: str) -> Quote | None:
        return Quote(symbol=symbol, price=100.0)

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        return [PriceBar(timestamp="2026-01-01", open=1.0, high=1.0, low=1.0, close=1.0)]


class _FakeMacro:
    def get_series(self, series_id: str) -> float | None:
        return 4.3

    def is_configured(self) -> bool:
        return True


class _FakeDeribit:
    _SUPPORTED = ("BTC", "ETH", "SOL", "XRP", "TRX", "AVAX")

    def supported_currencies(self) -> list[str]:
        return list(self._SUPPORTED)

    def settlement_model(self, currency: str) -> str | None:
        cur = currency.upper()
        if cur not in self._SUPPORTED:
            return None
        return "inverse" if cur in ("BTC", "ETH") else "linear_usdc"

    def get_index_price(self, currency: str) -> float | None:
        return 100000.0 if currency.upper() in self._SUPPORTED else None

    def list_option_instruments(self, currency: str) -> list[OptionInstrument]:
        future_ms = int((time.time() + 30 * 86_400) * 1000)
        return [
            OptionInstrument(
                instrument_name=f"{currency}-X-110000-C",
                base_currency=currency,
                option_type="call",
                strike=110000.0,
                expiration_timestamp=future_ms,
                is_active=True,
            )
        ]

    def get_option_ticker(self, instrument_name: str) -> OptionTicker | None:
        return OptionTicker(
            instrument_name=instrument_name, mark_price=0.05, mark_iv=50.0, delta=0.3
        )


class _FakeDefi:
    def get_protocols(self, *, limit: int = 20) -> list:
        return []

    def get_protocol(self, slug: str) -> dict | None:
        return {"name": slug}

    def get_chains(self, *, limit: int = 20) -> list:
        return []


def _tool_names(server: object) -> set[str]:
    return {t.name for t in asyncio.run(server.list_tools())}  # type: ignore[attr-defined]


def test_full_tool_set_registers() -> None:
    server = build_server(
        regime_engine=_FakeRegime(),  # type: ignore[arg-type]
        market=_FakeMarket(),  # type: ignore[arg-type]
        macro=_FakeMacro(),  # type: ignore[arg-type]
        deribit=_FakeDeribit(),  # type: ignore[arg-type]
        defillama=_FakeDefi(),  # type: ignore[arg-type]
    )
    names = _tool_names(server)
    expected = {
        "current_regime",
        "regime_signals",
        "get_quote",
        "get_price_history",
        "get_economic_series",
        "option_price",
        "covered_call",
        "cash_secured_put",
        "collar",
        "equity_collar_screen",
        "collar_book",
        "crypto_option_instruments",
        "crypto_option_ticker",
        "crypto_covered_call",
        "crypto_covered_call_chain",
        "crypto_iv_term_structure",
        "crypto_vol_skew",
        "crypto_protective_put",
        "crypto_collar",
        "crypto_regime_overwrite",
        "crypto_covered_call_ladder",
        "crypto_option_roll",
        "crypto_options_book_mtm",
        "crypto_options_scenario",
        "defi_protocols",
        "defi_protocol",
        "defi_chains",
    }
    assert expected <= names


def test_minimal_server_registers_only_meta_tools() -> None:
    # health + describe are always available (server self-description), even with
    # no providers wired.
    assert _tool_names(build_server()) == {"health", "describe"}


def test_only_supplied_groups_register() -> None:
    # Market only → market + equity-options tools, no regime/macro/defi/crypto.
    names = _tool_names(build_server(market=_FakeMarket()))  # type: ignore[arg-type]
    assert "get_quote" in names
    assert "covered_call" in names
    assert "current_regime" not in names
    assert "defi_protocols" not in names
    assert "crypto_option_instruments" not in names


def test_extra_tools_register() -> None:
    def _planner(body: dict) -> str:  # type: ignore[type-arg]
        return '{"ok": true}'

    server = build_server(extra_tools=[("my_planner", "desc", _planner)])
    assert "my_planner" in _tool_names(server)


_PLANNING_TOOL_IDS = {
    "monte_carlo_decumulation",
    "solve_goal",
    "analyze_goals",
    "project_cash_flow",
    "cashflow_planning_bridge",
    "cash_reserve_analysis",
    "budget_pacing_projection",
    "glide_path",
    "tax_aware_withdrawal",
    "correlation_matrix",
    "capital_market_assumptions",
    "regime_return_generator",
    "roth_conversion",
    "sequence_of_returns_stress",
    "rmd",
    "tax_bracket_headroom",
    "social_security_claiming",
    "regime_conditioned_swr",
    "portfolio_xray",
    "fire",
    "risk_metrics",
    "rebalance",
    "irmaa_headroom",
    "analyze_roth_conversion",
    "sequence_conversions",
    "build_planning_report",
}


def _configured_server() -> object:
    # build_configured_server wires the planning tools via extra_tools.
    from nexus_core.app.mcp_mount import build_configured_server

    return build_configured_server(
        regime_engine=_FakeRegime(),  # type: ignore[arg-type]
        market=_FakeMarket(),  # type: ignore[arg-type]
        macro=_FakeMacro(),  # type: ignore[arg-type]
    )


def test_planning_tools_register_natively() -> None:
    # Every planning tool must appear in tools/list over the MCP transport,
    # alongside the research tools — not only on the REST gateway.
    names = _tool_names(_configured_server())
    assert names >= _PLANNING_TOOL_IDS
    assert "score_asset" in names  # research tools still present


def test_planning_tool_call_echoes_contract_version() -> None:
    server = _configured_server()
    body = {
        "currentAge": 40,
        "retirementAge": 65,
        "horizonAge": 95,
        "startEquityWeight": 0.8,
        "endEquityWeight": 0.4,
        "shape": "linear",
    }
    result = asyncio.run(server.call_tool("glide_path", {"body": body}))  # type: ignore[attr-defined]
    text = result.content[0].text
    assert '"contractVersion": "0.1.0"' in text
    assert "equityWeightByAge" in text
    assert "not investment, tax, legal, or financial advice" in text.lower()


def test_planning_tool_rejects_identity_keys() -> None:
    from fastmcp.exceptions import ToolError

    server = _configured_server()
    with pytest.raises(ToolError, match="identity"):
        asyncio.run(
            server.call_tool(  # type: ignore[attr-defined]
                "glide_path",
                {"body": {"currentAge": 40, "email": "a@b.com"}},
            )
        )


def test_server_masks_error_details() -> None:
    # Belt-and-suspenders: an unexpected tool exception must not leak str(e).
    server = build_server()
    assert server._mask_error_details is True


def _call_text(server: object, tool: str, args: dict[str, object]) -> str:
    result = asyncio.run(server.call_tool(tool, args))  # type: ignore[attr-defined]
    return str(result.content[0].text)


def test_option_price_rejects_bad_inputs_preserves_bs_limits() -> None:
    import json

    server = build_server(market=_FakeMarket())  # type: ignore[arg-type]
    base = {"spot": 100, "strike": 90, "volatility": 0.25}
    # Rejections (fail before the fix, which returned raw intrinsic).
    for bad in ({"days": -30}, {"days": 5000}, {"spot": -5, "days": 30}, {"strike": 0, "days": 30}):
        args = {**base, **bad}
        body = json.loads(_call_text(server, "option_price", args))
        assert "error" in body, bad
    # BS limits must STILL work: days=0 (expiry intrinsic) and vol=0 (forward intrinsic).
    for ok in ({"days": 0}, {"days": 30, "volatility": 0.0}):
        body = json.loads(_call_text(server, "option_price", {**base, "days": 30, **ok}))
        assert "error" not in body, ok
        assert body["price"] >= 0.0


def test_equity_collar_screen_tool() -> None:
    import json

    server = build_server(market=_FakeMarket())  # type: ignore[arg-type]
    body = json.loads(
        _call_text(
            server,
            "equity_collar_screen",
            {
                "positions": [
                    {"symbol": "AAPL", "expiry_days": 45, "sigma": 0.25, "dividend_yield": 0.01}
                ]
            },
        )
    )
    assert "error" not in body
    assert body["count"] == 1
    row = body["screen"][0]
    assert row["symbol"] == "AAPL"
    assert row["spot"] == 100.0  # live quote from the fake market
    assert row["put_strike"] == 85.0  # 15% below spot on the $1 grid
    assert row["put_strike"] < row["spot"] < row["call_strike"]
    assert row["theoretical"] is True
    assert "not investment advice" in body["disclaimer"].lower()


def test_equity_collar_screen_tool_rejects_bad_inputs() -> None:
    import json

    server = build_server(market=_FakeMarket())  # type: ignore[arg-type]
    too_many = [
        {"symbol": f"T{i}", "spot": 100, "sigma": 0.3, "expiry_days": 30} for i in range(26)
    ]
    bad_calls: list[dict[str, object]] = [
        {"positions": []},
        {"positions": too_many},
        {"positions": [{"symbol": "AAPL", "expiry_days": 45}], "target_call_delta": 1.5},
        {"positions": [{"symbol": "AAPL", "expiry_days": 45}], "put_otm_pct": 100},
        {"positions": [{"symbol": "", "expiry_days": 45}]},
        {"positions": [{"symbol": "AAPL"}]},  # expiry_days missing
        {"positions": [{"symbol": "AAPL", "expiry_days": 5000}]},
        {"positions": [{"symbol": "AAPL", "expiry_days": 45, "spot": -1}]},
        {"positions": [{"symbol": "AAPL", "expiry_days": 45, "dividend_yield": 2}]},
    ]
    for args in bad_calls:
        body = json.loads(_call_text(server, "equity_collar_screen", args))
        assert "error" in body, args


def test_collar_book_tool() -> None:
    import json

    server = build_server(market=_FakeMarket())  # type: ignore[arg-type]
    body = json.loads(
        _call_text(
            server,
            "collar_book",
            {
                "positions": [
                    {
                        "symbol": "AAA",
                        "spot": 100.0,
                        "dte": 30,
                        "net_credit": 2.0,
                        "sector": "Tech",
                        "put_strike": 85.0,
                        "call_strike": 110.0,
                    },
                    {"symbol": "BBB", "spot": 50.0, "dte": 30, "net_credit": 1.0},
                ],
                "notional_target": 500_000.0,
            },
        )
    )
    assert "error" not in body
    assert body["basis"] == "advisor_research_worksheet"
    assert body["count"] == 2
    book = body["book"]
    holdings = {h["symbol"]: h for h in book["positions"]}
    assert set(holdings) == {"AAA", "BBB"}
    assert all(h["contracts"] >= 1 for h in holdings.values())
    assert holdings["AAA"]["floor_pct"] == 15.0  # derived from the put strike
    assert book["notional_deployed"] > 0.0
    assert "not investment advice" in body["disclaimer"].lower()


def test_collar_book_tool_rejects_bad_inputs() -> None:
    import json

    server = build_server(market=_FakeMarket())  # type: ignore[arg-type]
    good = {"symbol": "AAA", "spot": 100.0, "dte": 30, "net_credit": 2.0}
    too_many = [{**good, "symbol": f"T{i}"} for i in range(51)]
    bad_calls: list[dict[str, object]] = [
        {"positions": []},
        {"positions": too_many},
        # (a non-dict entry is rejected by FastMCP's schema validation itself)
        {"positions": [{"spot": 100.0, "dte": 30, "net_credit": 2.0}]},  # symbol missing
        {"positions": [{"symbol": "AAA", "dte": 30, "net_credit": 2.0}]},  # spot missing
        {"positions": [{"symbol": "AAA", "spot": 100.0, "net_credit": 2.0}]},  # dte missing
        {"positions": [{"symbol": "AAA", "spot": 100.0, "dte": 30}]},  # net_credit missing
        {"positions": [{**good, "sector": 7}]},
        {"positions": [{**good, "put_strike": "x"}]},
        {"positions": [good], "notional_target": 5_000},
        {"positions": [good], "notional_target": 2e9},
        {"positions": [good], "n_positions_target": 0},
        {"positions": [good], "n_positions_target": 51},
        {"positions": [good], "n_positions_min": 10, "n_positions_max": 5},
        {"positions": [good], "max_position_weight_pct": 0},
        {"positions": [good], "max_sector_weight_pct": 101},
    ]
    for args in bad_calls:
        body = json.loads(_call_text(server, "collar_book", args))
        assert "error" in body, args


def test_collar_book_tool_excludes_degenerates_not_errors() -> None:
    import json

    server = build_server(market=_FakeMarket())  # type: ignore[arg-type]
    body = json.loads(
        _call_text(
            server,
            "collar_book",
            {
                "positions": [
                    {"symbol": "BAD", "spot": 0.0, "dte": 30, "net_credit": 1.0},
                    {"symbol": "GOOD", "spot": 100.0, "dte": 30, "net_credit": 2.0},
                ]
            },
        )
    )
    assert "error" not in body
    book = body["book"]
    assert [e["symbol"] for e in book["excluded_degenerate"]] == ["BAD"]
    assert [h["symbol"] for h in book["positions"]] == ["GOOD"]


def test_crypto_covered_call_tool_inverse_yield() -> None:
    import json

    server = build_server(market=_FakeMarket(), deribit=_FakeDeribit())  # type: ignore[arg-type]
    body = json.loads(
        _call_text(
            server,
            "crypto_covered_call",
            {"currency": "BTC", "strike": 120000, "days": 30, "coins": 2, "premium": 0.02},
        )
    )
    assert "error" not in body
    assert body["settlement"] == "inverse"
    assert body["spot"] == 100000.0
    assert body["premium_usd"] == 2000.0
    assert body["coin_income"] == 0.04


def test_crypto_covered_call_chain_tool_ranks() -> None:
    import json

    server = build_server(market=_FakeMarket(), deribit=_FakeDeribit())  # type: ignore[arg-type]
    body = json.loads(
        _call_text(server, "crypto_covered_call_chain", {"currency": "BTC", "max_days": 60})
    )
    assert "error" not in body
    assert body["considered"] == 1  # the single OTM 110k call
    assert body["ranked"][0]["strike"] == 110000.0


def test_crypto_regime_overwrite_tool() -> None:
    import json

    server = build_server(
        regime_engine=_FakeRegime(),  # type: ignore[arg-type]
        market=_FakeMarket(),  # type: ignore[arg-type]
        deribit=_FakeDeribit(),  # type: ignore[arg-type]
    )
    body = json.loads(
        _call_text(server, "crypto_regime_overwrite", {"currency": "BTC", "max_days": 60})
    )
    assert "error" not in body
    assert body["regime"] == "expansion"  # fake GROWTH -> expansion
    assert body["adjusted_target_delta"] == 0.30


def test_crypto_regime_overwrite_without_regime_engine_errors() -> None:
    import json

    server = build_server(market=_FakeMarket(), deribit=_FakeDeribit())  # type: ignore[arg-type]
    body = json.loads(_call_text(server, "crypto_regime_overwrite", {"currency": "BTC"}))
    assert "error" in body  # tool registers but reports the missing regime engine


def test_crypto_vol_skew_tool() -> None:
    import json

    server = build_server(market=_FakeMarket(), deribit=_FakeDeribit())  # type: ignore[arg-type]
    body = json.loads(_call_text(server, "crypto_vol_skew", {"currency": "BTC", "target_days": 30}))
    assert "error" not in body
    assert body["expiry_days"] == 30
    assert body["points"][0]["strike"] == 110000.0  # the fake's single call
    assert body["atm_iv"] == 50.0


def test_crypto_iv_term_structure_tool() -> None:
    import json

    server = build_server(market=_FakeMarket(), deribit=_FakeDeribit())  # type: ignore[arg-type]
    body = json.loads(
        _call_text(server, "crypto_iv_term_structure", {"currency": "BTC", "max_days": 90})
    )
    assert "error" not in body
    assert body["points"][0]["expiry_days"] == 30  # the fake's near OTM call
    assert body["shape"] in {"flat", "backwardation", "contango", "n/a"}


def test_crypto_structured_tools_ladder_roll_book_scenario() -> None:
    import json

    server = build_server(market=_FakeMarket(), deribit=_FakeDeribit())  # type: ignore[arg-type]

    ladder = json.loads(
        _call_text(
            server,
            "crypto_covered_call_ladder",
            {
                "currency": "BTC",
                "total_coins": 10,
                "legs": [
                    {"expiry_days": 30, "strike": 120000, "coins": 4, "premium": 0.02},
                    {"expiry_days": 60, "strike": 130000, "coins": 3, "premium": 0.03},
                ],
            },
        )
    )
    assert ladder["coverage_pct"] == 70.0
    assert ladder["total_premium_usd"] == 17000.0

    roll = json.loads(
        _call_text(
            server,
            "crypto_option_roll",
            {
                "currency": "BTC",
                "coins": 2,
                "current_strike": 110000,
                "current_expiry_days": 5,
                "current_entry_premium": 0.03,
                "current_close_premium": 0.05,
                "new_strike": 120000,
                "new_expiry_days": 35,
                "new_open_premium": 0.04,
            },
        )
    )
    assert roll["roll_type"] == "roll up and out"
    assert roll["net_credit_usd"] == -2000.0

    book = json.loads(
        _call_text(
            server,
            "crypto_options_book_mtm",
            {
                "currency": "BTC",
                "coins_held": 1,
                "positions": [
                    {
                        "kind": "call",
                        "side": "short",
                        "strike": 120000,
                        "expiry_days": 30,
                        "coins": 1,
                        "entry_premium": 0.03,
                        "iv": 0.6,
                        "mark_premium": 0.02,
                    }
                ],
            },
        )
    )
    assert book["total_pnl_usd"] == 1000.0

    scenario = json.loads(
        _call_text(
            server,
            "crypto_options_scenario",
            {
                "currency": "BTC",
                "coins_held": 1,
                "positions": [
                    {
                        "kind": "call",
                        "side": "short",
                        "strike": 120000,
                        "expiry_days": 30,
                        "coins": 1,
                        "entry_premium": 0.03,
                        "iv": 0.6,
                    }
                ],
                "spot_shocks": [-0.2, 0.0, 0.25],
            },
        )
    )
    assert len(scenario["cells"]) == 3


def test_crypto_structured_tool_bad_input_errors() -> None:
    import json

    server = build_server(market=_FakeMarket(), deribit=_FakeDeribit())  # type: ignore[arg-type]
    body = json.loads(
        _call_text(
            server,
            "crypto_options_book_mtm",
            {"currency": "BTC", "positions": [{"kind": "spread", "side": "short"}]},
        )
    )
    assert "error" in body


def test_crypto_protective_put_and_collar_tools() -> None:
    import json

    server = build_server(market=_FakeMarket(), deribit=_FakeDeribit())  # type: ignore[arg-type]
    put = json.loads(
        _call_text(
            server,
            "crypto_protective_put",
            {"currency": "BTC", "strike": 80000, "days": 30, "coins": 2, "premium": 0.015},
        )
    )
    assert put["settlement"] == "inverse"
    assert put["premium_usd"] == 1500.0
    collar = json.loads(
        _call_text(
            server,
            "crypto_collar",
            {"currency": "BTC", "put_strike": 80000, "call_strike": 120000, "days": 30},
        )
    )
    assert collar["settlement"] == "inverse"
    assert "net_premium_usd" in collar


def test_enhancement_tools_register() -> None:
    names = _tool_names(_configured_server())
    assert {"health", "describe", "get_quotes"} <= names


def test_tools_are_annotated_read_only() -> None:
    server = _configured_server()
    tools = asyncio.run(server.list_tools())  # type: ignore[attr-defined]
    annotated = [t for t in tools if t.annotations is not None]
    assert annotated, "expected ToolAnnotations on tools"
    assert all(t.annotations.readOnlyHint for t in annotated)


def test_describe_reports_symbology_and_contract() -> None:
    import json

    server = _configured_server()
    body = json.loads(_call_text(server, "describe", {}))
    assert body["planning_contract_version"] == "0.1.0"
    assert "BTC-USD" in body["symbology"]["crypto_scoring"]
    assert "bitcoin" in body["symbology"]["crypto_quotes"]
    assert "monte_carlo_decumulation" in body["categories"]["planning"]


def test_health_reports_upstreams() -> None:
    import json

    server = _configured_server()
    body = json.loads(_call_text(server, "health", {}))
    assert body["service"] == "nexus-core"
    assert "fred" in body["upstreams"]


def test_get_quotes_batch() -> None:
    import json

    server = build_server(market=_FakeMarket())  # type: ignore[arg-type]
    body = json.loads(_call_text(server, "get_quotes", {"symbols": ["AAPL", "SPY"]}))
    assert set(body["quotes"]) == {"AAPL", "SPY"}


def test_native_research_tools_carry_disclaimer() -> None:
    # The not-advice disclaimer must be present on the /mcp transport, not only
    # on the REST equivalents (RIA Marketing-Rule guarantee, CI-enforced).
    server = _configured_server()
    cases = [
        ("get_quote", {"symbol": "AAPL"}),
        ("current_regime", {}),
        ("option_price", {"spot": 100, "strike": 100, "days": 30, "volatility": 0.3}),
    ]
    for tool, args in cases:
        result = asyncio.run(server.call_tool(tool, args))  # type: ignore[attr-defined]
        text = result.content[0].text.lower()
        assert "not investment, tax, legal, or financial advice" in text, tool


def _mboum_options_stub(payload: dict[str, object] | None) -> object:
    import httpx

    from nexus_core.data.derivatives import MboumOptionsClient

    def handler(request: httpx.Request) -> httpx.Response:
        if payload is None:
            return httpx.Response(500, json={})
        return httpx.Response(200, json=payload)

    return MboumOptionsClient(
        api_key="test-mboum-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


_MBOUM_TOOL_PAYLOAD: dict[str, object] = {
    "meta": {"expirations": {"monthly": ["2026-08-21"], "weekly": ["2026-08-07"]}},
    "body": {
        "Call": [
            {
                "strikePrice": "87.00",
                "bidPrice": "0.62",
                "askPrice": "0.70",
                "midpoint": "0.66",
                "openInterest": "2,400",
                "volatility": "24.50%",
                "delta": "0.2600",
                "expirationDate": "08/07/26",
                "expirationType": "weekly",
            }
        ],
        "Put": [
            {
                "strikePrice": "70.00",
                "bidPrice": "0.28",
                "askPrice": "0.34",
                "midpoint": "0.31",
                "openInterest": "7,299",
                "volatility": "28.19%",
                "delta": "-0.0403",
                "expirationDate": "08/07/26",
                "expirationType": "weekly",
            }
        ],
    },
}


def test_equity_option_chain_tools_registered_only_with_client() -> None:
    default_server = build_server(market=_FakeMarket())  # type: ignore[arg-type]
    default_tools = _tool_names(default_server)
    assert "equity_option_expirations" not in default_tools
    assert "equity_option_chain" not in default_tools

    server = build_server(
        market=_FakeMarket(),  # type: ignore[arg-type]
        mboum_options=_mboum_options_stub(_MBOUM_TOOL_PAYLOAD),  # type: ignore[arg-type]
    )
    tools = _tool_names(server)
    assert "equity_option_expirations" in tools
    assert "equity_option_chain" in tools


def test_equity_option_expirations_tool() -> None:
    import json

    server = build_server(
        market=_FakeMarket(),  # type: ignore[arg-type]
        mboum_options=_mboum_options_stub(_MBOUM_TOOL_PAYLOAD),  # type: ignore[arg-type]
    )
    body = json.loads(_call_text(server, "equity_option_expirations", {"symbol": "ko"}))
    assert "error" not in body
    assert body["symbol"] == "KO"
    assert body["expirations"]["weekly"] == ["2026-08-07"]

    bad = json.loads(_call_text(server, "equity_option_expirations", {"symbol": "K$O"}))
    assert "error" in bad


def test_equity_option_chain_tool() -> None:
    import json

    server = build_server(
        market=_FakeMarket(),  # type: ignore[arg-type]
        mboum_options=_mboum_options_stub(_MBOUM_TOOL_PAYLOAD),  # type: ignore[arg-type]
    )
    body = json.loads(
        _call_text(
            server, "equity_option_chain", {"symbol": "KO", "expiration": "2026-08-07"}
        )
    )
    assert "error" not in body
    assert body["count"] == {"calls": 1, "puts": 1}
    assert body["puts"][0]["open_interest"] == 7299

    bad_date = json.loads(
        _call_text(server, "equity_option_chain", {"symbol": "KO", "expiration": "soon"})
    )
    assert "error" in bad_date


def test_equity_option_chain_tools_degrade_without_key() -> None:
    import json

    from nexus_core.data.derivatives import MboumOptionsClient

    server = build_server(
        market=_FakeMarket(),  # type: ignore[arg-type]
        mboum_options=MboumOptionsClient(api_key=None),  # type: ignore[arg-type]
    )
    body = json.loads(_call_text(server, "equity_option_expirations", {"symbol": "KO"}))
    assert "error" in body
    assert "MBOUM_API_KEY" in body["error"]
