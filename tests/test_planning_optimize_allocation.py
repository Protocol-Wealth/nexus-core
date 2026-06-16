# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the ``optimize_allocation`` planning tool (via the gateway).

Exercises the real optimizer, so the module skips when PyPortfolioOpt is absent
(it is in the ``serve`` extra, hence installed in CI).
"""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("pypfopt")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from nexus_core.app.planning import build_planning_router  # noqa: E402
from nexus_core.data.providers import PriceBar  # noqa: E402

_N_BARS = 320
_DATES = [f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}T00:00:00Z" for i in range(_N_BARS)]

#: Per-ticker daily volatility — bonds low, bitcoin high — so the optimizer has a
#: real risk/return tradeoff to exploit (otherwise every risk profile collapses to
#: the same achievable volatility). Default for any unlisted proxy.
_VOL_BY_SYMBOL = {
    "AGG": 0.003,
    "GOVT": 0.003,
    "TIP": 0.004,
    "HYG": 0.006,
    "GLD": 0.010,
    "SPY": 0.011,
    "VTI": 0.012,
    "VXUS": 0.012,
    "EFA": 0.012,
    "DBC": 0.012,
    "IWM": 0.014,
    "VNQ": 0.014,
    "VWO": 0.016,
    "BTC-USD": 0.035,
}


def _deterministic_closes(symbol: str) -> list[float]:
    """A reproducible positive price series with a per-ticker volatility.

    Each day's return blends a shared market factor (so assets are positively but
    imperfectly correlated) with deterministic idiosyncratic noise, scaled by the
    ticker's volatility.
    """
    seed = sum(ord(c) for c in symbol)
    vol = _VOL_BY_SYMBOL.get(symbol, 0.010)
    base = 80.0 + (seed % 60)
    price = base
    closes: list[float] = []
    for i in range(_N_BARS):
        market = math.sin(i * 0.08)
        idio = (((i * 1103515245 + seed * 2654435761 + 1) % 2**31) / 2**31) - 0.5
        ret = 0.0003 + vol * (0.4 * market + 1.2 * idio)
        price = max(1.0, price * (1.0 + ret))
        closes.append(price)
    return closes


class _FakeMarket:
    """Deterministic daily closes for any requested proxy ticker."""

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        closes = _deterministic_closes(symbol)
        return [
            PriceBar(timestamp=d, open=c, high=c + 1, low=c - 1, close=c, volume=10.0)
            for d, c in zip(_DATES, closes, strict=True)
        ]


class _FakeRegimeEngine:
    def __init__(self, regime: str = "GROWTH") -> None:
        self._regime = regime

    def classify(self) -> SimpleNamespace:
        return SimpleNamespace(regime=self._regime, confidence_score=80)


def _client(regime: str = "GROWTH") -> TestClient:
    app = FastAPI()
    app.include_router(
        build_planning_router(market=_FakeMarket(), regime_engine=_FakeRegimeEngine(regime))
    )
    return TestClient(app)


_SUBSET = ["us_equity", "us_bonds", "gold", "bitcoin"]


def _post(body: dict[str, Any], *, regime: str = "GROWTH") -> Any:
    return _client(regime).post("/mcp/tools/optimize_allocation", json=body)


def test_risk_profile_allocation_is_well_formed() -> None:
    r = _post({"assetClassIds": _SUBSET, "riskProfile": "moderate"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["objective"] == "max_quadratic_utility"
    assert body["objectiveSource"] == "riskProfile"
    assert body["riskProfile"] == "moderate"
    assert body["riskAversion"] == 3.0
    # Weights are a valid, fully-invested, long-only allocation.
    assert sum(body["weights"].values()) == pytest.approx(1.0, abs=1e-3)
    assert all(0.0 <= w <= 1.0 for w in body["weights"].values())
    assert {ac["id"] for ac in body["assetClasses"]} == set(_SUBSET)
    assert body["disclaimer"]  # gateway attaches the MC disclaimer
    assert body["contractVersion"] == "0.1.0"


def test_conservative_is_lower_vol_than_aggressive() -> None:
    cons = _post({"assetClassIds": _SUBSET, "riskProfile": "conservative"}).json()
    aggr = _post({"assetClassIds": _SUBSET, "riskProfile": "aggressive"}).json()
    assert cons["expectedVolatility"] <= aggr["expectedVolatility"]
    # Aggressive should not under-weight the highest-return asset vs conservative.
    assert aggr["expectedReturn"] >= cons["expectedReturn"]


def test_default_is_regime_selected() -> None:
    body = _post({"assetClassIds": _SUBSET}, regime="GROWTH").json()
    # GROWTH → max_sharpe per the regime→optimizer map.
    assert body["objectiveSource"] == "regime"
    assert body["objective"] == "max_sharpe"
    assert body["regime"] == "GROWTH"
    assert "regimeNote" in body


def test_transition_regime_falls_back_from_hrp() -> None:
    # TRANSITION maps to 'hrp', which has no moments-only form → min_volatility.
    body = _post({"assetClassIds": _SUBSET}, regime="TRANSITION").json()
    assert body["objective"] == "min_volatility"
    assert body["regime"] == "TRANSITION"


def test_explicit_objective_overrides_regime() -> None:
    body = _post({"assetClassIds": _SUBSET, "objective": "min_volatility"}).json()
    assert body["objective"] == "min_volatility"
    assert body["objectiveSource"] == "explicit"


def test_historical_return_model() -> None:
    body = _post({"assetClassIds": _SUBSET, "returnModel": "historical"}).json()
    assert body["returnModel"] == "historical"
    assert body["expectedReturn"] is not None


def test_objective_and_risk_profile_conflict_is_400() -> None:
    r = _post({"assetClassIds": _SUBSET, "objective": "max_sharpe", "riskProfile": "moderate"})
    assert r.status_code == 400
    assert "either objective or riskProfile" in r.text


def test_unknown_asset_class_is_400() -> None:
    r = _post({"assetClassIds": ["us_equity", "martian_reits"]})
    assert r.status_code == 400
    assert "unknown asset class" in r.text


def test_single_asset_is_400() -> None:
    r = _post({"assetClassIds": ["us_equity"]})
    assert r.status_code == 400
    assert "at least 2 asset classes" in r.text


def test_infeasible_weight_bounds_is_422() -> None:
    # 4 assets, upper bound 0.2 → max investable 0.8 < 1 → infeasible budget.
    r = _post({"assetClassIds": _SUBSET, "weightBounds": [0.0, 0.2]})
    assert r.status_code == 422
    assert "too low" in r.text


def test_bad_objective_is_400() -> None:
    r = _post({"assetClassIds": _SUBSET, "objective": "moon_shot"})
    assert r.status_code == 400


def test_full_universe_defaults() -> None:
    # Omitted assetClassIds → the full published universe; still well-formed.
    body = _post({"riskProfile": "moderate_conservative"}).json()
    assert sum(body["weights"].values()) == pytest.approx(1.0, abs=1e-3)
    assert body["riskAversion"] == 5.0


def test_lower_weight_bound_too_high_is_422() -> None:
    # 4 assets, lower bound 0.4 → minimum weights sum to 1.6 > 1 → infeasible.
    r = _post({"assetClassIds": _SUBSET, "weightBounds": [0.4, 1.0]})
    assert r.status_code == 422
    assert "too high" in r.text


class _FlatAssetMarket(_FakeMarket):
    """Like the base market, but one ticker has a perfectly flat price (zero vol)."""

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        if symbol == "AGG":  # the us_bonds proxy
            return [
                PriceBar(timestamp=d, open=100.0, high=100.0, low=100.0, close=100.0, volume=1.0)
                for d in _DATES
            ]
        return super().get_price_history(symbol, days=days, interval=interval)


def test_zero_volatility_asset_is_422_not_500() -> None:
    # A zero-variance asset would make the correlation matrix 0/0 (NaN); the tool
    # must reject it cleanly rather than letting NaN reach the solver / renderer.
    app = FastAPI()
    app.include_router(
        build_planning_router(market=_FlatAssetMarket(), regime_engine=_FakeRegimeEngine())
    )
    r = TestClient(app).post(
        "/mcp/tools/optimize_allocation",
        json={"assetClassIds": _SUBSET, "objective": "min_volatility"},
    )
    assert r.status_code == 422
    assert "no price variation" in r.text
