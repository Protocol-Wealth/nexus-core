# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for capital_market_assumptions + the asset universe."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.planning import CONTRACT_VERSION, build_planning_router
from nexus_core.app.planning.universe import ASSET_UNIVERSE, universe_ids
from nexus_core.data.providers import PriceBar


class _FakeMarket:
    """Deterministic positive closes for ANY ticker over a fixed date grid."""

    _DATES = [f"2026-02-{d:02d}T00:00:00Z" for d in range(1, 16)]  # 15 days

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        seed = sum(ord(ch) for ch in symbol)
        closes = [100.0 + (seed % 7) + i * 0.5 + ((i * seed) % 5) for i in range(len(self._DATES))]
        return [
            PriceBar(timestamp=d, open=c, high=c + 1, low=c - 1, close=c, volume=10.0)
            for d, c in zip(self._DATES, closes, strict=True)
        ]


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(build_planning_router(market=_FakeMarket()))
    return TestClient(app)


def _post(body: dict[str, object]):
    return _client().post("/mcp/tools/capital_market_assumptions", json=body)


def test_universe_has_lambda_and_returns_on_every_asset() -> None:
    assert universe_ids()  # non-empty
    for assumption in ASSET_UNIVERSE.values():
        assert 0.0 <= assumption.lambda_ <= 1.0
        assert assumption.expected_return > 0.0
        assert assumption.ticker and assumption.label


def test_cma_specific_ids_shape() -> None:
    r = _post({"contractVersion": "0.1.0", "assetClassIds": ["us_equity", "us_bonds"], "asOf": None})
    assert r.status_code == 200
    body = r.json()
    assert body["contractVersion"] == CONTRACT_VERSION
    assert body["asOf"] == "2026-02-15"
    classes = {a["id"]: a for a in body["assetClasses"]}
    assert set(classes) == {"us_equity", "us_bonds"}
    for asset_id, a in classes.items():
        assert a["label"] == ASSET_UNIVERSE[asset_id].label
        assert a["expectedReturn"] == ASSET_UNIVERSE[asset_id].expected_return
        assert a["lambda"] == ASSET_UNIVERSE[asset_id].lambda_  # populated for emf_regime
        assert a["volatility"] >= 0.0


def test_cma_correlations_are_dropin_for_monte_carlo() -> None:
    body = _post({"assetClassIds": ["us_equity", "us_bonds", "gold"]}).json()
    corr = body["correlations"]
    ids = [a["id"] for a in body["assetClasses"]]
    assert set(corr) == set(ids)  # same keys as assetClasses
    for i in ids:
        assert corr[i][i] == 1.0
        for j in ids:
            assert corr[i][j] == corr[j][i]  # symmetric
            assert -1.0 <= corr[i][j] <= 1.0


def test_cma_default_universe_when_ids_omitted() -> None:
    body = _post({"contractVersion": "0.1.0"}).json()
    returned = {a["id"] for a in body["assetClasses"]}
    assert returned == set(universe_ids())  # full default universe
    assert all("lambda" in a for a in body["assetClasses"])


def test_cma_unknown_id_returns_400() -> None:
    r = _post({"assetClassIds": ["us_equity", "unobtanium"]})
    assert r.status_code == 400
    assert "unobtanium" in r.text


def test_cma_asof_filters_history() -> None:
    body = _post({"assetClassIds": ["us_equity"], "asOf": "2026-02-10"}).json()
    assert body["asOf"] == "2026-02-10"  # capped to the requested date
