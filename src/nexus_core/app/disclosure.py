# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Machine-readable AI-system disclosure card for the public deployment.

Conforms to the `@protocolwealthos/disclosure-card` open-standard schema (a
sibling pwos-core package) and **mirrors Protocol Wealth's published "AI and
Technology Disclosure"** — the authoritative, human-readable source the card
links to (see ``_CANONICAL_DISCLOSURE_URL``). The card is the machine-readable
companion; the firm's disclosures page is canonical.

Posture taken straight from the firm disclosure: AI-assisted tools support
research, drafting, operational workflows, and educational communications; human
adviser + compliance oversight is required before any client-facing
recommendation or production publication of regulated content; automated systems
make no final investment decisions and do not execute trades or transfer assets;
AI output is never the sole basis for advisory decisions; data minimization +
security controls apply with third-party technology providers; supervisory
records of AI-assisted workflows are kept as part of the compliance program.

The remaining values stay accurate to *this* deployment specifically — a
read-only, model-less, no-client-data public analysis API + MCP tool server:
``model.provider`` is ``"none"`` (no LLM in the served path; transformers/torch
are optional extras, never imported by ``app`` or ``mcp``); data retention is
zero (anonymous, read-only); PII handling is ``block`` (the planning gateway
rejects identity-shaped keys). Served at ``/.well-known/ai-disclosure.json`` and
pointed to from ``llms.txt``.

Bump ``_GENERATED_AT`` whenever the card's content changes (it records when this
disclosure was authored / last reviewed, NOT the time of each request); keep the
posture in sync with the canonical disclosures page.
"""

from __future__ import annotations

from typing import Any

from .. import __version__

#: Authoritative human-readable disclosure this card mirrors + links to.
_CANONICAL_DISCLOSURE_URL = "https://protocolwealthllc.com/disclosures/"

#: When this disclosure content was last authored / reviewed (ISO-8601, UTC).
#: Pinned, not "now": stamping the request time would falsely imply continuous
#: re-review. Bump on any content change.
_GENERATED_AT = "2026-06-01T00:00:00Z"


def render_disclosure_card() -> dict[str, Any]:
    """Return the nexus-core public-deployment disclosure card as a dict.

    Conforms to the disclosure-card JSON Schema (Draft 2020-12) and mirrors the
    firm's published AI and Technology Disclosure (see the module docstring).
    """
    return {
        "systemName": "Nexus Core (nexusmcp.site)",
        "version": __version__,
        "operator": {"firm": "Protocol Wealth, LLC", "crd": "335298"},
        "generatedAt": _GENERATED_AT,
        # No language model in this deployment's served path; deterministic engine.
        "model": {
            "provider": "none",
            "name": "not_applicable",
            "version": "not_applicable",
        },
        # No model inference happens here, so there is no inference jurisdiction.
        "inferenceJurisdiction": "not_applicable",
        # Data minimization: anonymous + read-only, nothing client-specific stored.
        "dataRetention": {
            "inputRetentionDays": 0,
            "outputRetentionDays": 0,
            "trainingUse": False,
        },
        # Mirrors the firm's AI and Technology Disclosure posture.
        "humanOversight": {
            "tier": "human_in_the_loop",
            "clientFacingRequiresApproval": True,
            "scope": (
                "Human adviser and compliance oversight is required before any "
                "client-facing recommendation or production publication of "
                "regulated content; AI-assisted output may contain errors and is "
                "never the sole basis for advisory decisions. Automated systems "
                "make no final investment decisions and do not execute trades or "
                "transfer assets. This open service is research/educational and "
                "produces no client-facing deliverables directly. See "
                f"{_CANONICAL_DISCLOSURE_URL}"
            ),
        },
        # The planning gateway rejects identity-shaped keys (structural tripwire);
        # the rest of the surface takes tickers/symbols, never PII. One layer —
        # not the 4-layer pwos-core pii-guard.
        "piiHandling": {"mode": "block", "layerCount": 1},
        "knownLimitations": [
            "Educational and informational use only — not investment, tax, legal, "
            "or financial advice; AI-assisted output may contain errors and is not "
            "relied on as the sole basis for advisory decisions.",
            "This deployment runs no language model in its served path — a "
            "deterministic analysis engine and MCP tool server. The 'model' block "
            "is not applicable; any LLM that calls these tools is a separate system.",
            "Public and read-only: accepts no client data, stores no client prompts "
            "or outputs, and requires no authentication (data minimization).",
            "Regime classifications and durability scores are probabilistic labels, "
            "not verdicts, predictions, or guarantees.",
            "External data integrations degrade to null / empty / HTTP 503 when a "
            "provider API key is absent.",
            "Authoritative human-readable disclosure — Protocol Wealth AI and "
            f"Technology Disclosure: {_CANONICAL_DISCLOSURE_URL}",
        ],
        "regulatoryBasis": [
            "SEC Rule 204-2 (supervisory records of AI-assisted workflows)",
            "Reg S-P (data minimization + security controls with third-party "
            "technology providers)",
            "SEC Marketing Rule 206(4)-1 (standardized disclaimers on analytical "
            "output)",
        ],
        # Schema pins rule to the literal "SEC 204-2"; supervisory records of
        # AI-assisted workflows are kept at the firm level. This anonymous public
        # service holds no client data, so it carries no tamper-evident trail.
        "auditTrail": {"rule": "SEC 204-2", "tamperEvident": False},
    }


__all__ = ["render_disclosure_card"]
