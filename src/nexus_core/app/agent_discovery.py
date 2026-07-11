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


def render_mcp_server_card() -> dict[str, Any]:
    """SEP-format MCP Server Card describing this deployment's ``/mcp`` transport."""
    return {
        "serverInfo": {
            "name": "nexus-core",
            "title": "Protocol Wealth — Nexus Core (public MCP)",
            "version": __version__,
            "description": (
                "Regime-adaptive financial-analysis engine exposed as Model Context "
                "Protocol tools: macro-regime classification, market and economic data, "
                "options analytics, and de-identified planning illustrations. Public "
                "educational endpoint — informational only, no advice, no trade "
                "execution, and no client data."
            ),
        },
        "provider": dict(_PROVIDER),
        "transport": {"type": "streamable-http", "endpoint": f"{_BASE}/mcp"},
        "capabilities": {
            "tools": True,
            "categories": [
                "regime-analysis — Entropic Macro Framework classification and signals",
                "market-data — quotes and price history for stocks, ETFs, indices, crypto",
                "economic-data — FRED economic series",
                "options-analytics — Black-Scholes overlays and collar worksheets (illustration only)",
                "planning-illustration — glide-path / allocation modeling; de-identified inputs only",
            ],
        },
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
