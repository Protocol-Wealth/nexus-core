# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the /api/layer EMF durability-layer surface.

Hermetic — a fake market provider is injected into ``create_app`` and
``build_fundamentals`` is monkeypatched, so no SEC or market request is made.

Covers the four ways an asset reaches a layer: an explicit ticker-map hit, an
asset-class route (BTC-USD -> L1), a sector/industry keyword rule, and a sector
default — plus the honest fallback for an unknown ticker (UNCLASSIFIED, never a
silent default layer).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexus_core.app.main import create_app
from nexus_core.data.providers import PriceBar, Quote
from nexus_core.engine.scoring.emf.lambda_decay import LAYER_DECAY_THRESHOLDS
from nexus_core.engine.scoring.emf.layers import (
    LAYER_CODES,
    LAYER_HORIZONS,
    LAYER_NAMES,
)


class _FakeMarket:
    def get_quote(self, symbol: str) -> Quote | None:
        return Quote(symbol=symbol, price=100.0, timestamp="2026-01-05T00:00:00Z")

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        return [
            PriceBar(
                timestamp="2026-01-01", open=1.0, high=1.0, low=1.0, close=1.0, volume=1.0
            )
        ]


def _client() -> TestClient:
    return TestClient(create_app(enable_mcp=False, market=_FakeMarket()))


def _no_fundamentals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nexus_core.app.layers.build_fundamentals", lambda ticker, **kw: None)


def _fundamentals(monkeypatch: pytest.MonkeyPatch, **fields: Any) -> None:
    monkeypatch.setattr("nexus_core.app.layers.build_fundamentals", lambda ticker, **kw: fields)


def test_explicit_ticker_map_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """NVDA is an explicit L3 assignment — the ticker map wins over everything."""
    _no_fundamentals(monkeypatch)
    r = _client().get("/api/layer/nvda")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "NVDA"
    assert body["layer"] == "L3"
    assert body["layer_key"] == "L3_engine"
    assert body["name"] == "Engine"
    assert body["horizon"] == "5-10 yr"
    assert body["horizon_years"] == [5, 10]
    assert body["decay_threshold"] == LAYER_DECAY_THRESHOLDS["L3"]
    assert body["classification"]["source"] == "ticker_map"
    assert body["classification"]["matched_on"] == "NVDA"
    assert body["classification"]["rule"]
    # The layer's target weight in each of the five regimes.
    assert body["regime_weights"] == {"G": 25, "T": 20, "H": 15, "D": 15, "R": 15}
    assert "not investment, tax, legal, or financial advice" in body["disclaimer"].lower()
    assert r.headers["cache-control"] == "public, max-age=3600"


def test_asset_class_route_btc(monkeypatch: pytest.MonkeyPatch) -> None:
    """BTC-USD has no SEC fundamentals; asset-class routing lands it in L1."""
    _no_fundamentals(monkeypatch)
    body = _client().get("/api/layer/BTC-USD").json()
    assert body["layer"] == "L1"
    assert body["name"] == "Foundation"
    assert body["horizon"] == "40-60 yr"
    assert body["classification"]["source"] == "asset_class_crypto"
    assert body["classification"]["matched_on"] == "BTC-USD"


def test_asset_class_route_sector_etf(monkeypatch: pytest.MonkeyPatch) -> None:
    _no_fundamentals(monkeypatch)
    body = _client().get("/api/layer/XLE").json()
    assert body["layer"] == "L1"
    assert body["classification"]["source"] == "asset_class_sector_etf"


def test_sector_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unmapped industrial with no keyword hit falls to its sector's default."""
    _fundamentals(monkeypatch, sector="Industrials", industry="Farm Machinery")
    body = _client().get("/api/layer/DE").json()
    assert body["layer"] == "L2"
    assert body["name"] == "Backbone"
    assert body["horizon"] == "15-30 yr"
    assert body["sector"] == "Industrials"
    assert body["classification"]["source"] == "sector_default"
    assert body["classification"]["matched_on"] == "industrials"


def test_sector_industry_keyword_via_query_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Caller-supplied sector/industry skips the SEC lookup and drives the keyword rule."""

    def _boom(ticker: str, **kwargs: Any) -> dict[str, Any]:  # pragma: no cover - must not run
        raise AssertionError("query override must not hit the fundamentals lookup")

    monkeypatch.setattr("nexus_core.app.layers.build_fundamentals", _boom)
    body = _client().get("/api/layer/UNLISTEDCO?industry=Semiconductor%20Equipment").json()
    assert body["layer"] == "L3"
    assert body["classification"]["source"] == "sector_industry_keyword"
    assert body["classification"]["matched_on"] == "industry:semiconductor"
    assert body["industry"] == "Semiconductor Equipment"


def test_unknown_ticker_is_unclassified(monkeypatch: pytest.MonkeyPatch) -> None:
    """No positive match → UNCLASSIFIED, never a silent default layer."""
    _no_fundamentals(monkeypatch)
    body = _client().get("/api/layer/ZZZZ").json()
    assert body["layer"] == "UNCLASSIFIED"
    assert body["layer_key"] is None
    assert body["name"] is None
    assert body["horizon"] is None
    assert body["decay_threshold"] is None
    assert body["regime_weights"] is None
    assert body["classification"]["source"] == "unclassified"
    assert body["classification"]["matched_on"] is None
    # A broad-market ETF is deliberately unclassifiable too — a diversified index
    # has no single durability layer.
    assert _client().get("/api/layer/SPY").json()["layer"] == "UNCLASSIFIED"


def test_layer_catalog_publishes_the_stack() -> None:
    r = _client().get("/api/layers")
    assert r.status_code == 200
    body = r.json()
    layers = body["layers"]
    assert [entry["layer"] for entry in layers] == list(LAYER_CODES)
    # Every layer publishes a name, a horizon, and its λ ceiling.
    for entry in layers:
        code = entry["layer"]
        assert entry["name"] == LAYER_NAMES[code]
        assert entry["horizon"] == LAYER_HORIZONS[code]
        assert entry["decay_threshold"] == LAYER_DECAY_THRESHOLDS[code]
        assert set(entry["regime_weights"]) == {"G", "T", "H", "D", "R"}
    by_code = {entry["layer"]: entry for entry in layers}
    # The code key stays `datatoll`; the published display name is cleaner.
    assert by_code["L4"]["layer_key"] == "L4_datatoll"
    assert by_code["L4"]["name"] == "Data Infrastructure"
    assert by_code["L4"]["horizon"] == "7-12 yr"
    # L7 is held for a catalyst with a defined exit, not for a durability window.
    assert by_code["L7"]["horizon"] == "tactical"
    assert by_code["L7"]["horizon_years"] is None
    assert "not investment, tax, legal, or financial advice" in body["disclaimer"].lower()
