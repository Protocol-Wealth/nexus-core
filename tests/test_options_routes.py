# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the educational options-overlay REST surface.

Hermetic — a fake market provider supplies spot + history, and a fake Deribit
client supplies crypto option data. No network.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.options import build_options_router
from nexus_core.data.derivatives import OptionInstrument, OptionTicker
from nexus_core.data.providers import PriceBar, Quote


class _FakeMarket:
    def get_quote(self, symbol: str) -> Quote | None:
        if symbol == "UNKNOWN":
            return None
        return Quote(symbol=symbol, price=100.0, timestamp="2026-01-05T00:00:00Z")

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        # ~40 gently drifting closes so volatility estimation yields a real number.
        closes = [100.0 + (i % 5) - 2 for i in range(40)]
        return [
            PriceBar(timestamp=f"2026-01-{i + 1:02d}", open=c, high=c + 1, low=c - 1, close=c)
            for i, c in enumerate(closes)
        ]


class _FakeDeribit:
    _SUPPORTED = ["BTC", "ETH", "SOL", "XRP", "TRX", "AVAX"]

    def supported_currencies(self) -> list[str]:
        return list(self._SUPPORTED)

    def settlement_model(self, currency: str) -> str | None:
        cur = currency.upper()
        if cur not in self._SUPPORTED:
            return None
        return "inverse" if cur in ("BTC", "ETH") else "linear_usdc"

    def list_option_instruments(self, currency: str) -> list[OptionInstrument]:
        return [
            OptionInstrument(
                instrument_name=f"{currency}-27JUN26-100000-C",
                base_currency=currency,
                option_type="call",
                strike=100000.0,
                is_active=True,
            )
        ]

    def get_option_ticker(self, instrument_name: str) -> OptionTicker | None:
        if "UNKNOWN" in instrument_name:
            return None
        return OptionTicker(
            instrument_name=instrument_name,
            mark_price=0.05,
            mark_iv=62.5,
            underlying_price=101000.0,
            delta=0.42,
        )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(build_options_router(market=_FakeMarket(), deribit=_FakeDeribit()))
    return TestClient(app)


def test_price_call() -> None:
    r = _client().get("/api/options/price", params={"spot": 100, "strike": 105, "days": 30, "vol": 0.25})
    assert r.status_code == 200
    body = r.json()
    assert body["price"] > 0
    assert set(body["greeks"]) == {"delta", "gamma", "theta", "vega", "rho"}
    assert 0.0 <= body["greeks"]["delta"] <= 1.0
    assert "not investment advice" in body["disclaimer"].lower()
    assert r.headers["cache-control"] == "public, max-age=300"


def test_covered_call_overlay() -> None:
    r = _client().get("/api/options/overlay/covered-call", params={"symbol": "AAPL", "strike": 105, "days": 30})
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "AAPL"
    assert body["spot"] == 100.0
    assert "max_profit" in body and "disclaimer" in body


def test_cash_secured_put_overlay() -> None:
    r = _client().get(
        "/api/options/overlay/cash-secured-put",
        params={"symbol": "AAPL", "strike": 95, "days": 30, "premium": 2.0},
    )
    assert r.status_code == 200
    assert "max_loss" in r.json()


def test_collar_overlay() -> None:
    r = _client().get(
        "/api/options/overlay/collar",
        params={"symbol": "AAPL", "put_strike": 95, "call_strike": 110, "days": 45},
    )
    assert r.status_code == 200
    assert r.json()["symbol"] == "AAPL"


def test_unknown_symbol_404() -> None:
    r = _client().get("/api/options/overlay/covered-call", params={"symbol": "UNKNOWN", "strike": 105, "days": 30})
    assert r.status_code == 404


def test_crypto_currencies() -> None:
    r = _client().get("/api/options/crypto/currencies")
    assert r.status_code == 200
    body = r.json()
    assert body["currencies"] == ["BTC", "ETH", "SOL", "XRP", "TRX", "AVAX"]
    assert body["settlement"]["BTC"] == "inverse"
    assert body["settlement"]["SOL"] == "linear_usdc"
    assert "not investment advice" in body["disclaimer"].lower()


def test_crypto_instruments() -> None:
    r = _client().get("/api/options/crypto/btc/instruments")
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "BTC"
    assert body["count"] == 1
    assert body["instruments"][0]["base_currency"] == "BTC"


def test_crypto_instruments_linear_currency() -> None:
    r = _client().get("/api/options/crypto/sol/instruments")
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "SOL"
    assert body["count"] == 1


def test_crypto_instruments_unsupported_404() -> None:
    assert _client().get("/api/options/crypto/DOGE/instruments").status_code == 404


def test_crypto_ticker() -> None:
    r = _client().get("/api/options/crypto/instrument/BTC-27JUN26-100000-C")
    assert r.status_code == 200
    body = r.json()
    assert body["mark_iv"] == 62.5
    assert body["delta"] == 0.42


def test_crypto_ticker_unknown_404() -> None:
    assert (
        _client().get("/api/options/crypto/instrument/UNKNOWN-INSTRUMENT").status_code == 404
    )
