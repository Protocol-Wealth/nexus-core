# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the educational options-overlay REST surface.

Hermetic — a fake market provider supplies spot + history, and a fake Deribit
client supplies crypto option data. No network.
"""

from __future__ import annotations

import time

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

    def get_index_price(self, currency: str) -> float | None:
        return 100000.0 if currency.upper() in self._SUPPORTED else None

    def list_option_instruments(self, currency: str) -> list[OptionInstrument]:
        # Future-dated so (ts - now) lands inside a chain's day window; mix of
        # ITM (90k) and OTM (110k/120k) calls so the OTM filter has work to do.
        now = time.time()
        cur = currency.upper()

        def ts(days: int) -> int:
            return int((now + days * 86_400) * 1000)

        return [
            OptionInstrument(f"{cur}-A-90000-C", cur, "call", 90000.0, ts(30), True),
            OptionInstrument(f"{cur}-A-110000-C", cur, "call", 110000.0, ts(30), True),
            OptionInstrument(f"{cur}-B-120000-C", cur, "call", 120000.0, ts(45), True),
        ]

    def get_option_ticker(self, instrument_name: str) -> OptionTicker | None:
        if "UNKNOWN" in instrument_name:
            return None
        # Delta thins out for higher strikes so select_by_delta has a gradient.
        delta = 0.20 if "120000" in instrument_name else 0.35
        return OptionTicker(
            instrument_name=instrument_name,
            mark_price=0.05,
            mark_iv=62.5,
            underlying_price=101000.0,
            delta=delta,
        )


class _RegimeResult:
    regime = "GROWTH"  # -> generic "expansion"


class _FakeRegime:
    def classify(self) -> _RegimeResult:
        return _RegimeResult()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(
        build_options_router(
            market=_FakeMarket(), deribit=_FakeDeribit(), regime_engine=_FakeRegime()
        )
    )
    return TestClient(app)


def test_price_call() -> None:
    r = _client().get(
        "/api/options/price", params={"spot": 100, "strike": 105, "days": 30, "vol": 0.25}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["price"] > 0
    assert set(body["greeks"]) == {"delta", "gamma", "theta", "vega", "rho"}
    assert 0.0 <= body["greeks"]["delta"] <= 1.0
    assert "not investment, tax, legal, or financial advice" in body["disclaimer"].lower()
    assert r.headers["cache-control"] == "public, max-age=300"


def test_covered_call_overlay() -> None:
    r = _client().get(
        "/api/options/overlay/covered-call", params={"symbol": "AAPL", "strike": 105, "days": 30}
    )
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
    r = _client().get(
        "/api/options/overlay/covered-call", params={"symbol": "UNKNOWN", "strike": 105, "days": 30}
    )
    assert r.status_code == 404


def test_crypto_currencies() -> None:
    r = _client().get("/api/options/crypto/currencies")
    assert r.status_code == 200
    body = r.json()
    assert body["currencies"] == ["BTC", "ETH", "SOL", "XRP", "TRX", "AVAX"]
    assert body["settlement"]["BTC"] == "inverse"
    assert body["settlement"]["SOL"] == "linear_usdc"
    assert "not investment, tax, legal, or financial advice" in body["disclaimer"].lower()


def test_crypto_instruments() -> None:
    r = _client().get("/api/options/crypto/btc/instruments")
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "BTC"
    assert body["count"] == 3
    assert body["instruments"][0]["base_currency"] == "BTC"


def test_crypto_instruments_linear_currency() -> None:
    r = _client().get("/api/options/crypto/sol/instruments")
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "SOL"
    assert body["count"] == 3


def test_crypto_instruments_unsupported_404() -> None:
    assert _client().get("/api/options/crypto/DOGE/instruments").status_code == 404


def test_crypto_ticker() -> None:
    r = _client().get("/api/options/crypto/instrument/BTC-27JUN26-100000-C")
    assert r.status_code == 200
    body = r.json()
    assert body["mark_iv"] == 62.5
    assert body["delta"] == 0.35


def test_crypto_ticker_unknown_404() -> None:
    assert _client().get("/api/options/crypto/instrument/UNKNOWN-INSTRUMENT").status_code == 404


# ── Crypto covered-call overwriting suite ──


def test_crypto_covered_call_inverse_route() -> None:
    r = _client().get(
        "/api/options/crypto/btc/covered-call",
        params={"strike": 120000, "days": 30, "coins": 2, "premium": 0.02},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["settlement"] == "inverse"
    assert body["spot"] == 100000.0  # live index from the fake
    assert body["premium_usd"] == 2000.0  # 0.02 BTC × 100k
    assert body["static_yield_pct"] == 2.0
    assert body["coin_income"] == 0.04  # grows the stack
    assert "not investment" in body["disclaimer"].lower()


def test_crypto_covered_call_linear_route() -> None:
    r = _client().get(
        "/api/options/crypto/sol/covered-call",
        params={"strike": 120000, "days": 30, "coins": 10, "premium": 5},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["settlement"] == "linear"
    assert body["premium_coin"] is None  # USDC-settled


def test_crypto_covered_call_unsupported_404() -> None:
    assert (
        _client()
        .get(
            "/api/options/crypto/doge/covered-call",
            params={"strike": 1, "days": 30},
        )
        .status_code
        == 404
    )


def test_crypto_covered_call_chain_ranks() -> None:
    r = _client().get(
        "/api/options/crypto/btc/covered-call-chain",
        params={"max_days": 60, "top": 5, "target_delta": 0.2},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["settlement"] == "inverse"
    assert body["spot"] == 100000.0
    assert body["considered"] == 2  # 110k + 120k OTM; 90k ITM dropped
    ranked = body["ranked"]
    assert ranked and ranked[0]["annualized_yield_pct"] >= ranked[-1]["annualized_yield_pct"]
    # target_delta 0.2 matches the 120k strike (delta 0.20 in the fake).
    assert body["selected_by_delta"]["strike"] == 120000.0


def test_crypto_iv_term_structure_route() -> None:
    r = _client().get("/api/options/crypto/btc/iv-term-structure", params={"max_days": 90})
    assert r.status_code == 200
    body = r.json()
    # Fake chain: 110k @30d + 120k @45d, both mark_iv 62.5 -> 2 tenors, flat curve.
    assert [p["expiry_days"] for p in body["points"]] == [30, 45]
    assert all(p["atm_iv"] == 62.5 for p in body["points"])
    assert body["shape"] == "flat"


def test_crypto_vol_skew_route() -> None:
    r = _client().get("/api/options/crypto/btc/vol-skew", params={"target_days": 30})
    assert r.status_code == 200
    body = r.json()
    # Fake chain at 30d (90k + 110k in the [0.9, 2.0]×spot band); 120k is 45d.
    assert body["expiry_days"] == 30
    assert len(body["points"]) == 2
    assert body["skew_25d_pts"] == 0.0  # both IV 62.5 in the fake
    assert body["richest_strike"] == 110000.0  # the OTM call
    assert all(p["vega"] is not None for p in body["points"])


def test_crypto_regime_overwrite_route() -> None:
    r = _client().get("/api/options/crypto/btc/regime-overwrite", params={"max_days": 60})
    assert r.status_code == 200
    body = r.json()
    assert body["regime"] == "expansion"  # fake regime GROWTH -> expansion
    assert body["delta_multiplier"] == 1.20
    assert body["adjusted_target_delta"] == 0.30  # 0.25 × 1.2
    # Expansion target 0.30 -> the 0.35-delta 110k call (closest in the fake chain).
    assert body["selected"]["strike"] == 110000.0
    assert body["covered_call"]["annualized_yield_pct"] > 0


def test_crypto_protective_put_route() -> None:
    r = _client().get(
        "/api/options/crypto/btc/protective-put",
        params={"strike": 80000, "days": 30, "coins": 2, "premium": 0.015},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["settlement"] == "inverse"
    assert body["premium_usd"] == 1500.0
    assert body["protection_level_pct"] == 20.0
    assert body["cost_pct"] == 1.5
    assert body["floor_usd"] == 80000.0


def test_crypto_collar_route() -> None:
    r = _client().get(
        "/api/options/crypto/btc/collar",
        params={
            "put_strike": 80000,
            "call_strike": 120000,
            "days": 30,
            "coins": 2,
            "put_premium": 0.015,
            "call_premium": 0.02,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["settlement"] == "inverse"
    assert body["net_premium_usd"] == 500.0
    assert body["upside_cap_pct"] == 20.0
    assert body["downside_protection_pct"] == 20.0


def test_crypto_collar_linear_route() -> None:
    r = _client().get(
        "/api/options/crypto/sol/collar",
        params={"put_strike": 80000, "call_strike": 120000, "days": 30},
    )
    assert r.status_code == 200
    assert r.json()["settlement"] == "linear"


def test_crypto_ladder_route() -> None:
    r = _client().post(
        "/api/options/crypto/btc/ladder",
        json={
            "total_coins": 10,
            "legs": [
                {"expiry_days": 30, "strike": 120000, "coins": 4, "premium": 0.02},
                {"expiry_days": 60, "strike": 130000, "coins": 3, "premium": 0.03},
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["settlement"] == "inverse"
    assert body["coverage_pct"] == 70.0
    assert body["total_premium_usd"] == 17000.0


def test_crypto_ladder_bad_body_400() -> None:
    r = _client().post("/api/options/crypto/btc/ladder", json={"legs": []})
    assert r.status_code == 400


def test_crypto_roll_route() -> None:
    r = _client().post(
        "/api/options/crypto/btc/roll",
        json={
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
    assert r.status_code == 200
    body = r.json()
    assert body["roll_type"] == "roll up and out"
    assert body["net_credit_usd"] == -2000.0


def test_crypto_book_mtm_route() -> None:
    r = _client().post(
        "/api/options/crypto/btc/book/mtm",
        json={
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
    assert r.status_code == 200
    body = r.json()
    assert body["total_pnl_usd"] == 1000.0
    assert body["net_delta_with_underlying"] < 1.0


def test_crypto_book_scenario_route() -> None:
    r = _client().post(
        "/api/options/crypto/btc/book/scenario",
        json={
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
    assert r.status_code == 200
    cells = r.json()["cells"]
    assert len(cells) == 3
    up = next(c for c in cells if c["spot_shock_pct"] == 25.0)
    assert up["short_calls_itm"] == 1
    assert up["underlying_pnl_usd"] == 25000.0
