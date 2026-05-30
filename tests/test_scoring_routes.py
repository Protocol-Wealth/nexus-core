# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the /api/score EMF scoring surface.

Hermetic — a fake market provider supplies quotes + history, a fake regime
engine supplies the regime code, and ``build_fundamentals`` is monkeypatched so
no SEC request is made.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.scoring import build_score_router
from nexus_core.data.providers import PriceBar, Quote


class _FakeMarket:
    def get_quote(self, symbol: str) -> Quote | None:
        return Quote(symbol=symbol, price=100.0, timestamp="2026-01-05T00:00:00Z")

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        # 120 gently trending closes — enough for the Hurst multi-window + returns.
        return [
            PriceBar(
                timestamp=f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                open=100.0 + i * 0.1,
                high=101.0 + i * 0.1,
                low=99.0 + i * 0.1,
                close=100.0 + i * 0.1,
                volume=1_000_000.0,
            )
            for i in range(120)
        ]


class _RegimeResult:
    def to_dict(self) -> dict[str, str]:
        return {"regime": "GROWTH"}


class _FakeEngine:
    def classify(self) -> _RegimeResult:
        return _RegimeResult()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(build_score_router(market=_FakeMarket(), regime_engine=_FakeEngine()))
    return TestClient(app)


def test_score_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "nexus_core.app.scoring.build_fundamentals",
        lambda ticker, **kwargs: {"croic": 0.18, "f_score": 7},
    )
    r = _client().get("/api/score/aapl")
    assert r.status_code == 200
    body = r.json()
    assert body["subject"] == "AAPL"
    assert body["total_checks"] == 8
    assert len(body["checks"]) == 8
    assert body["tier"]
    assert "not investment, tax, legal, or financial advice" in body["disclaimer"].lower()
    assert r.headers["cache-control"] == "public, max-age=1800"
    by_name = {c["name"]: c for c in body["checks"]}
    # The injected fundamentals make CROIC + F-Score evaluate (and pass).
    assert by_name["CROIC"]["passed"] is True
    assert by_name["F-Score"]["passed"] is True


def test_score_without_fundamentals(monkeypatch: pytest.MonkeyPatch) -> None:
    """ETF/crypto path: no SEC fundamentals → CROIC/F-Score insufficient_data, still 200."""
    monkeypatch.setattr(
        "nexus_core.app.scoring.build_fundamentals", lambda ticker, **kwargs: None
    )
    r = _client().get("/api/score/SPY")
    assert r.status_code == 200
    body = r.json()
    assert body["total_checks"] == 8
    by_name = {c["name"]: c for c in body["checks"]}
    assert by_name["CROIC"]["passed"] is None
    # Compliance: a sparsely-evaluable subject must NOT get a verdict-shaped tier.
    assert body["total_evaluated"] < 4
    assert body["tier"] == "NOT APPLICABLE"
    assert body["tier_note"] and "insufficient" in body["tier_note"].lower()
