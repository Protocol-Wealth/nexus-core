# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Output formatters for scoring results.

Different audiences need different presentations of the same score:

    - **Public / retail**: plain language, rounded values, no jargon.
    - **Advisor / research**: exact values, sector overrides, thresholds.
    - **Structured (JSON)**: machine-readable, includes attribution.

Each formatter is a pure function — pass a ``ScoreResult`` and get a string
or dict back. Users can pipe these into MCP responses, emails, or PDFs.
"""

from __future__ import annotations

from typing import Any

from .attribution import CHECK_METADATA, CheckMetadata
from .framework import ScoreResult


def format_public(result: ScoreResult) -> str:
    """Format a scoring result for public / retail audiences.

    Uses ``CheckMetadata.public_label`` where available, falls back to the
    check's raw name. Strips technical numeric values.
    """
    lines = [
        f"Quality Score: {result.total_passed} of {result.total_checks} checks passed",
        f"Confidence: {result.tier.value.title()}",
    ]
    if result.layer_assignment:
        lines.append(f"Classification: {result.layer_assignment}")
    lines.append("")

    for check in result.checks:
        meta = CHECK_METADATA.get(check.name)
        label = meta.public_label if meta and meta.public_label else check.name
        mark = "[✓]" if check.passed else "[✗]" if check.passed is False else "[·]"
        lines.append(f"{mark} {label}: {check.interpretation or _fallback_display(check)}")

    return "\n".join(lines)


def format_advisor(result: ScoreResult) -> str:
    """Format a scoring result for advisors / research audiences.

    Includes raw numeric values, thresholds, and details. No jargon-stripping.
    """
    lines = [
        f"SCORE: {result.subject} — {result.total_passed}/{result.total_checks} "
        f"({result.tier.value})"
    ]
    if result.layer_assignment:
        lines[0] += f" [{result.layer_assignment}]"

    for check in result.checks:
        mark = "✓" if check.passed else "✗" if check.passed is False else "·"
        value_str = f"{check.value:.3f}" if isinstance(check.value, (int, float)) else "N/A"
        if check.threshold is not None:
            value_str += f" (threshold: {check.threshold})"
        lines.append(f"  {mark} {check.name}: {value_str} — {check.signal}")

    # Append enhancements
    if result.enhancements:
        lines.append("")
        for key, payload in result.enhancements.items():
            lines.append(f"[{key.upper()}]")
            if isinstance(payload, dict):
                for pk, pv in payload.items():
                    lines.append(f"  {pk}: {pv}")

    return "\n".join(lines)


def format_structured(
    result: ScoreResult,
    metadata: dict[str, CheckMetadata] | None = None,
) -> dict[str, Any]:
    """Return a structured dict with attribution for each check.

    Useful for MCP tool responses, JSON APIs, and audit logs. Includes
    ``method`` and ``source`` fields from ``CHECK_METADATA``.
    """
    meta_source = metadata or CHECK_METADATA
    checks_out = []
    for check in result.checks:
        meta = meta_source.get(check.name)
        checks_out.append(
            {
                **check.to_dict(),
                "display_name": (meta.public_label if meta else check.name),
                "method": meta.method if meta else "",
                "source": meta.source if meta else "",
                "explanation": meta.explanation if meta else "",
            }
        )

    return {
        "subject": result.subject,
        "tier": result.tier.value,
        "total_passed": result.total_passed,
        "total_evaluated": result.total_evaluated,
        "total_checks": result.total_checks,
        "checks": checks_out,
        "enhancements": result.enhancements,
        "layer_assignment": result.layer_assignment,
        "metadata": result.metadata,
    }


def _fallback_display(check) -> str:  # noqa: ANN001
    """Short human-readable fallback when no interpretation is set."""
    if check.value is None:
        return "data unavailable"
    if isinstance(check.value, float):
        return f"{check.value:.3f}"
    return str(check.value)


__all__ = ["format_advisor", "format_public", "format_structured"]
