# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the ``classify_layer`` MCP tool.

Pure compute over the published EMF layer maps — no provider is wired, so the
tool must register (and answer) on a bare server and on the public demo profile.
Skipped if ``fastmcp`` is absent.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("fastmcp")

from nexus_core.disclaimers import TERSE  # noqa: E402
from nexus_core.mcp.server import build_server  # noqa: E402


def _call(server: Any, **arguments: Any) -> dict[str, Any]:
    result = asyncio.run(server.call_tool("classify_layer", arguments))
    payload: dict[str, Any] = json.loads(result.content[0].text)
    return payload


def test_classify_layer_registers_in_every_profile() -> None:
    for server in (build_server(), build_server(tool_profile="demo")):
        names = {t.name for t in asyncio.run(server.list_tools())}
        assert "classify_layer" in names


def test_ticker_map_hit_carries_horizon_and_provenance() -> None:
    # The deployment builds with the canonical TERSE disclaimer (see mcp_mount).
    body = _call(build_server(disclaimer=TERSE), ticker="crwd")
    assert body["ticker"] == "CRWD"
    assert body["layer"] == "L4"
    assert body["layer_key"] == "L4_datatoll"  # code name stays; display name is clean
    assert body["name"] == "Data Infrastructure"
    assert body["horizon"] == "7-12 yr"
    assert body["decay_threshold"] == 0.15
    assert body["classification"]["source"] == "ticker_map"
    assert body["regime_weights"]["G"] == 20
    assert "not investment, tax, legal, or financial advice" in body["disclaimer"].lower()


def test_asset_class_route() -> None:
    body = _call(build_server(tool_profile="demo"), ticker="BTC-USD")
    assert body["layer"] == "L1"
    assert body["name"] == "Foundation"
    assert body["horizon"] == "40-60 yr"
    assert body["classification"]["source"] == "asset_class_crypto"


def test_sector_default_and_keyword_from_caller_supplied_fundamentals() -> None:
    server = build_server()
    default = _call(server, ticker="DE", sector="Industrials")
    assert default["layer"] == "L2"
    assert default["classification"]["source"] == "sector_default"

    keyword = _call(server, ticker="DE", sector="Industrials", industry="Defense Systems")
    assert keyword["layer"] == "L4"
    assert keyword["classification"]["source"] == "sector_industry_keyword"
    assert keyword["classification"]["matched_on"] == "industry:defense"


def test_unknown_ticker_is_unclassified_not_defaulted() -> None:
    body = _call(build_server(), ticker="ZZZZ")
    assert body["layer"] == "UNCLASSIFIED"
    assert body["name"] is None
    assert body["horizon"] is None
    assert body["decay_threshold"] is None
    assert "insufficient data" in body["classification"]["rule"].lower()


def test_empty_ticker_errors() -> None:
    body = _call(build_server(), ticker="   ")
    assert "ticker must not be empty" in body["error"]
