# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Agent-discovery surfaces for the public deployment.

Static, in-process well-known documents that let AI agents discover the Nexus
MCP + REST API without prior knowledge: the MCP Server Card (SEP), an RFC 9727
API catalogue, ``robots.txt`` (AI-crawler rules + Content-Signal), and a minimal
sitemap. These describe the *same* public, read-only, no-PII surface already
documented in ``llms.txt`` and the MCP guide — they add no capability and take no
advice position (the ``policy.posture`` is the canonical ``disclaimers.TERSE``).
"""

from __future__ import annotations

import os
from typing import Any

from .. import __version__
from ..disclaimers import TERSE as _TERSE

_BASE = "https://nexusmcp.site"

_PROVIDER = {
    "name": "Protocol Wealth, LLC",
    "url": "https://protocolwealthllc.com",
    "registration": "SEC-registered investment adviser, CRD #335298",
}

_POLICY = {
    "posture": _TERSE,
    "data": (
        "Public endpoint; read-only and non-custodial. Accepts de-identified inputs "
        "only and holds no client nonpublic information."
    ),
    "terms": "https://protocolwealthllc.com/disclosures",
}

#: AI crawler user-agents named explicitly in robots.txt.
_AI_BOTS = [
    "GPTBot",
    "OAI-SearchBot",
    "ChatGPT-User",
    "Claude-Web",
    "ClaudeBot",
    "anthropic-ai",
    "Google-Extended",
    "PerplexityBot",
    "CCBot",
    "Applebot-Extended",
]

#: Public HTML/text surfaces for the sitemap (the JSON API itself is not indexed).
_SITEMAP_PATHS = ["/", "/mcp-guide", "/docs", "/llms.txt"]


def _public_mcp_profile() -> str:
    """Active public MCP tool profile (``NEXUS_PUBLIC_MCP_PROFILE``): ``full`` or ``demo``.

    Read here rather than imported from ``app.mcp_mount`` to keep this module free of
    the optional ``fastmcp`` dependency. The env var is the shared contract, so the
    published card reflects the tools the ``/mcp`` transport actually registers.
    """
    return os.environ.get("NEXUS_PUBLIC_MCP_PROFILE", "full").strip().lower() or "full"


def _mcp_protocol_version() -> str:
    """The MCP protocol version this deployment negotiates, from the installed SDK."""
    try:
        from mcp.types import LATEST_PROTOCOL_VERSION

        return str(LATEST_PROTOCOL_VERSION)
    except Exception:  # pragma: no cover - core-only installs without the mcp SDK
        return "2025-06-18"


def render_mcp_server_card() -> dict[str, Any]:
    """MCP Server Card describing this deployment's ``/mcp`` transport.

    Mirrors the MCP ``InitializeResult`` shape — ``protocolVersion``, ``capabilities``
    as a ServerCapabilities object, ``serverInfo`` — plus SEP discovery extras
    (transport, provider, policy). Profile-aware: the ``instructions`` reflect whether
    the public transport runs the full tool set or the closed-world demo profile, so
    agents are not told about tools ``tools/list`` will not expose.
    """
    if _public_mcp_profile() == "demo":
        tool_summary = (
            "Demo profile — closed-world tools only: option pricing and collar "
            "worksheets (Black-Scholes, illustration only) plus server health and "
            "self-description. No live-vendor regime, market-data, economic-data, or "
            "planning tools are exposed on this transport."
        )
    else:
        tool_summary = (
            "Full profile: macro-regime classification and signals, market quotes and "
            "history, FRED economic series, options analytics (illustration only), and "
            "de-identified planning illustrations."
        )
    return {
        "protocolVersion": _mcp_protocol_version(),
        "serverInfo": {
            "name": "nexus-core",
            "title": "Protocol Wealth — Nexus Core (public MCP)",
            "version": __version__,
        },
        "capabilities": {"tools": {"listChanged": False}},
        "instructions": (
            "Regime-adaptive financial-analysis engine exposed as Model Context Protocol "
            f"tools. {tool_summary} Informational and educational only — not investment, "
            "tax, or legal advice, no trade execution, and no client data. Call "
            "tools/list after connecting for the exact tool set."
        ),
        "transport": {"type": "streamable-http", "endpoint": f"{_BASE}/mcp"},
        "provider": dict(_PROVIDER),
        "documentation": f"{_BASE}/mcp-guide",
        "openSource": "https://github.com/Protocol-Wealth/nexus-core",
        "policy": dict(_POLICY),
    }


def render_api_catalog() -> dict[str, Any]:
    """RFC 9727 (``application/linkset+json``) API catalogue for the deployment."""
    return {
        "linkset": [
            {
                "anchor": f"{_BASE}/",
                "service-desc": [
                    {"href": f"{_BASE}/openapi.json", "type": "application/json", "title": "OpenAPI specification"},
                    {
                        "href": f"{_BASE}/.well-known/mcp/server-card.json",
                        "type": "application/json",
                        "title": "MCP Server Card — Nexus Core public MCP",
                    },
                ],
                "service-doc": [
                    {"href": f"{_BASE}/mcp-guide", "type": "text/html", "title": "MCP setup guide"},
                    {"href": f"{_BASE}/llms.txt", "type": "text/markdown", "title": "Agent site map (llms.txt)"},
                ],
                "status": [
                    {"href": f"{_BASE}/health", "type": "application/json", "title": "Health check"},
                ],
            }
        ]
    }


def api_catalog_link_header() -> str:
    """The RFC 8288 ``Link`` header advertised on the landing page."""
    return (
        '</.well-known/api-catalog>; rel="api-catalog", '
        '</openapi.json>; rel="service-desc"; type="application/json", '
        '</mcp-guide>; rel="service-doc"; type="text/html"'
    )


def render_robots_txt() -> str:
    """``robots.txt``: allow the public surface, name AI crawlers, declare Content-Signal."""
    lines = [
        "# nexus-core (https://nexusmcp.site) — public, read-only financial-analysis",
        "# API + MCP, operated by Protocol Wealth, LLC. AI systems are welcome on the",
        "# public surface. See /llms.txt and /.well-known/mcp/server-card.json.",
        "",
        "User-agent: *",
        "Content-Signal: search=yes, ai-input=yes, ai-train=no",
        "Allow: /",
        "",
    ]
    for bot in _AI_BOTS:
        lines += [f"User-agent: {bot}", "Allow: /", ""]
    lines += [f"Sitemap: {_BASE}/sitemap.xml", ""]
    return "\n".join(lines)


def render_sitemap_xml() -> str:
    """Minimal sitemap of the public HTML/text surfaces (the JSON API is not indexed)."""
    urls = "".join(f"  <url><loc>{_BASE}{p}</loc></url>\n" for p in _SITEMAP_PATHS)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}"
        "</urlset>\n"
    )


__all__ = [
    "api_catalog_link_header",
    "render_api_catalog",
    "render_mcp_server_card",
    "render_robots_txt",
    "render_sitemap_xml",
]
