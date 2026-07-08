# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for ``build_planning_report`` + the pure assembly helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus_core.app.planning import build_planning_router
from nexus_core.app.planning.contract import PlanningInputError
from nexus_core.app.planning.report import (
    PLANNING_BENEFIT_NOTICE,
    REPORT_DISPLAY_TITLE,
    SCOPE_STATEMENT,
    SECTION_ORDER,
    WEALTH_ROADMAP_SECTION_ORDER,
    assemble_report,
    assemble_wealth_roadmap,
    derive_findings,
)
from nexus_core.app.planning.tools import build_tool_handlers
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
    assert derive_findings("historical_blend", {"statistics": {}}) == []


def test_derive_findings_historical_blend() -> None:
    findings = derive_findings(
        "historical_blend",
        {
            "months": 120,
            "startMonth": "2016-04",
            "endMonth": "2026-03",
            "statistics": {"annualizedMean": 0.071, "annualizedVolatility": 0.122},
        },
    )

    assert any(
        "Hypothetical historical index-blend illustration covers 120 monthly returns" in finding
        for finding in findings
    )
    assert any(
        "Illustrative annualized historical blend return 7.1%" in finding and "12.2%" in finding
        for finding in findings
    )


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


def _roadmap_sections() -> list[dict[str, Any]]:
    return [
        {"kind": "income", "findings": ["Income layers cover the first gap."]},
        {"kind": "snapshot", "findings": ["Net worth snapshot is complete."]},
        {"kind": "historical_blend", "data": {"months": 120, "startMonth": "2016-01", "endMonth": "2025-12"}},
        {"kind": "trajectory", "findings": ["Success probability is within tolerance."]},
        {"kind": "goals", "findings": ["Education goal needs an additional monthly savings amount."]},
        {"kind": "guardrails", "findings": ["Guardrail lower band would freeze spending."]},
    ]


def _roadmap_metadata(scope: str = "focused") -> dict[str, Any]:
    return {
        "assumptionVersion": "assumptions-2026",
        "cmaVersion": "cma-2026-q3",
        "taxYear": 2026,
        "seed": 42,
        "engineReference": "nexus-core:test",
        "scope": scope,
    }


def test_wealth_roadmap_focused_injects_scope_notice_and_stamps_metadata() -> None:
    report = assemble_wealth_roadmap(
        _roadmap_sections(),
        scope="focused",
        metadata=_roadmap_metadata(),
        regime=None,
    )

    assert report["title"] == REPORT_DISPLAY_TITLE
    assert report["scope"] == "focused"
    assert report["scopeStatement"] == SCOPE_STATEMENT
    assert report["planningBenefitNotice"] == PLANNING_BENEFIT_NOTICE
    assert [section["kind"] for section in report["sections"]] == [
        "snapshot",
        "trajectory",
        "goals",
        "scope_assumptions_disclosures",
    ]
    assert all(section["metadata"]["scope"] == "focused" for section in report["sections"])
    scope_section = report["sections"][-1]
    assert SCOPE_STATEMENT in scope_section["findings"]
    assert PLANNING_BENEFIT_NOTICE in scope_section["findings"]
    assert WEALTH_ROADMAP_SECTION_ORDER.index("snapshot") < WEALTH_ROADMAP_SECTION_ORDER.index(
        "trajectory"
    )


def test_wealth_roadmap_full_blocks_release_until_priority_actions_are_curated() -> None:
    report = assemble_wealth_roadmap(
        _roadmap_sections(),
        scope="full",
        metadata=_roadmap_metadata("full"),
        regime="GROWTH",
    )

    kinds = [section["kind"] for section in report["sections"]]
    assert kinds == [
        "snapshot",
        "trajectory",
        "goals",
        "income",
        "guardrails",
        "historical_blend",
        "scope_assumptions_disclosures",
        "priority_actions",
    ]
    assert report["release"]["blocked"] is True
    assert report["release"]["released"] is False
    assert report["release"]["blockReason"] == "uncurated_priority_actions"
    assert report["release"]["uncuratedPriorityActions"] > 0
    assert report["regime"] == "GROWTH"


def test_wealth_roadmap_rejects_caller_curated_priority_actions() -> None:
    try:
        assemble_wealth_roadmap(
            [
                *_roadmap_sections(),
                {
                    "kind": "priority_actions",
                    "data": {
                        "actions": [
                            {
                                "text": "Review Roth conversion window.",
                                "curated": True,
                                "sourceSection": "tax_planning",
                            }
                        ]
                    },
                },
            ],
            scope="full",
            metadata=_roadmap_metadata("full"),
            regime=None,
        )
    except ValueError as exc:
        assert "curated is private workflow state" in str(exc)
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("expected caller-curated priority action to fail")


def test_wealth_roadmap_focused_rejects_priority_actions_section() -> None:
    try:
        assemble_wealth_roadmap(
            [
                *_roadmap_sections(),
                {
                    "kind": "priority_actions",
                    "data": {
                        "actions": [
                            {
                                "text": "Review Roth conversion window.",
                                "curated": True,
                                "sourceSection": "tax_planning",
                            }
                        ]
                    },
                },
            ],
            scope="focused",
            metadata=_roadmap_metadata(),
            regime=None,
        )
    except ValueError as exc:
        assert "priority_actions sections are only accepted for full scope" in str(exc)
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("expected focused priority_actions section to fail")


def test_wealth_roadmap_priority_actions_remain_unreleased_candidate_state() -> None:
    report = assemble_wealth_roadmap(
        [
            *_roadmap_sections(),
            {
                "kind": "priority_actions",
                "data": {
                    "actions": [
                        {
                            "text": "Review Roth conversion window.",
                            "sourceSection": "tax_planning",
                        }
                    ]
                },
            },
        ],
        scope="full",
        metadata=_roadmap_metadata("full"),
        regime=None,
    )

    action = report["sections"][-1]["data"]["actions"][0]
    assert action["curated"] is False
    assert report["release"]["released"] is False
    assert report["release"]["blocked"] is True
    assert report["release"]["blockReason"] == "uncurated_priority_actions"
    assert report["release"]["uncuratedPriorityActions"] == 1


def test_wealth_roadmap_full_blocks_release_when_priority_actions_are_missing() -> None:
    report = assemble_wealth_roadmap(
        [
            {"kind": "snapshot", "data": {}},
            {"kind": "trajectory", "data": {}},
            {"kind": "goals", "data": {}},
            {"kind": "income", "data": {}},
            {"kind": "guardrails", "data": {}},
            {"kind": "historical_blend", "data": {}},
        ],
        scope="full",
        metadata=_roadmap_metadata("full"),
        regime=None,
    )

    assert report["release"]["blocked"] is True
    assert report["release"]["blockReason"] == "missing_priority_actions"


def test_wealth_roadmap_rejects_missing_required_sections() -> None:
    try:
        assemble_wealth_roadmap(
            [{"kind": "snapshot", "data": {}}],
            scope="focused",
            metadata=_roadmap_metadata(),
            regime=None,
        )
    except ValueError as exc:
        assert "wealth_roadmap focused scope missing required sections" in str(exc)
        assert "goals" in str(exc)
        assert "trajectory" in str(exc)
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("expected missing required sections to fail")


def test_wealth_roadmap_replay_is_deterministic_with_same_metadata() -> None:
    first = assemble_wealth_roadmap(
        _roadmap_sections(),
        scope="focused",
        metadata=_roadmap_metadata(),
        regime=None,
    )
    second = assemble_wealth_roadmap(
        _roadmap_sections(),
        scope="focused",
        metadata=_roadmap_metadata(),
        regime=None,
    )

    assert first == second


# ── gateway ────────────────────────────────────────────────────────────────


def _build(body: dict[str, Any]) -> Any:
    return _client().post("/mcp/tools/build_planning_report", json=body)


def _direct_build(body: dict[str, Any]) -> dict[str, Any]:
    handlers = build_tool_handlers(market=_FakeMarket(), regime_engine=_FakeRegimeEngine())
    return handlers["build_planning_report"](body)


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
    body = _build({"sections": [{"kind": "executive_summary"}], "includeRegime": False}).json()
    assert "regime" not in body["report"]
    assert body["report"]["title"] == "Planning Analysis Report"  # default title


def test_build_report_wealth_roadmap_focused_gateway() -> None:
    body = _build(
        {
            "preset": "wealth_roadmap",
            "scope": "focused",
            "includeRegime": False,
            "metadata": {
                "assumptionVersion": "assumptions-2026",
                "cmaVersion": "cma-2026-q3",
                "taxYear": 2026,
                "seed": 42,
            },
            "sections": [
                {"kind": "trajectory", "findings": ["Success probability is within tolerance."]},
                {"kind": "snapshot", "findings": ["Snapshot ready."]},
                {"kind": "goals", "findings": ["Goal funding is within range."]},
            ],
        }
    ).json()

    report = body["report"]
    assert report["title"] == REPORT_DISPLAY_TITLE
    assert report["scope"] == "focused"
    assert report["metadata"]["engineReference"].startswith("nexus-core:")
    assert [section["kind"] for section in report["sections"]] == [
        "snapshot",
        "trajectory",
        "goals",
        "scope_assumptions_disclosures",
    ]
    assert report["sections"][0]["metadata"]["seed"] == 42
    assert SCOPE_STATEMENT in report["sections"][-1]["findings"]


def test_wealth_roadmap_handler_rejects_missing_metadata() -> None:
    try:
        _direct_build(
            {
                "preset": "wealth_roadmap",
                "scope": "focused",
                "includeRegime": False,
                "sections": [
                    {"kind": "snapshot", "findings": ["Snapshot ready."]},
                    {"kind": "trajectory", "findings": ["Trajectory ready."]},
                    {"kind": "goals", "findings": ["Goal ready."]},
                ],
            }
        )
    except PlanningInputError as exc:
        assert "metadata.assumptionVersion is required for wealth_roadmap" in str(exc)
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("expected missing Roadmap metadata to fail")


def test_wealth_roadmap_rejects_duplicate_visible_sections() -> None:
    try:
        assemble_wealth_roadmap(
            [
                *_roadmap_sections(),
                {"kind": "snapshot", "findings": ["Duplicate snapshot."]},
            ],
            scope="full",
            metadata=_roadmap_metadata("full"),
            regime=None,
        )
    except ValueError as exc:
        assert "at most one snapshot section" in str(exc)
    else:  # pragma: no cover - explicit failure branch
        raise AssertionError("expected duplicate Roadmap section to fail")


def test_build_report_wealth_roadmap_rejects_public_release_state() -> None:
    r = _build(
        {
            "preset": "wealth_roadmap",
            "scope": "full",
            "released": True,
            "includeRegime": False,
            "sections": [
                {"kind": "snapshot", "findings": ["Snapshot ready."]},
                {"kind": "trajectory", "findings": ["Success probability is within tolerance."]},
            ],
        }
    )

    assert r.status_code == 400
    assert "released is private workflow state" in r.text


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
