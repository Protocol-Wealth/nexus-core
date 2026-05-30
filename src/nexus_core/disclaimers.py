# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Canonical compliance disclaimers — the single source of truth.

Every output surface imports its disclaimer from here; nothing hand-writes a
disclaimer string. That keeps the wording consistent and auditable across the
MCP tools, the REST API, the web pages, the OpenAPI description, and ``llms.txt``.

The text is client-facing regulatory copy. Changing it is a compliance decision
(RIA Marketing Rule / SEC Rule 206(4)-1), not a routine edit.

Variants:

- :data:`TERSE` — for JSON tool/REST responses where space is tight.
- :data:`MC_DISCLAIMER` — for Monte Carlo / scenario / projection-shaped
  planning outputs, which need an explicit "illustrative, not a prediction"
  caveat.
- :data:`FULL` — the comprehensive text for web pages, the OpenAPI description,
  docs, and ``llms.txt``.
- :data:`SAFEGUARDS` — a short statement of the risk mitigations the service
  applies (read-only, non-custodial, PII-free, no autonomous decisions).
"""

from __future__ import annotations

from typing import Any

#: Terse — attached as the ``disclaimer`` field on JSON tool/REST responses.
TERSE = (
    "Educational and informational use only. Not investment, tax, legal, or "
    "financial advice, and not a recommendation. Data and outputs are provided "
    "as-is, without warranty. Past performance does not guarantee future results."
)

#: For Monte Carlo / scenario / projection-shaped outputs (the planning engine).
#: Emphasises that a success-probability or terminal-value figure is an
#: illustration, never a forecast or guarantee.
MC_DISCLAIMER = (
    "Educational and informational use only. Not investment, tax, legal, or "
    "financial advice. These are illustrative model results computed from "
    "hypothetical, user-supplied assumptions — not predictions, forecasts, or "
    "guarantees of any individual's outcome. Past performance does not guarantee "
    "future results."
)

#: Short statement of the risk mitigations the service applies. Surfaced on the
#: web pages and in agent-facing docs so the safeguards are discoverable.
SAFEGUARDS = (
    "Safeguards: this service is read-only and non-custodial — it never holds "
    "funds or private keys, executes no trades, and makes no autonomous "
    "investment decisions. It stores no personal data; planning inputs are "
    "de-identified (age, never date of birth) and identity fields are rejected. "
    "Any AI-generated narrative is informational only and is not reviewed advice."
)

#: Fuller text for web pages, the OpenAPI description, docs, and ``llms.txt``.
FULL = (
    "Nexus Core is provided for educational and informational purposes only. It "
    "is not investment, tax, legal, or financial advice, not a recommendation, "
    "and not a suitability determination. Quantitative scores and confidence "
    "tiers are analytical views of public data, not buy, sell, or hold calls. "
    "Monte Carlo and scenario outputs are illustrative model results from "
    "hypothetical assumptions — not predictions or guarantees of future results; "
    "past performance does not guarantee future results. Any AI-generated "
    "narrative is informational only and is not reviewed advice. All data and "
    "outputs are provided as-is, without warranty of any kind. Consult a "
    "qualified professional before making any financial decision. " + SAFEGUARDS + " "
    "Operated by Protocol Wealth, LLC; governing law Delaware."
)


def with_disclaimer(payload: dict[str, Any], text: str = TERSE) -> dict[str, Any]:
    """Return ``payload`` with a ``disclaimer`` key (does not overwrite one already set)."""
    payload.setdefault("disclaimer", text)
    return payload


__all__ = ["FULL", "MC_DISCLAIMER", "SAFEGUARDS", "TERSE", "with_disclaimer"]
