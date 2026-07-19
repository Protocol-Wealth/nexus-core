# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the Deribit public options client.

Hermetic — every request is served by an ``httpx.MockTransport`` handler that
returns Deribit-shaped ``{"result": ...}`` JSON-RPC-over-REST envelopes. No
network, no credentials.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from nexus_core.data.derivatives import (
    DISCLAIMER,
    DeribitClient,
    OptionInstrument,
    OptionTicker,
)
from nexus_core.disclaimers import TERSE


def test_disclaimer_is_canonical_terse() -> None:
    # Deribit must not hand-write regulatory copy — DISCLAIMER is the canonical TERSE.
    assert DISCLAIMER == TERSE


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_list_option_instruments_parses_and_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/public/get_instruments"
        # Deribit expects the lowercase JSON literal, not Python's "False".
        assert request.url.params["currency"] == "BTC"
        assert request.url.params["kind"] == "option"
        assert request.url.params["expired"] == "false"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "result": [
                    {
                        "instrument_name": "BTC-27JUN25-100000-C",
                        "base_currency": "BTC",
                        "option_type": "call",
                        "strike": 100000,
                        "expiration_timestamp": 1750982400000,
                        "is_active": True,
                    },
                    {
                        "instrument_name": "BTC-27JUN25-80000-P",
                        "base_currency": "BTC",
                        "option_type": "put",
                        "strike": 80000.0,
                        "expiration_timestamp": 1750982400000,
                        "is_active": True,
                    },
                    # Malformed entries are skipped, not fatal.
                    {"base_currency": "BTC"},
                    "not-a-dict",
                ],
            },
        )

    instruments = DeribitClient(http_client=_client(handler)).list_option_instruments("btc")
    assert [i.instrument_name for i in instruments] == [
        "BTC-27JUN25-100000-C",
        "BTC-27JUN25-80000-P",
    ]
    first = instruments[0]
    assert isinstance(first, OptionInstrument)
    assert first.option_type == "call"
    assert first.strike == 100000.0
    assert first.expiration_timestamp == 1750982400000
    assert first.is_active is True
    # Raw entry retained for callers that need extra fields.
    assert first.details["base_currency"] == "BTC"


def test_list_option_instruments_linear_uses_usdc_umbrella_and_filters() -> None:
    """SOL/XRP/TRX/AVAX are USDC-settled: query the USDC umbrella, prefix-filter."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/public/get_instruments"
        # Linear underliers query the USDC umbrella, NOT currency=SOL.
        assert request.url.params["currency"] == "USDC"
        assert request.url.params["kind"] == "option"
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "instrument_name": "SOL_USDC-30MAY26-70-C",
                        "base_currency": "SOL",
                        "option_type": "call",
                        "strike": 70.0,
                        "expiration_timestamp": 1748563200000,
                        "is_active": True,
                    },
                    {
                        "instrument_name": "SOL_USDC-30MAY26-72-P",
                        "base_currency": "SOL",
                        "option_type": "put",
                        "strike": 72.0,
                        "expiration_timestamp": 1748563200000,
                        "is_active": True,
                    },
                    # Other bases in the same umbrella must be filtered out.
                    {"instrument_name": "XRP_USDC-30MAY26-1d15-C", "base_currency": "XRP"},
                    {"instrument_name": "BTC_USDC-30MAY26-70000-C", "base_currency": "BTC"},
                ],
            },
        )

    instruments = DeribitClient(http_client=_client(handler)).list_option_instruments("sol")
    assert [i.instrument_name for i in instruments] == [
        "SOL_USDC-30MAY26-70-C",
        "SOL_USDC-30MAY26-72-P",
    ]
    assert all(i.base_currency == "SOL" for i in instruments)


def test_list_option_instruments_unsupported_currency_returns_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("should not hit the network for an unsupported currency")

    assert DeribitClient(http_client=_client(handler)).list_option_instruments("DOGE") == []


def test_supported_currencies_and_settlement_model() -> None:
    assert DeribitClient.supported_currencies() == ["BTC", "ETH", "SOL", "XRP", "TRX", "AVAX"]
    assert DeribitClient.settlement_model("BTC") == "inverse"
    assert DeribitClient.settlement_model("eth") == "inverse"
    assert DeribitClient.settlement_model("sol") == "linear_usdc"
    assert DeribitClient.settlement_model("AVAX") == "linear_usdc"
    assert DeribitClient.settlement_model("DOGE") is None


def test_get_option_ticker_extracts_mark_iv_greeks_and_book() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/public/ticker"
        assert request.url.params["instrument_name"] == "BTC-27JUN25-100000-C"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "result": {
                    "instrument_name": "BTC-27JUN25-100000-C",
                    "mark_price": 0.0825,
                    "mark_iv": 54.2,
                    "underlying_price": 98250.0,
                    "best_bid_price": 0.081,
                    "best_ask_price": 0.084,
                    "open_interest": 1234.0,
                    "greeks": {
                        "delta": 0.5123,
                        "gamma": 0.00002,
                        "theta": -45.6,
                        "vega": 120.4,
                        "rho": 33.1,
                    },
                },
            },
        )

    ticker = DeribitClient(http_client=_client(handler)).get_option_ticker("BTC-27JUN25-100000-C")
    assert isinstance(ticker, OptionTicker)
    assert ticker.mark_price == 0.0825
    assert ticker.mark_iv == 54.2
    assert ticker.underlying_price == 98250.0
    assert ticker.delta == 0.5123
    assert ticker.vega == 120.4
    assert ticker.rho == 33.1
    assert ticker.bid_price == 0.081
    assert ticker.ask_price == 0.084
    assert ticker.open_interest == 1234.0
    # Educational framing rides along on the structured shape.
    assert ticker.disclaimer == DISCLAIMER
    as_dict = ticker.to_dict()
    assert as_dict["greeks"]["gamma"] == 0.00002
    assert as_dict["disclaimer"] == DISCLAIMER


def test_get_option_ticker_missing_greeks_degrades_to_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "instrument_name": "ETH-27JUN25-4000-C",
                    "mark_price": None,
                    "underlying_price": 3500.0,
                }
            },
        )

    ticker = DeribitClient(http_client=_client(handler)).get_option_ticker("ETH-27JUN25-4000-C")
    assert ticker is not None
    assert ticker.mark_price is None
    assert ticker.delta is None
    assert ticker.underlying_price == 3500.0


def test_get_option_ticker_blank_name_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("should not hit the network for a blank instrument name")

    assert DeribitClient(http_client=_client(handler)).get_option_ticker("  ") is None


def test_get_index_price_maps_currency_to_index_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/public/get_index_price"
        assert request.url.params["index_name"] == "sol_usd"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "result": {"index_price": 142.37, "estimated_delivery_price": 142.37},
            },
        )

    price = DeribitClient(http_client=_client(handler)).get_index_price("SOL")
    assert price == 142.37


def test_get_index_price_linear_underlier_maps_to_usd_index() -> None:
    """A USDC-settled underlier still resolves spot via its ``<code>_usd`` index."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["index_name"] == "trx_usd"
        return httpx.Response(200, json={"result": {"index_price": 0.3428}})

    assert DeribitClient(http_client=_client(handler)).get_index_price("TRX") == 0.3428


def test_get_index_price_unsupported_currency_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never called
        raise AssertionError("should not hit the network for an unsupported currency")

    assert DeribitClient(http_client=_client(handler)).get_index_price("DOGE") is None


def test_http_error_degrades_gracefully() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"code": 10000, "message": "down"}})

    client = DeribitClient(http_client=_client(handler))
    assert client.list_option_instruments("BTC") == []
    assert client.get_option_ticker("BTC-27JUN25-100000-C") is None
    assert client.get_index_price("BTC") is None


def test_jsonrpc_error_envelope_degrades_gracefully() -> None:
    # A 200 response can still carry a JSON-RPC error envelope.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "error": {"code": 11044, "message": "not_open_order"},
            },
        )

    client = DeribitClient(http_client=_client(handler))
    assert client.list_option_instruments("ETH") == []
    assert client.get_option_ticker("ETH-27JUN25-4000-C") is None
    assert client.get_index_price("ETH") is None

