# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the AI-system disclosure card.

Validates the served card against a vendored copy of the published
`@protocolwealthos/disclosure-card` JSON Schema (Draft 2020-12), and pins the
honesty-critical values that describe nexus-core as a read-only, model-less,
no-client-data service. The vendored schema is intentionally a byte-for-byte
transcription of pwos-core's `DISCLOSURE_CARD_JSON_SCHEMA`; if that standard
changes, this test should fail loudly so the card is re-reconciled.
"""

from __future__ import annotations

import re

import jsonschema
from fastapi.testclient import TestClient

from nexus_core.app import create_app
from nexus_core.app.disclosure import render_disclosure_card

# Vendored from pwos-core packages/disclosure-card/src/jsonSchema.ts (Apache-2.0).
_DISCLOSURE_CARD_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "DisclosureCard",
    "type": "object",
    "required": [
        "systemName",
        "version",
        "operator",
        "generatedAt",
        "model",
        "inferenceJurisdiction",
        "dataRetention",
        "humanOversight",
        "piiHandling",
        "knownLimitations",
        "regulatoryBasis",
        "auditTrail",
    ],
    "additionalProperties": False,
    "properties": {
        "systemName": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
        "operator": {
            "type": "object",
            "required": ["firm", "crd"],
            "additionalProperties": False,
            "properties": {
                "firm": {"type": "string", "minLength": 1},
                "crd": {"type": "string"},
            },
        },
        "generatedAt": {"type": "string", "format": "date-time"},
        "model": {
            "type": "object",
            "required": ["provider", "name", "version"],
            "additionalProperties": False,
            "properties": {
                "provider": {"type": "string", "minLength": 1},
                "name": {"type": "string", "minLength": 1},
                "version": {"type": "string", "minLength": 1},
            },
        },
        "inferenceJurisdiction": {"type": "string", "minLength": 1},
        "dataRetention": {
            "type": "object",
            "required": ["inputRetentionDays", "outputRetentionDays", "trainingUse"],
            "additionalProperties": False,
            "properties": {
                "inputRetentionDays": {"type": "integer", "minimum": 0},
                "outputRetentionDays": {"type": "integer", "minimum": 0},
                "trainingUse": {"type": "boolean"},
            },
        },
        "humanOversight": {
            "type": "object",
            "required": ["tier", "clientFacingRequiresApproval", "scope"],
            "additionalProperties": False,
            "properties": {
                "tier": {
                    "type": "string",
                    "enum": [
                        "human_in_the_loop",
                        "human_on_the_loop",
                        "no_human_oversight",
                    ],
                },
                "clientFacingRequiresApproval": {"type": "boolean"},
                "scope": {"type": "string", "minLength": 1},
            },
        },
        "piiHandling": {
            "type": "object",
            "required": ["mode", "layerCount"],
            "additionalProperties": False,
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["off", "warn", "block", "redact"],
                },
                "layerCount": {"type": "integer", "minimum": 0},
            },
        },
        "knownLimitations": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "regulatoryBasis": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
        "auditTrail": {
            "type": "object",
            "required": ["rule", "tamperEvident"],
            "additionalProperties": False,
            "properties": {
                "rule": {"type": "string", "const": "SEC 204-2"},
                "tamperEvident": {"type": "boolean"},
            },
        },
    },
}


def test_disclosure_card_matches_published_schema() -> None:
    card = render_disclosure_card()
    # Raises ValidationError on any shape/enum/type drift from the standard.
    jsonschema.validate(
        instance=card,
        schema=_DISCLOSURE_CARD_JSON_SCHEMA,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )


def test_disclosure_card_generated_at_is_iso8601() -> None:
    card = render_disclosure_card()
    # The format checker is a no-op without optional deps, so pin it explicitly.
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", card["generatedAt"]
    )


def test_disclosure_card_states_honest_posture() -> None:
    """Lock the values that describe a read-only, model-less, no-PII service.

    These assertions exist so nobody can quietly upgrade the card to look more
    'compliant' than nexus-core actually is — honest disclosure is the point.
    """
    card = render_disclosure_card()
    assert card["operator"] == {"firm": "Protocol Wealth, LLC", "crd": "335298"}
    # No language model in the served path.
    assert card["model"]["provider"] == "none"
    # Anonymous + read-only: nothing client-specific retained, no training use.
    assert card["dataRetention"] == {
        "inputRetentionDays": 0,
        "outputRetentionDays": 0,
        "trainingUse": False,
    }
    # Mirrors the firm's AI and Technology Disclosure: human-in-the-loop, with
    # human approval required before client-facing use.
    assert card["humanOversight"]["tier"] == "human_in_the_loop"
    assert card["humanOversight"]["clientFacingRequiresApproval"] is True
    # Identity-shaped keys are blocked; not the 4-layer pii-guard.
    assert card["piiHandling"]["mode"] == "block"
    # No client data on this anonymous service -> no tamper-evident trail here.
    assert card["auditTrail"]["tamperEvident"] is False


def test_disclosure_card_links_to_canonical_firm_disclosure() -> None:
    """The card must point to the authoritative human-readable disclosure."""
    card = render_disclosure_card()
    blob = " ".join(card["knownLimitations"]) + " " + card["humanOversight"]["scope"]
    assert "https://protocolwealthllc.com/disclosures/" in blob


def test_disclosure_card_has_no_unverified_markers() -> None:
    """Mirror pwos-core's assertNoVerifyMarkers publish gate: no '[VERIFY]'."""
    card = render_disclosure_card()
    for citation in card["regulatoryBasis"]:
        assert "[VERIFY]" not in citation, citation


def test_disclosure_card_served_at_well_known(
    stub_market: object, stub_fred: object
) -> None:
    app = create_app(market=stub_market, macro=stub_fred, enable_mcp=False)  # type: ignore[arg-type]
    with TestClient(app) as client:
        response = client.get("/.well-known/ai-disclosure.json")
    assert response.status_code == 200
    assert "application/json" in response.headers["content-type"]
    body = response.json()
    assert body["systemName"] == "Nexus Core (nexusmcp.site)"
    assert body["model"]["provider"] == "none"
