# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for MCP tool registration in ``build_server``.

Verifies the conditional tool groups (regime / market / macro / DeFi / options)
register when their providers are supplied. Skipped if ``fastmcp`` is absent.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastmcp")

from nexus_core.data.derivatives import OptionInstrument, OptionTicker  # noqa: E402
from nexus_core.data.providers import PriceBar, Quote  # noqa: E402
from nexus_core.mcp.server import build_server  # noqa: E402


class _RegimeResult:
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
    def list_option_instruments(self, currency: str) -> list[OptionInstrument]:
        return [OptionInstrument(instrument_name=f"{currency}-X", base_currency=currency)]

    def get_option_ticker(self, instrument_name: str) -> OptionTicker | None:
        return OptionTicker(instrument_name=instrument_name, mark_iv=50.0)


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
        "crypto_option_instruments",
        "crypto_option_ticker",
        "defi_protocols",
        "defi_protocol",
        "defi_chains",
    }
    assert expected <= names


def test_minimal_server_registers_no_tools() -> None:
    assert _tool_names(build_server()) == set()


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
    "glide_path",
    "tax_aware_withdrawal",
    "correlation_matrix",
    "capital_market_assumptions",
    "regime_return_generator",
}


def _configured_server() -> object:
    # build_configured_server wires the 6 planning tools via extra_tools.
    from nexus_core.app.mcp_mount import build_configured_server

    return build_configured_server(
        regime_engine=_FakeRegime(),  # type: ignore[arg-type]
        market=_FakeMarket(),  # type: ignore[arg-type]
        macro=_FakeMacro(),  # type: ignore[arg-type]
    )


def test_planning_tools_register_natively() -> None:
    # The 6 planning tools must appear in tools/list over the MCP transport,
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
