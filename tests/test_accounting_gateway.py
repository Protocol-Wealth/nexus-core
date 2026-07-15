# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the onchain-accounting Phase 0 scaffold (epic nexus-core#248).

Pure tests (schema + tools + identity scan) carry no TestClient dependency so
they run in any environment; the ``route_`` tests exercise the HTTP gateway.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from nexus_core.app.accounting import build_accounting_router
from nexus_core.app.accounting.contract import (
    ACCOUNTING_CONTRACT_VERSION,
    EventLedger,
    find_identity_keys,
)
from nexus_core.app.accounting.tools import PLANNED_TOOLS, build_tool_handlers
from nexus_core.engine.accounting import PriceHistorian

# A de-identified sample ledger: opaque refs + public onchain facts only.
SAMPLE_LEDGER = {
    "events": [
        {
            "event_id": "evt-1",
            "account_ref": "acct-opaque-1",
            "kind": "acquire",
            "timestamp": 1_700_000_000,
            "tx_ref": "tx-opaque-1",
            "legs": [
                {
                    "asset": {"asset_id": "eth:usdc", "symbol": "USDC", "chain": "ethereum", "decimals": 6},
                    "direction": "in",
                    "amount": "1000.00",
                    "unit_price_usd": "1.00",
                }
            ],
        },
        {
            "event_id": "evt-2",
            "account_ref": "acct-opaque-1",
            "kind": "deposit",
            "timestamp": 1_700_100_000,
            "legs": [
                {
                    "asset": {"asset_id": "base:aero-vault", "symbol": "vAERO", "chain": "base"},
                    "direction": "out",
                    "amount": "1000",
                }
            ],
        },
    ]
}


def test_contract_version_is_a_semver_string() -> None:
    assert ACCOUNTING_CONTRACT_VERSION.count(".") == 2


def test_event_ledger_validates_a_de_identified_sample() -> None:
    ledger = EventLedger.model_validate(SAMPLE_LEDGER)
    assert len(ledger.events) == 2
    # amounts parse as Decimal, not float — accounting precision is preserved.
    assert ledger.events[0].legs[0].amount == Decimal("1000.00")
    assert isinstance(ledger.events[0].legs[0].amount, Decimal)


def test_event_ledger_forbids_smuggled_extra_fields() -> None:
    bad = {
        "events": [
            {
                "event_id": "evt-1",
                "account_ref": "acct-1",
                "kind": "acquire",
                "timestamp": 1,
                "client_id": "should-be-rejected",
                "legs": [{"asset": {"asset_id": "x"}, "direction": "in", "amount": "1"}],
            }
        ]
    }
    with pytest.raises(ValidationError):
        EventLedger.model_validate(bad)


def test_event_ledger_rejects_non_positive_amount() -> None:
    bad = {
        "events": [
            {
                "event_id": "e",
                "account_ref": "a",
                "kind": "dispose",
                "timestamp": 1,
                "legs": [{"asset": {"asset_id": "x"}, "direction": "out", "amount": "0"}],
            }
        ]
    }
    with pytest.raises(ValidationError):
        EventLedger.model_validate(bad)


def test_event_ledger_requires_at_least_one_leg() -> None:
    bad = {"events": [{"event_id": "e", "account_ref": "a", "kind": "fee", "timestamp": 1, "legs": []}]}
    with pytest.raises(ValidationError):
        EventLedger.model_validate(bad)


def test_find_identity_keys_catches_identity_wallet_and_client_keys() -> None:
    assert find_identity_keys({"name": "x"}) == ["name"]
    assert find_identity_keys({"client_id": "x"}) == ["client_id"]
    assert find_identity_keys({"nested": [{"walletAddress": "0x0"}]}) == ["walletAddress"]
    # opaque references are fine
    assert find_identity_keys({"account_ref": "acct-1", "asset_id": "eth:usdc"}) == []


def test_build_tool_handlers_ships_describe_scaffold() -> None:
    handlers = build_tool_handlers()
    assert set(handlers) == {"describe", "decode_onchain_events"}
    out = handlers["describe"]({})
    assert out["status"] == "scaffold"
    assert list(out["plannedTools"]) == list(PLANNED_TOOLS)
    # the ledger schema is published so a consumer can validate its shape
    assert "eventLedgerSchema" in out
    assert out["eventLedgerSchema"]["type"] == "object"


# --- HTTP gateway tests ------------------------------------------------------


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(build_accounting_router())
    return TestClient(app)


def test_route_lists_tools_with_contract_version() -> None:
    resp = _client().get("/api/accounting/tools")
    assert resp.status_code == 200
    body = resp.json()
    assert body["contractVersion"] == ACCOUNTING_CONTRACT_VERSION
    assert body["tools"] == ["decode_onchain_events", "describe"]


def test_route_describe_echoes_contract_version_and_disclaimer() -> None:
    resp = _client().post("/api/accounting/tools/describe", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["contractVersion"] == ACCOUNTING_CONTRACT_VERSION
    assert body["engine"] == "onchain-accounting"
    assert "disclaimer" in body


def test_route_rejects_identity_fields_400() -> None:
    resp = _client().post("/api/accounting/tools/describe", json={"clientId": "nope"})
    assert resp.status_code == 400
    assert "PII-free" in resp.text


def test_route_unknown_tool_404() -> None:
    resp = _client().post("/api/accounting/tools/not_a_tool", json={})
    assert resp.status_code == 404
    assert "unknown tool" in resp.text


def test_route_non_object_body_400() -> None:
    resp = _client().post(
        "/api/accounting/tools/describe", content="[]", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 400


def test_route_lists_decode_tool_always() -> None:
    assert "decode_onchain_events" in _client().get("/api/accounting/tools").json()["tools"]


def test_route_decode_normalizes_a_swap() -> None:
    body = {
        "transactions": [
            {
                "account_ref": "a",
                "chain": "ethereum",
                "timestamp": 1,
                "protocol_hint": "uniswap_v3",
                "movements": [
                    {"asset": {"asset_id": "eth:usdc"}, "direction": "out", "amount": "1000"},
                    {"asset": {"asset_id": "eth:weth"}, "direction": "in", "amount": "0.3"},
                ],
            }
        ]
    }
    resp = _client().post("/api/accounting/tools/decode_onchain_events", json=body)
    assert resp.status_code == 200
    out = resp.json()
    assert out["events"][0]["kind"] == "swap"
    assert out["eventCountsByKind"] == {"swap": 1}


def test_route_decode_invalid_body_400() -> None:
    resp = _client().post("/api/accounting/tools/decode_onchain_events", json={"transactions": []})
    assert resp.status_code == 400


def test_route_decode_rejects_identity_field_400() -> None:
    body = {
        "transactions": [
            {
                "account_ref": "a",
                "chain": "ethereum",
                "timestamp": 1,
                "clientId": "leak",
                "movements": [{"asset": {"asset_id": "eth:a"}, "direction": "in", "amount": "1"}],
            }
        ]
    }
    resp = _client().post("/api/accounting/tools/decode_onchain_events", json=body)
    assert resp.status_code == 400
    assert "PII-free" in resp.text


def test_route_price_history_absent_without_historian_404() -> None:
    resp = _client().post(
        "/api/accounting/tools/price_history", json={"queries": [{"coin": "x", "timestamp": 1}]}
    )
    assert resp.status_code == 404


# --- price_history route (P1), with an override-only historian ---------------


def _client_with_historian() -> TestClient:
    app = FastAPI()
    # no live sources: overrides resolve deterministically, everything else gaps
    app.include_router(build_accounting_router(price_historian=PriceHistorian([])))
    return TestClient(app)


def test_route_price_history_is_registered_with_a_historian() -> None:
    resp = _client_with_historian().get("/api/accounting/tools")
    assert "price_history" in resp.json()["tools"]


def test_route_price_history_prices_via_override() -> None:
    body = {
        "queries": [{"coin": "eth:usdc", "timestamp": 100}],
        "overrides": [{"coin": "eth:usdc", "timestamp": 100, "price_usd": "0.999"}],
    }
    resp = _client_with_historian().post("/api/accounting/tools/price_history", json=body)
    assert resp.status_code == 200
    price = resp.json()["prices"][0]
    assert price["status"] == "priced"
    assert price["priceUsd"] == "0.999"
    assert price["source"] == "override"


def test_route_price_history_gap_is_explicit_null() -> None:
    resp = _client_with_historian().post(
        "/api/accounting/tools/price_history",
        json={"queries": [{"coin": "eth:unknown", "timestamp": 100}]},
    )
    price = resp.json()["prices"][0]
    assert price["status"] == "unpriced"
    assert price["priceUsd"] is None


def test_route_price_history_invalid_body_400() -> None:
    resp = _client_with_historian().post(
        "/api/accounting/tools/price_history", json={"queries": []}
    )
    assert resp.status_code == 400
