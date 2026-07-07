# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""De-identified planning-report assembly.

Composes the *outputs* of the planning tools (allocation, projection, tax, ...)
into one ordered, render-ready report envelope: each section gets a canonical
display position, auto-derived plain-language findings where the section kind is
recognized, and a consolidated, de-duplicated assumptions list.

PII-free by construction — it operates on the engine's numeric tool outputs,
never on identity. This is generic financial-planning structure (executive
summary → regime → assumptions → allocation → analytics → projection → withdrawal
→ tax → Social Security → risk → appendix); it is not, and does not render, a
firm's proprietary Investment Policy Statement. Educational illustration only.
"""

from __future__ import annotations

from typing import Any, cast

#: Canonical section kinds, in report display order. A section's ``kind`` sets its
#: position; recognized but unordered kinds, and any unknown kinds, are appended
#: after the ordered ones in their original (stable) input order.
SECTION_ORDER: tuple[str, ...] = (
    "executive_summary",
    "regime_context",
    "capital_market_assumptions",
    "historical_blend",
    "asset_allocation",
    "portfolio_analytics",
    "retirement_projection",
    "withdrawal_strategy",
    "tax_planning",
    "social_security",
    "risk_assessment",
    "appendix",
)

REPORT_DISPLAY_TITLE = "PW Wealth Roadmap"
SCOPE_STATEMENT = (
    "This Wealth Roadmap is a planning snapshot, not a comprehensive financial plan. "
    "It addresses only the stated goal(s) and subject area(s) listed in the scope, "
    "assumptions, and disclosures section."
)
PLANNING_BENEFIT_NOTICE = (
    "A comprehensive financial planning engagement may identify needs, tradeoffs, "
    "and subject areas outside this focused scope. Declining that broader engagement "
    "may limit the advice and analysis available from this Roadmap."
)
WEALTH_ROADMAP_SCOPES: tuple[str, ...] = ("focused", "full")
WEALTH_ROADMAP_SECTION_ORDER: tuple[str, ...] = (
    "snapshot",
    "trajectory",
    "goals",
    "income",
    "guardrails",
    "historical_blend",
    "scope_assumptions_disclosures",
    "priority_actions",
)
_WEALTH_ROADMAP_INPUT_KINDS = frozenset(
    kind for kind in WEALTH_ROADMAP_SECTION_ORDER if kind != "scope_assumptions_disclosures"
)
_WEALTH_ROADMAP_FOCUSED_INPUT_KINDS = frozenset(("snapshot", "trajectory", "goals"))
_WEALTH_ROADMAP_REQUIRED_BY_SCOPE: dict[str, frozenset[str]] = {
    "focused": frozenset(("snapshot", "trajectory", "goals")),
    "full": frozenset(
        (
            "snapshot",
            "trajectory",
            "goals",
            "income",
            "guardrails",
            "historical_blend",
        )
    ),
}

#: Section kinds with a canonical position. Unknown kinds are still accepted (they
#: sort last) so a caller can attach a bespoke section without a contract change.
KNOWN_SECTION_KINDS: frozenset[str] = frozenset(
    [*SECTION_ORDER, *WEALTH_ROADMAP_SECTION_ORDER]
)

#: Default human title per kind; a section may override with its own ``title``.
_DEFAULT_TITLES: dict[str, str] = {
    "executive_summary": "Executive Summary",
    "regime_context": "Market Regime Context",
    "capital_market_assumptions": "Capital Market Assumptions",
    "historical_blend": "Historical Context",
    "asset_allocation": "Recommended Asset Allocation",
    "portfolio_analytics": "Portfolio Analytics",
    "retirement_projection": "Retirement Projection",
    "withdrawal_strategy": "Withdrawal Strategy",
    "tax_planning": "Tax Planning",
    "social_security": "Social Security",
    "risk_assessment": "Risk Assessment",
    "appendix": "Appendix",
    "snapshot": "Snapshot",
    "trajectory": "Trajectory",
    "goals": "Goals",
    "income": "Income",
    "guardrails": "Guardrails",
    "scope_assumptions_disclosures": "Scope, Assumptions & Disclosures",
    "priority_actions": "Priority Actions",
}


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _allocation_findings(data: dict[str, Any]) -> list[str]:
    """Findings for an ``optimize_allocation`` output."""
    out: list[str] = []
    weights = data.get("weights")
    if isinstance(weights, dict) and weights:
        ranked = sorted(
            ((k, float(v)) for k, v in weights.items() if isinstance(v, (int, float))),
            key=lambda kv: kv[1],
            reverse=True,
        )[:3]
        if ranked:
            parts = ", ".join(f"{k} {_fmt_pct(w)}" for k, w in ranked)
            out.append(f"Largest target weights: {parts}.")
    er, vol = data.get("expectedReturn"), data.get("expectedVolatility")
    if isinstance(er, (int, float)) and isinstance(vol, (int, float)):
        sharpe = data.get("sharpeRatio")
        tail = f", Sharpe {float(sharpe):.2f}" if isinstance(sharpe, (int, float)) else ""
        out.append(
            f"Expected return {_fmt_pct(float(er))} at {_fmt_pct(float(vol))} volatility{tail}."
        )
    objective = data.get("objective")
    if isinstance(objective, str):
        regime = data.get("regime")
        if data.get("objectiveSource") == "regime" and isinstance(regime, str):
            out.append(f"Objective '{objective}' selected for the live {regime} regime.")
        else:
            out.append(f"Optimized with objective '{objective}'.")
    return out


def _cma_findings(data: dict[str, Any]) -> list[str]:
    """Findings for a ``capital_market_assumptions`` output."""
    out: list[str] = []
    asset_classes = data.get("assetClasses")
    if isinstance(asset_classes, list) and asset_classes:
        returns = [
            float(a["expectedReturn"])
            for a in asset_classes
            if isinstance(a, dict) and isinstance(a.get("expectedReturn"), (int, float))
        ]
        if returns:
            out.append(
                f"{len(asset_classes)} asset classes; forward expected returns span "
                f"{_fmt_pct(min(returns))} to {_fmt_pct(max(returns))}."
            )
    as_of = data.get("asOf")
    if isinstance(as_of, str):
        out.append(f"Volatility and correlations estimated as of {as_of}.")
    return out


def _historical_blend_findings(data: dict[str, Any]) -> list[str]:
    """Findings for a ``historical_blend`` output."""
    out: list[str] = []
    months = data.get("months")
    start = data.get("startMonth")
    end = data.get("endMonth")
    if isinstance(months, int) and isinstance(start, str) and isinstance(end, str):
        out.append(
            f"Hypothetical historical index-blend illustration covers {months} "
            f"monthly returns from {start} through {end}."
        )
    stats = data.get("statistics")
    if isinstance(stats, dict):
        mean = stats.get("annualizedMean")
        vol = stats.get("annualizedVolatility")
        if isinstance(mean, (int, float)) and isinstance(vol, (int, float)):
            out.append(
                f"Illustrative annualized historical blend return {_fmt_pct(float(mean))} "
                f"with {_fmt_pct(float(vol))} volatility."
            )
    return out


def _regime_findings(data: dict[str, Any]) -> list[str]:
    """Findings for a live-regime context section."""
    out: list[str] = []
    regime = data.get("regime") or data.get("code")
    if isinstance(regime, str):
        out.append(f"Live macro regime: {regime}.")
    confidence = data.get("confidence")
    if confidence is None:
        confidence = data.get("confidenceScore")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        out.append(f"Classification confidence: {int(confidence)}.")
    return out


#: Section kind → finding deriver. Only kinds whose output shape is a stable
#: contract are auto-derived; every deriver reads defensively and skips a bullet
#: when a field is absent, so partial inputs never raise.
_AUTO_FINDINGS = {
    "asset_allocation": _allocation_findings,
    "capital_market_assumptions": _cma_findings,
    "historical_blend": _historical_blend_findings,
    "regime_context": _regime_findings,
}


def derive_findings(kind: str, data: dict[str, Any]) -> list[str]:
    """Best-effort plain-language findings for a recognized section kind.

    Returns ``[]`` for kinds without an auto-deriver (the caller can still attach
    explicit ``findings``). Never raises on a partial or unexpected ``data``.
    """
    deriver = _AUTO_FINDINGS.get(kind)
    return deriver(data) if deriver is not None else []


def _ordered(kind: str, section_order: tuple[str, ...] = SECTION_ORDER) -> tuple[int, int]:
    """Sort key: known kinds by canonical order, unknown kinds appended (stable)."""
    try:
        return (0, section_order.index(kind))
    except ValueError:
        return (1, 0)


def assemble_report(
    sections: list[dict[str, Any]],
    *,
    title: str,
    regime: str | None,
    section_order: tuple[str, ...] = SECTION_ORDER,
    section_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble validated section inputs into the ordered report envelope.

    Each input section is a dict with a ``kind`` and optional ``title``,
    ``data``, ``findings`` (caller-supplied bullets), and ``assumptions``.
    Caller-supplied findings precede auto-derived ones (de-duplicated, order
    preserved). Assumptions across all sections are consolidated and de-duplicated.

    ``regime`` (when given) is recorded as report-level context — it does not add
    a section. Input order among same-position kinds is preserved (stable sort).
    """
    indexed = sorted(
        enumerate(sections),
        key=lambda pair: (_ordered(pair[1]["kind"], section_order), pair[0]),
    )

    assembled: list[dict[str, Any]] = []
    all_assumptions: list[str] = []
    seen_assumptions: set[str] = set()

    for _, section in indexed:
        kind = section["kind"]
        data = section.get("data") if isinstance(section.get("data"), dict) else {}
        assert isinstance(data, dict)  # narrowed above; for the type checker

        findings: list[str] = []
        seen_findings: set[str] = set()
        for bullet in [*section.get("findings", []), *derive_findings(kind, data)]:
            if bullet not in seen_findings:
                seen_findings.add(bullet)
                findings.append(bullet)

        for assumption in section.get("assumptions", []):
            if assumption not in seen_assumptions:
                seen_assumptions.add(assumption)
                all_assumptions.append(assumption)

        assembled_section = {
            "kind": kind,
            "title": section.get("title") or _DEFAULT_TITLES.get(kind, kind),
            "findings": findings,
            "data": data,
        }
        if section_metadata is not None:
            assembled_section["metadata"] = dict(section_metadata)
        assembled.append(assembled_section)

    report: dict[str, Any] = {
        "title": title,
        "sections": assembled,
        "assumptions": all_assumptions,
    }
    if regime is not None:
        report["regime"] = regime
    return report


def _scope_section(scope: str, metadata: dict[str, Any], source_kinds: list[str]) -> dict[str, Any]:
    findings = [SCOPE_STATEMENT]
    if scope == "focused":
        findings.append(PLANNING_BENEFIT_NOTICE)
    return {
        "kind": "scope_assumptions_disclosures",
        "findings": findings,
        "data": {
            "scope": scope,
            "displayTitle": REPORT_DISPLAY_TITLE,
            "scopeStatement": SCOPE_STATEMENT,
            "planningBenefitNotice": PLANNING_BENEFIT_NOTICE if scope == "focused" else None,
            "metadata": dict(metadata),
            "sourceSectionKinds": source_kinds,
        },
        "assumptions": [SCOPE_STATEMENT]
        + ([PLANNING_BENEFIT_NOTICE] if scope == "focused" else []),
    }


def _normalize_priority_actions(section: dict[str, Any] | None) -> list[dict[str, Any]]:
    if section is None:
        return []
    data = section.get("data")
    if not isinstance(data, dict):
        return []
    raw_actions = data.get("actions")
    if raw_actions is None:
        return []
    if not isinstance(raw_actions, list):
        raise ValueError("priority_actions.data.actions must be a list")
    actions: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_actions):
        if isinstance(raw, str):
            if not raw:
                raise ValueError(f"priority_actions.data.actions[{index}] must be non-empty")
            actions.append({"text": raw, "curated": False, "sourceSection": "caller"})
            continue
        if not isinstance(raw, dict):
            raise ValueError(f"priority_actions.data.actions[{index}] must be an object or string")
        text = raw.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError(f"priority_actions.data.actions[{index}].text must be a non-empty string")
        if "curated" in raw:
            raise ValueError(
                f"priority_actions.data.actions[{index}].curated is private workflow state"
            )
        source = raw.get("sourceSection", "caller")
        if not isinstance(source, str) or not source:
            raise ValueError(
                f"priority_actions.data.actions[{index}].sourceSection must be a non-empty string"
            )
        action = {"text": text, "curated": False, "sourceSection": source}
        if isinstance(raw.get("rationale"), str):
            action["rationale"] = raw["rationale"]
        actions.append(action)
    return actions


def _candidate_priority_actions(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for section in sections:
        kind = section.get("kind")
        if not isinstance(kind, str):
            continue
        if kind in {"scope_assumptions_disclosures", "priority_actions"}:
            continue
        raw_data = section.get("data")
        data = cast(dict[str, Any], raw_data) if isinstance(raw_data, dict) else {}
        raw_findings = section.get("findings", [])
        section_findings = raw_findings if isinstance(raw_findings, list) else []
        findings = [*section_findings, *derive_findings(kind, data)]
        for finding in findings:
            if not isinstance(finding, str) or not finding:
                continue
            actions.append(
                {
                    "text": finding,
                    "curated": False,
                    "sourceSection": kind,
                }
            )
            if len(actions) >= 5:
                return actions
    return actions


def _priority_actions_section(actions: list[dict[str, Any]]) -> dict[str, Any]:
    curated_count = sum(1 for action in actions if action.get("curated") is True)
    return {
        "kind": "priority_actions",
        "data": {
            "actions": actions,
            "curatedCount": curated_count,
            "uncuratedCount": len(actions) - curated_count,
        },
        "findings": [
            "Priority actions are candidate planning observations until an advisor curates them."
        ],
    }


def _release_state(*, actions: list[dict[str, Any]], require_actions: bool) -> dict[str, Any]:
    uncurated = sum(1 for action in actions if action.get("curated") is not True)
    missing = require_actions and not actions
    block_reason = None
    if missing:
        block_reason = "missing_priority_actions"
    elif uncurated > 0:
        block_reason = "uncurated_priority_actions"
    else:
        block_reason = "private_release_required"
    return {
        "released": False,
        "blocked": True,
        "blockReason": block_reason,
        "uncuratedPriorityActions": uncurated,
    }


def assemble_wealth_roadmap(
    sections: list[dict[str, Any]],
    *,
    scope: str,
    metadata: dict[str, Any],
    regime: str | None,
) -> dict[str, Any]:
    """Assemble the deterministic PW Wealth Roadmap preset."""

    if scope not in WEALTH_ROADMAP_SCOPES:
        raise ValueError(f"scope must be one of {', '.join(WEALTH_ROADMAP_SCOPES)}")

    roadmap_sections: list[dict[str, Any]] = []
    priority_section: dict[str, Any] | None = None
    focused_goal_seen = False
    seen_kinds: set[str] = set()
    for section in sections:
        kind = section["kind"]
        if kind == "scope_assumptions_disclosures":
            continue
        if kind == "priority_actions":
            if scope != "full":
                raise ValueError("priority_actions sections are only accepted for full scope")
            if priority_section is not None:
                raise ValueError("wealth_roadmap accepts at most one priority_actions section")
            priority_section = section
            continue
        if kind not in _WEALTH_ROADMAP_INPUT_KINDS:
            allowed = ", ".join(sorted(_WEALTH_ROADMAP_INPUT_KINDS))
            raise ValueError(f"wealth_roadmap sections must use one of: {allowed}")
        if kind in seen_kinds:
            raise ValueError(f"wealth_roadmap accepts at most one {kind} section")
        seen_kinds.add(kind)
        if scope == "focused":
            if kind not in _WEALTH_ROADMAP_FOCUSED_INPUT_KINDS:
                continue
            if kind == "goals":
                if focused_goal_seen:
                    continue
                focused_goal_seen = True
        roadmap_sections.append(section)

    present = {section["kind"] for section in roadmap_sections}
    missing = sorted(_WEALTH_ROADMAP_REQUIRED_BY_SCOPE[scope] - present)
    if missing:
        raise ValueError(f"wealth_roadmap {scope} scope missing required sections: {missing}")

    source_kinds = [section["kind"] for section in roadmap_sections]
    roadmap_sections.append(_scope_section(scope, metadata, source_kinds))

    actions: list[dict[str, Any]] = []
    if scope == "full":
        actions = _normalize_priority_actions(priority_section)
        if not actions:
            actions = _candidate_priority_actions(roadmap_sections)
        roadmap_sections.append(_priority_actions_section(actions))

    release = _release_state(actions=actions, require_actions=scope == "full")

    report = assemble_report(
        roadmap_sections,
        title=REPORT_DISPLAY_TITLE,
        regime=regime,
        section_order=WEALTH_ROADMAP_SECTION_ORDER,
        section_metadata=metadata,
    )
    report["preset"] = "wealth_roadmap"
    report["scope"] = scope
    report["scopeStatement"] = SCOPE_STATEMENT
    if scope == "focused":
        report["planningBenefitNotice"] = PLANNING_BENEFIT_NOTICE
    report["metadata"] = dict(metadata)
    report["release"] = release
    return report


__all__ = [
    "KNOWN_SECTION_KINDS",
    "PLANNING_BENEFIT_NOTICE",
    "REPORT_DISPLAY_TITLE",
    "SECTION_ORDER",
    "SCOPE_STATEMENT",
    "WEALTH_ROADMAP_SCOPES",
    "WEALTH_ROADMAP_SECTION_ORDER",
    "assemble_report",
    "assemble_wealth_roadmap",
    "derive_findings",
]
