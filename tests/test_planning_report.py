# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for ``build_planning_report`` + the pure assembly helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.planning import build_planning_router
from nexus_core.app.planning.report import (
    SECTION_ORDER,
    assemble_report,
    derive_findings,
)
from nexus_core.data.providers import PriceBar


class _FakeMarket:
    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        return [PriceBar(timestamp="2026-01-01T00:00:00Z", open=1.0, high=1.0, low=1.0, close=1.0)]


class _FakeRegimeEngine:
    def classify(self) -> SimpleNamespace:
        return SimpleNamespace(regime="HARD_ASSET", confidence_score=72)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(
        build_planning_router(market=_FakeMarket(), regime_engine=_FakeRegimeEngine())
    )
    return TestClient(app)


# ── pure helpers ───────────────────────────────────────────────────────────


def test_derive_findings_allocation() -> None:
    data = {
        "weights": {"us_equity": 0.6, "us_bonds": 0.35, "gold": 0.05},
        "expectedReturn": 0.061,
        "expectedVolatility": 0.102,
        "sharpeRatio": 0.16,
        "objective": "max_sharpe",
        "objectiveSource": "regime",
        "regime": "GROWTH",
    }
    findings = derive_findings("asset_allocation", data)
    assert any("us_equity 60.0%" in f for f in findings)
    assert any("Expected return 6.1%" in f and "Sharpe 0.16" in f for f in findings)
    assert any("GROWTH regime" in f for f in findings)


def test_derive_findings_unknown_kind_is_empty() -> None:
    assert derive_findings("appendix", {"anything": 1}) == []


def test_derive_findings_partial_data_does_not_raise() -> None:
    # Missing fields just yield fewer bullets, never an exception.
    assert derive_findings("asset_allocation", {}) == []
    assert derive_findings("capital_market_assumptions", {"assetClasses": []}) == []


def test_assemble_report_orders_by_taxonomy() -> None:
    sections = [
        {"kind": "appendix", "data": {}},
        {"kind": "asset_allocation", "data": {}},
        {"kind": "executive_summary", "data": {}},
    ]
    report = assemble_report(sections, title="X", regime=None)
    kinds = [s["kind"] for s in report["sections"]]
    assert kinds == ["executive_summary", "asset_allocation", "appendix"]
    assert kinds.index("executive_summary") < kinds.index("appendix")
    # Order matches SECTION_ORDER for known kinds.
    assert SECTION_ORDER.index("executive_summary") < SECTION_ORDER.index("asset_allocation")


def test_assemble_report_unknown_kind_sorts_last_stable() -> None:
    sections = [
        {"kind": "custom_b", "data": {}},
        {"kind": "regime_context", "data": {}},
        {"kind": "custom_a", "data": {}},
    ]
    kinds = [s["kind"] for s in assemble_report(sections, title="X", regime=None)["sections"]]
    assert kinds == ["regime_context", "custom_b", "custom_a"]  # unknowns appended, input order


def test_assemble_report_merges_and_dedupes_assumptions() -> None:
    sections = [
        {"kind": "asset_allocation", "data": {}, "assumptions": ["rf=4.5%", "shared"]},
        {"kind": "retirement_projection", "data": {}, "assumptions": ["shared", "horizon=30y"]},
    ]
    report = assemble_report(sections, title="X", regime=None)
    assert report["assumptions"] == ["rf=4.5%", "shared", "horizon=30y"]


def test_assemble_report_caller_findings_precede_auto() -> None:
    sections = [
        {
            "kind": "asset_allocation",
            "data": {"objective": "max_sharpe"},
            "findings": ["Custom headline."],
        }
    ]
    findings = assemble_report(sections, title="X", regime=None)["sections"][0]["findings"]
    assert findings[0] == "Custom headline."
    assert any("max_sharpe" in f for f in findings)  # auto-derived appended


# ── gateway ────────────────────────────────────────────────────────────────


def _build(body: dict[str, Any]) -> Any:
    return _client().post("/mcp/tools/build_planning_report", json=body)


def test_build_report_happy_path() -> None:
    r = _build(
        {
            "title": "Q2 Review",
            "sections": [
                {
                    "kind": "asset_allocation",
                    "data": {"weights": {"us_equity": 0.6, "us_bonds": 0.4}},
                },
                {"kind": "executive_summary", "findings": ["On track."]},
            ],
        }
    )
    assert r.status_code == 200, r.text
    body = r.json()
    report = body["report"]
    assert report["title"] == "Q2 Review"
    assert [s["kind"] for s in report["sections"]] == ["executive_summary", "asset_allocation"]
    assert report["regime"] == "HARD_ASSET"  # includeRegime defaults true
    # build_planning_report carries the comprehensive disclaimer.
    assert "Operated by Protocol Wealth" in body["disclaimer"]
    assert body["contractVersion"] == "0.1.0"


def test_build_report_exclude_regime() -> None:
    body = _build(
        {"sections": [{"kind": "executive_summary"}], "includeRegime": False}
    ).json()
    assert "regime" not in body["report"]
    assert body["report"]["title"] == "Planning Analysis Report"  # default title


def test_build_report_empty_sections_is_400() -> None:
    r = _build({"sections": []})
    assert r.status_code == 400
    assert "non-empty list" in r.text


def test_build_report_section_without_kind_is_400() -> None:
    r = _build({"sections": [{"data": {}}]})
    assert r.status_code == 400
    assert "kind" in r.text


def test_build_report_bad_findings_type_is_400() -> None:
    r = _build({"sections": [{"kind": "appendix", "findings": [1, 2]}]})
    assert r.status_code == 400
    assert "findings must be a list of strings" in r.text


def test_build_report_rejects_identity_keys() -> None:
    # The PII-free gateway rejects any identity-shaped key anywhere in the body.
    r = _build({"sections": [{"kind": "appendix", "data": {"email": "jane@example.com"}}]})
    assert r.status_code == 400
    assert "identity fields are not accepted" in r.text
