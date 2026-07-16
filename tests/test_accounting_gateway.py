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
    OpeningLotInput,
    PriceHistoryRequest,
    RawTransactionInput,
    find_identity_keys,
)
from nexus_core.app.accounting.tools import PLANNED_TOOLS, build_tool_handlers
from nexus_core.engine.accounting import PriceHistorian
from nexus_core.engine.accounting.lots import exact_decimal_sum

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
                    "asset": {
                        "asset_id": "eth:usdc",
                        "symbol": "USDC",
                        "chain": "ethereum",
                        "decimals": 6,
                    },
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
    assert ACCOUNTING_CONTRACT_VERSION == "0.2.0"
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
    bad = {
        "events": [{"event_id": "e", "account_ref": "a", "kind": "fee", "timestamp": 1, "legs": []}]
    }
    with pytest.raises(ValidationError):
        EventLedger.model_validate(bad)


@pytest.mark.parametrize("value", ["1e-100000000", "1e100000000", "0e100000000"])
def test_event_ledger_rejects_extreme_decimal_exponents(value: str) -> None:
    with pytest.raises(ValidationError, match="accounting"):
        EventLedger.model_validate(
            {
                "events": [
                    {
                        "event_id": "e",
                        "account_ref": "a",
                        "kind": "acquire",
                        "timestamp": 1,
                        "legs": [
                            {
                                "asset": {"asset_id": "x"},
                                "direction": "in",
                                "amount": "1",
                                "usd_value": value,
                            }
                        ],
                    }
                ]
            }
        )


def test_exact_decimal_sum_rejects_unbounded_alignment_before_arithmetic() -> None:
    with pytest.raises(ValueError, match="arithmetic envelope"):
        exact_decimal_sum((Decimal("1"), Decimal("1e-100000000")))


def test_exact_decimal_sum_rejects_a_derived_total_outside_the_envelope() -> None:
    maximum_operand = Decimal("9" * 128)

    with pytest.raises(ValueError, match="magnitude exceeds"):
        exact_decimal_sum((maximum_operand, maximum_operand))


def test_event_ledger_rejects_raw_wallet_as_opaque_account_ref() -> None:
    bad = {
        "events": [
            {
                "event_id": "e",
                "account_ref": "0x" + "a" * 40,
                "kind": "acquire",
                "timestamp": 1,
                "legs": [{"asset": {"asset_id": "x"}, "direction": "in", "amount": "1"}],
            }
        ]
    }
    with pytest.raises(ValidationError, match="account_ref must be opaque"):
        EventLedger.model_validate(bad)


def test_supported_chain_wallet_shapes_are_rejected_across_account_inputs() -> None:
    solana_address = "11111111111111111111111111111111"
    bitcoin_legacy = "1BoatSLRHtKNngkdXEeobR76b53LETtpyT"

    with pytest.raises(ValidationError, match="account_ref must be opaque"):
        EventLedger.model_validate(
            {
                "events": [
                    {
                        "event_id": "e",
                        "account_ref": solana_address,
                        "kind": "acquire",
                        "timestamp": 1,
                        "legs": [{"asset": {"asset_id": "x"}, "direction": "in", "amount": "1"}],
                    }
                ]
            }
        )

    with pytest.raises(ValidationError, match="account_ref must be opaque"):
        RawTransactionInput.model_validate(
            {
                "account_ref": bitcoin_legacy,
                "chain": "bitcoin",
                "timestamp": 1,
                "movements": [{"asset": {"asset_id": "btc"}, "direction": "in", "amount": "1"}],
            }
        )

    with pytest.raises(ValidationError, match="account_ref must be opaque"):
        OpeningLotInput.model_validate(
            {
                "lot_ref": "lot-1",
                "account_ref": solana_address,
                "asset": {"asset_id": "sol"},
                "quantity": "1",
                "unit_cost_usd": "10",
                "acquired_at": 1,
                "basis_source": "replayed_history",
            }
        )


def test_find_identity_keys_catches_identity_wallet_and_client_keys() -> None:
    assert find_identity_keys({"name": "x"}) == ["name"]
    assert find_identity_keys({"client_id": "x"}) == ["client_id"]
    assert find_identity_keys({"client_ref": "x"}) == ["client_ref"]
    assert find_identity_keys({"nested": [{"walletAddress": "0x0"}]}) == ["walletAddress"]
    # opaque references are fine
    assert find_identity_keys({"account_ref": "acct-1", "asset_id": "eth:usdc"}) == []


def test_build_tool_handlers_describes_available_v2_contract() -> None:
    handlers = build_tool_handlers()
    assert set(handlers) == {
        "describe",
        "decode_onchain_events",
        "compute_cost_basis",
        "onchain_pnl_report",
    }
    out = handlers["describe"]({})
    assert out["status"] == "available"
    assert set(out["tools"]) == set(handlers)
    assert "price_history" not in out["tools"]
    assert list(out["plannedTools"]) == list(PLANNED_TOOLS)
    # the ledger schema is published so a consumer can validate its shape
    assert "eventLedgerSchema" in out
    assert out["eventLedgerSchema"]["type"] == "object"
    assert "report_window" in out["costBasisRequestSchema"]["properties"]
    assert out["methodology"]["reviewStatus"] == "pending_governance_review"


def test_describe_lists_optional_price_history_only_when_registered() -> None:
    handlers = build_tool_handlers(price_historian=PriceHistorian([]))
    assert "price_history" in handlers["describe"]({})["tools"]


def test_decode_handler_classifies_fee_only_transaction() -> None:
    out = build_tool_handlers()["decode_onchain_events"](
        {
            "transactions": [
                {
                    "account_ref": "account-opaque",
                    "chain": "ethereum",
                    "timestamp": 1,
                    "tx_ref": "fee-transaction",
                    "movements": [
                        {
                            "asset": {"asset_id": "eth:eth"},
                            "direction": "out",
                            "amount": "0.001",
                            "role": "fee",
                        }
                    ],
                }
            ]
        }
    )

    assert out["events"][0]["kind"] == "fee"
    assert out["eventCountsByKind"] == {"fee": 1}


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
    assert body["tools"] == [
        "compute_cost_basis",
        "decode_onchain_events",
        "describe",
        "onchain_pnl_report",
    ]


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


def test_route_decode_rejects_fallback_event_id_collision_400() -> None:
    transaction = {
        "account_ref": "account-opaque",
        "chain": "ethereum",
        "timestamp": 1,
        "movements": [{"asset": {"asset_id": "eth:asset"}, "direction": "in", "amount": "1"}],
    }
    resp = _client().post(
        "/api/accounting/tools/decode_onchain_events",
        json={"transactions": [transaction, transaction]},
    )

    assert resp.status_code == 400
    assert "duplicate event_id" in resp.text


def test_route_decode_rejects_transfer_metadata_on_a_non_transfer_400() -> None:
    response = _client().post(
        "/api/accounting/tools/decode_onchain_events",
        json={
            "transactions": [
                {
                    "account_ref": "account-opaque",
                    "chain": "ethereum",
                    "timestamp": 1,
                    "movements": [
                        {"asset": {"asset_id": "eth:a"}, "direction": "out", "amount": "1"},
                        {"asset": {"asset_id": "eth:b"}, "direction": "in", "amount": "1"},
                    ],
                    "transfer_ref": "transfer-1",
                    "transfer_treatment": "same_owner",
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "transfer metadata is only valid" in response.text


def test_route_compute_cost_basis_rejects_a_derived_total_outside_the_envelope() -> None:
    maximum_operand = "9" * 128
    response = _client().post(
        "/api/accounting/tools/compute_cost_basis",
        json={
            "events": [],
            "report_window": {
                "start_at": 10,
                "end_at": 11,
                "opening_state": {
                    "schema_version": "2.0.0",
                    "basis_method": "fifo",
                    "basis_method_version": "2.0.0",
                    "snapshot_complete": True,
                    "state_ref": "derived-total-overflow",
                    "as_of": 9,
                    "source": "private_event_ledger",
                    "last_verified": "2026-07-16",
                    "lots": [
                        {
                            "lot_ref": f"opening-lot-{index}",
                            "account_ref": "account-opaque",
                            "asset": {"asset_id": f"asset-{index}"},
                            "quantity": "1",
                            "cost_basis_usd": maximum_operand,
                            "acquired_at": 1,
                            "basis_source": "replayed_history",
                            "basis_price_source": "historian",
                            "basis_price_as_of": 1,
                        }
                        for index in range(2)
                    ],
                },
            },
        },
    )

    assert response.status_code == 400
    assert "magnitude exceeds" in response.text


def test_route_compute_cost_basis_fifo() -> None:
    body = {
        "events": [
            {
                "event_id": "b1",
                "account_ref": "a",
                "kind": "acquire",
                "timestamp": 1,
                "legs": [
                    {
                        "asset": {"asset_id": "a"},
                        "direction": "in",
                        "amount": "1",
                        "usd_value": "10",
                        "price_source": "caller_price",
                        "price_as_of": 1,
                    }
                ],
            },
            {
                "event_id": "s1",
                "account_ref": "a",
                "kind": "dispose",
                "timestamp": 2,
                "legs": [
                    {
                        "asset": {"asset_id": "a"},
                        "direction": "out",
                        "amount": "1",
                        "usd_value": "30",
                        "price_source": "caller_price",
                        "price_as_of": 2,
                    }
                ],
            },
        ],
        "report_window": {"start_at": 1, "end_at": 3, "full_history": True},
    }
    resp = _client().post("/api/accounting/tools/compute_cost_basis", json=body)
    assert resp.status_code == 200
    out = resp.json()
    assert out["method"] == "fifo"
    assert out["disposals"][0]["realized_gain_usd"] == "20"
    assert out["totals"]["realized_gain_usd"] == "20"
    assert out["completeness"]["complete"] is True
    assert out["completeness"]["statement_ready"] is False
    assert out["methodology"]["method_version"] == "2.0.0"


def test_route_compute_cost_basis_invalid_body_400() -> None:
    resp = _client().post("/api/accounting/tools/compute_cost_basis", json={"events": []})
    assert resp.status_code == 400


def test_route_compute_cost_basis_rejects_extreme_decimal_exponent_400() -> None:
    body = {
        "events": [
            {
                "event_id": "acq",
                "account_ref": "acct-opaque",
                "kind": "acquire",
                "timestamp": 1,
                "legs": [
                    {
                        "asset": {"asset_id": "asset"},
                        "direction": "in",
                        "amount": "1",
                        "usd_value": "1e-100000000",
                    }
                ],
            }
        ],
        "report_window": {"start_at": 1, "end_at": 2, "full_history": True},
    }

    resp = _client().post("/api/accounting/tools/compute_cost_basis", json=body)

    assert resp.status_code == 400


def test_route_compute_cost_basis_rejects_blank_price_provenance_400() -> None:
    body = {
        "events": [
            {
                "event_id": "acq",
                "account_ref": "acct-opaque",
                "kind": "acquire",
                "timestamp": 1,
                "legs": [
                    {
                        "asset": {"asset_id": "asset"},
                        "direction": "in",
                        "amount": "1",
                        "usd_value": "10",
                        "price_source": "   ",
                        "price_as_of": 1,
                    }
                ],
            }
        ],
        "report_window": {"start_at": 1, "end_at": 2, "full_history": True},
    }

    resp = _client().post("/api/accounting/tools/compute_cost_basis", json=body)

    assert resp.status_code == 400
    assert "invalid compute_cost_basis request body" in resp.text


def test_route_quiet_period_requests_are_valid() -> None:
    body = {
        "events": [],
        "report_window": {"start_at": 1, "end_at": 2, "full_history": True},
    }

    cost_basis = _client().post("/api/accounting/tools/compute_cost_basis", json=body)
    assert cost_basis.status_code == 200
    assert cost_basis.json()["replay"]["in_period_event_count"] == 0

    pnl = _client().post("/api/accounting/tools/onchain_pnl_report", json=body)
    assert pnl.status_code == 200
    assert pnl.json()["summary"]["disposal_count"] == 0


def test_route_onchain_pnl_report() -> None:
    body = {
        "events": [
            {
                "event_id": "a",
                "account_ref": "x",
                "kind": "acquire",
                "timestamp": 1_600_000_000,
                "legs": [
                    {
                        "asset": {"asset_id": "a"},
                        "direction": "in",
                        "amount": "1",
                        "usd_value": "10",
                        "price_source": "caller_price",
                        "price_as_of": 1_600_000_000,
                    }
                ],
            },
            {
                "event_id": "d",
                "account_ref": "x",
                "kind": "dispose",
                "timestamp": 1_600_100_000,
                "legs": [
                    {
                        "asset": {"asset_id": "a"},
                        "direction": "out",
                        "amount": "1",
                        "usd_value": "30",
                        "price_source": "caller_price",
                        "price_as_of": 1_600_100_000,
                    }
                ],
            },
        ],
        "report_window": {
            "start_at": 1_600_000_000,
            "end_at": 1_600_100_001,
            "full_history": True,
        },
    }
    resp = _client().post("/api/accounting/tools/onchain_pnl_report", json=body)
    assert resp.status_code == 200
    out = resp.json()
    assert out["summary"]["realized_gain_usd"] == "20"
    assert out["summary"]["complete"] is True
    assert out["completeness"]["complete"] is True
    assert out["completeness"]["statement_ready"] is False
    assert out["dispositions"][0]["disposal_event_id"] == "d"
    assert "tax professional" in out["disclaimer"]


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


def test_route_rejects_raw_wallet_value_as_account_ref() -> None:
    raw_wallet = "0x" + "a" * 40
    body = {
        "events": [
            {
                "event_id": "a",
                "account_ref": raw_wallet,
                "kind": "acquire",
                "timestamp": 1,
                "legs": [{"asset": {"asset_id": "a"}, "direction": "in", "amount": "1"}],
            }
        ]
    }
    response = _client().post("/api/accounting/tools/compute_cost_basis", json=body)
    assert response.status_code == 400


def test_route_rejects_duplicate_events_as_bad_request() -> None:
    event = {
        "event_id": "duplicate",
        "account_ref": "acct-opaque",
        "kind": "acquire",
        "timestamp": 1,
        "sequence": 0,
        "legs": [{"asset": {"asset_id": "a"}, "direction": "in", "amount": "1"}],
    }
    response = _client().post(
        "/api/accounting/tools/compute_cost_basis",
        json={"events": [event, event | {"sequence": 1}]},
    )
    assert response.status_code == 400
    assert "duplicate event_id" in response.text


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


def test_price_history_allows_duplicate_query_slots_with_one_override() -> None:
    body = {
        "queries": [
            {"coin": "eth:usdc", "timestamp": 100},
            {"coin": "eth:usdc", "timestamp": 100},
        ],
        "overrides": [{"coin": "eth:usdc", "timestamp": 100, "price_usd": "0.999"}],
    }
    request = PriceHistoryRequest.model_validate(body)
    assert len(request.queries) == 2

    prices = build_tool_handlers(price_historian=PriceHistorian([]))["price_history"](body)[
        "prices"
    ]
    assert len(prices) == 2
    assert all(price["priceUsd"] == "0.999" for price in prices)


@pytest.mark.parametrize(
    "overrides",
    [
        [{"coin": "eth:dai", "timestamp": 100, "price_usd": "1"}],
        [
            {"coin": "eth:usdc", "timestamp": 100, "price_usd": "0.999"},
            {"coin": "eth:usdc", "timestamp": 100, "price_usd": "1.001"},
        ],
    ],
    ids=["orphan", "duplicate"],
)
def test_price_history_rejects_ambiguous_override_coordinates(
    overrides: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        PriceHistoryRequest.model_validate(
            {
                "queries": [{"coin": "eth:usdc", "timestamp": 100}],
                "overrides": overrides,
            }
        )


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
