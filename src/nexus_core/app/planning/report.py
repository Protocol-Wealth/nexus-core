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

from typing import Any

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

#: Section kinds with a canonical position. Unknown kinds are still accepted (they
#: sort last) so a caller can attach a bespoke section without a contract change.
KNOWN_SECTION_KINDS: frozenset[str] = frozenset(SECTION_ORDER)

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


def _ordered(kind: str) -> tuple[int, int]:
    """Sort key: known kinds by canonical order, unknown kinds appended (stable)."""
    try:
        return (0, SECTION_ORDER.index(kind))
    except ValueError:
        return (1, 0)


def assemble_report(
    sections: list[dict[str, Any]],
    *,
    title: str,
    regime: str | None,
) -> dict[str, Any]:
    """Assemble validated section inputs into the ordered report envelope.

    Each input section is a dict with a ``kind`` and optional ``title``,
    ``data``, ``findings`` (caller-supplied bullets), and ``assumptions``.
    Caller-supplied findings precede auto-derived ones (de-duplicated, order
    preserved). Assumptions across all sections are consolidated and de-duplicated.

    ``regime`` (when given) is recorded as report-level context — it does not add
    a section. Input order among same-position kinds is preserved (stable sort).
    """
    indexed = sorted(enumerate(sections), key=lambda pair: (_ordered(pair[1]["kind"]), pair[0]))

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

        assembled.append(
            {
                "kind": kind,
                "title": section.get("title") or _DEFAULT_TITLES.get(kind, kind),
                "findings": findings,
                "data": data,
            }
        )

    report: dict[str, Any] = {
        "title": title,
        "sections": assembled,
        "assumptions": all_assumptions,
    }
    if regime is not None:
        report["regime"] = regime
    return report


__all__ = [
    "KNOWN_SECTION_KINDS",
    "SECTION_ORDER",
    "assemble_report",
    "derive_findings",
]
