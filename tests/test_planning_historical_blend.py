# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the historical-blend planning tool."""

from __future__ import annotations

import asyncio
import json
import math
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from nexus_core.app.planning import build_planning_router
from nexus_core.data.providers import PriceBar
from nexus_core.engine.planning import historical_blend, historical_blend_result_schema


class _FakeMarket:
    """Deterministic month-end closes for the public proxy tickers used by tests."""

    _DATES = [
        "2024-12-31T00:00:00Z",
        "2025-01-31T00:00:00Z",
        "2025-02-28T00:00:00Z",
        "2025-03-31T00:00:00Z",
        "2025-04-30T00:00:00Z",
        "2025-05-31T00:00:00Z",
        "2025-06-30T00:00:00Z",
        "2025-07-31T00:00:00Z",
        "2025-08-31T00:00:00Z",
        "2025-09-30T00:00:00Z",
        "2025-10-31T00:00:00Z",
        "2025-11-30T00:00:00Z",
        "2025-12-31T00:00:00Z",
        "2026-01-31T00:00:00Z",
        "2026-02-28T00:00:00Z",
        "2026-03-31T00:00:00Z",
    ]
    _MONTHLY_RETURNS = {
        "VTI": 0.01,
        "AGG": 0.002,
    }

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        if symbol not in self._MONTHLY_RETURNS:
            return []
        value = 100.0 if symbol == "VTI" else 80.0
        bars: list[PriceBar] = []
        for date in self._DATES:
            bars.append(
                PriceBar(
                    timestamp=date, open=value, high=value, low=value, close=value, volume=10.0
                )
            )
            value *= 1.0 + self._MONTHLY_RETURNS[symbol]
        return bars


class _FakeRegime:
    def classify(self) -> SimpleNamespace:
        return SimpleNamespace(regime="GROWTH", confidence_score=80)


class _GapMarket(_FakeMarket):
    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        bars = super().get_price_history(symbol, days=days, interval=interval)
        if symbol == "AGG":
            return [bar for bar in bars if not bar.timestamp.startswith("2025-07")]
        return bars


class _JsonRequest:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def json(self) -> dict[str, Any]:
        return self._payload


def _call_gateway_tool(
    tool_id: str, payload: dict[str, Any], *, market: object | None = None
) -> tuple[int, Any]:
    app = FastAPI()
    router = build_planning_router(market=market or _FakeMarket(), regime_engine=_FakeRegime())
    app.include_router(router)
    endpoint = next(
        route.endpoint for route in router.routes if route.path == "/mcp/tools/{tool_id}"
    )
    response = asyncio.run(endpoint(tool_id, _JsonRequest(payload)))
    body = response.body.decode()
    if isinstance(response, JSONResponse):
        return response.status_code, json.loads(body)
    return response.status_code, body


def _compound(returns: list[float]) -> float:
    value = 1.0
    for ret in returns:
        value *= 1.0 + ret
    return value - 1.0


def test_historical_blend_monthly_rebalanced_compounds_growth() -> None:
    months = [f"2025-{month:02d}" for month in range(1, 13)]
    blend_return = 0.6 * 0.01 + 0.4 * 0.002
    result = historical_blend(
        monthly_returns_by_id={
            "us_equity": [0.01] * 12,
            "us_bonds": [0.002] * 12,
        },
        weights={"us_equity": 0.6, "us_bonds": 0.4},
        month_labels=months,
        initial_value=100.0,
    )

    assert result["months"] == 12
    assert result["calendarYearReturns"] == [
        {
            "year": 2025,
            "months": 12,
            "return": round((1.0 + blend_return) ** 12 - 1.0, 6),
            "complete": True,
        }
    ]
    assert result["growthOfDollar"][-1]["value"] == pytest.approx(
        round(100.0 * (1.0 + blend_return) ** 12, 4)
    )


def test_historical_blend_trailing_windows_and_not_annualized_flags() -> None:
    months = [f"2025-{month:02d}" for month in range(1, 13)] + [
        "2026-01",
        "2026-02",
        "2026-03",
    ]
    returns = [0.01] * 15
    result = historical_blend(
        monthly_returns_by_id={"asset": returns},
        weights={"asset": 1.0},
        month_labels=months,
    )
    windows = {row["window"]: row for row in result["annualizedReturns"]}

    assert windows["lastQuarter"]["annualized"] is False
    assert windows["lastQuarter"]["return"] == pytest.approx(round((1.01**3) - 1.0, 6))
    assert windows["ytd"]["annualized"] is False
    assert windows["ytd"]["months"] == 3
    assert windows["1Year"]["annualized"] is True
    assert windows["1Year"]["return"] == pytest.approx(0.126825, abs=1e-6)


def test_historical_blend_annual_rebalance_works_with_synthetic_periods() -> None:
    result = historical_blend(
        monthly_returns_by_id={
            "up": [0.10] * 13,
            "flat": [0.0] * 13,
        },
        weights={"up": 0.5, "flat": 0.5},
        rebalance_frequency="annual",
    )
    values = [row["value"] for row in result["growthOfDollar"]]
    thirteenth_month_return = values[12] / values[11] - 1.0

    assert thirteenth_month_return == pytest.approx(0.05, abs=1e-4)


def test_historical_blend_sigma_bands_are_mean_plus_minus_volatility() -> None:
    returns = [0.02, -0.01, 0.015, -0.005, 0.01, 0.0]
    result = historical_blend(
        monthly_returns_by_id={"asset": returns},
        weights={"asset": 1.0},
        month_labels=[f"2025-{month:02d}" for month in range(1, 7)],
    )
    stats = result["statistics"]
    expected_mean = (1.0 + _compound(returns)) ** (12.0 / len(returns)) - 1.0
    expected_vol = math.sqrt(
        sum((ret - sum(returns) / len(returns)) ** 2 for ret in returns) / len(returns)
    )
    expected_vol *= math.sqrt(12.0)

    assert stats["annualizedMean"] == pytest.approx(round(expected_mean, 6))
    assert stats["annualizedVolatility"] == pytest.approx(round(expected_vol, 6))
    assert stats["sigmaBands"]["minus2Sigma"] == pytest.approx(
        round(expected_mean - 2.0 * expected_vol, 6)
    )
    assert stats["sigmaBands"]["plus4Sigma"] == pytest.approx(
        round(expected_mean + 4.0 * expected_vol, 6)
    )


def test_historical_blend_gateway_happy_path_and_disclaimer() -> None:
    status, body = _call_gateway_tool(
        "historical_blend",
        {
            "assetClassIds": ["us_equity", "us_bonds"],
            "weights": {"us_equity": 0.6, "us_bonds": 0.4},
            "rebalanceFrequency": "monthly",
            "initialValue": 100.0,
        },
    )

    assert status == 200
    assert body["contractVersion"] == "0.1.0"
    assert body["asOf"] == "2026-03-31"
    assert body["startMonth"] == "2025-01"
    assert body["endMonth"] == "2026-03"
    assert body["assetClasses"][0]["id"] == "us_equity"
    assert "hypothetical and illustrative index-blend" in body["disclaimer"]
    assert "cannot invest directly in an index" in body["disclaimer"].lower()


def test_historical_blend_gateway_rejects_unknown_fields() -> None:
    status, body = _call_gateway_tool(
        "historical_blend",
        {
            "assetClassIds": ["us_equity"],
            "weights": {"us_equity": 1.0},
            "clientName": "Example Client",
        },
    )

    assert status == 400
    assert "historical_blend only accepts" in body


def test_historical_blend_gateway_rejects_malformed_asof() -> None:
    status, body = _call_gateway_tool(
        "historical_blend",
        {
            "assetClassIds": ["us_equity"],
            "weights": {"us_equity": 1.0},
            "asOf": "not-a-date",
        },
    )

    assert status == 400
    assert "asOf must be a YYYY-MM-DD date string" in body


def test_historical_blend_gateway_rejects_non_contiguous_months() -> None:
    status, body = _call_gateway_tool(
        "historical_blend",
        {
            "assetClassIds": ["us_equity", "us_bonds"],
            "weights": {"us_equity": 0.6, "us_bonds": 0.4},
        },
        market=_GapMarket(),
    )

    assert status == 400
    assert "contiguous monthly observations" in body


def test_historical_blend_result_schema_exposes_wire_shape() -> None:
    schema = historical_blend_result_schema()
    assert schema["title"] == "HistoricalBlendResult"
    assert "contractVersion" in schema["required"]
    assert "calendarYearReturns" in schema["properties"]
    assert "growthOfDollar" in schema["properties"]
    assert "sigmaBands" in schema["properties"]["statistics"]["properties"]
