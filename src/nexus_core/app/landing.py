# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Landing page for the nexus-core public deployment.

A single self-contained HTML document — no template engine, no static-asset
pipeline. The page describes the public analytical surface, which has no
account/API-key gate, and points visitors at the interactive API docs and the
source repository.
"""

from __future__ import annotations

from .. import __version__
from ..disclaimers import FULL as _FULL_DISCLAIMER

_REPO_URL = "https://github.com/Protocol-Wealth/nexus-core"

_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nexus Core — open regime-adaptive financial analysis</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: #0b1020; color: #e6e9f0; line-height: 1.6;
  }}
  main {{ max-width: 760px; margin: 0 auto; padding: 4rem 1.5rem 5rem; }}
  .eyebrow {{
    font-size: .75rem; letter-spacing: .14em; text-transform: uppercase;
    color: #6f7da3; margin: 0 0 .75rem;
  }}
  h1 {{ font-size: 2.5rem; line-height: 1.15; margin: 0 0 1rem; }}
  .lede {{ font-size: 1.15rem; color: #aab3cf; margin: 0 0 2rem; }}
  .grid {{ display: grid; gap: .75rem; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
  a.card {{
    display: block; padding: 1rem 1.15rem; border: 1px solid #1f2a48;
    border-radius: 10px; background: #111830; text-decoration: none; color: inherit;
    transition: border-color .15s ease, background .15s ease;
  }}
  a.card:hover {{ border-color: #3a4f8a; background: #15203f; }}
  a.card .t {{ font-weight: 600; color: #fff; }}
  a.card .d {{ font-size: .9rem; color: #8b96b8; }}
  code {{
    background: #1a2240; padding: .12rem .4rem; border-radius: 5px;
    font-size: .88em; color: #c7d2fe;
  }}
  h2 {{ font-size: 1rem; margin: 2.5rem 0 .75rem; color: #cfd6e8; }}
  ul {{ padding-left: 1.2rem; margin: 0 0 1rem; color: #aab3cf; }}
  footer {{
    margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid #1f2a48;
    font-size: .82rem; color: #6f7da3;
  }}
  footer a {{ color: #8b96b8; }}
</style>
</head>
<body>
<main>
  <p class="eyebrow">Protocol Wealth · Open Source</p>
  <h1>Nexus Core</h1>
  <p class="lede">
    A regime-adaptive financial analysis engine, exposed as a public API and as
    Model Context Protocol (MCP) tools. Market data, macro signals, options,
    DeFi analytics, and PII-free planning math — no account or API key required.
    Remote MCP clients may complete transparent OAuth with no login.
  </p>

  <div class="grid">
    {mcp_guide_card}
    <a class="card" href="/docs">
      <div class="t">API documentation &rarr;</div>
      <div class="d">Interactive OpenAPI / Swagger explorer</div>
    </a>
    <a class="card" href="/api/regime">
      <div class="t">Current regime &rarr;</div>
      <div class="d">Live macro regime classification</div>
    </a>
    <a class="card" href="{repo}">
      <div class="t">Source on GitHub &rarr;</div>
      <div class="d">Apache-2.0 — fork it, run it, extend it</div>
    </a>
    <a class="card" href="/openapi.json">
      <div class="t">OpenAPI schema &rarr;</div>
      <div class="d">Machine-readable API contract</div>
    </a>
  </div>

  <h2>Endpoints</h2>
  <ul>
    <li><code>GET /api/regime</code> — current macro regime classification</li>
    <li><code>GET /api/regime/signals</code> — raw regime signal readings</li>
    <li><code>GET /api/market/quote/{{symbol}}</code> — latest quote (stocks, ETFs, indices, crypto)</li>
    <li><code>GET /api/market/history/{{symbol}}</code> — OHLCV price history</li>
    <li><code>GET /api/economic/{{series_id}}</code> — FRED economic series</li>
    {mcp_line}
  </ul>

  <h2>Try it — no setup</h2>
  <pre style="background:#111830;border:1px solid #1f2a48;border-radius:10px;padding:1rem 1.15rem;overflow-x:auto;font-size:.85rem;color:#d6def5"><code># current macro regime
curl https://nexusmcp.site/api/regime

# planning tools: contract handshake, then invoke one (educational, PII-free)
curl https://nexusmcp.site/mcp/tools
curl -X POST https://nexusmcp.site/mcp/tools/glide_path \\
  -H 'Content-Type: application/json' \\
  -d '{{"currentAge": 40, "retirementAge": 65, "horizonAge": 95, "startEquityWeight": 0.8, "endEquityWeight": 0.4, "shape": "linear"}}'</code></pre>

  <h2>Public surface only</h2>
  <p style="color:#aab3cf">
    This deployment exposes public data and educational analytical math. It
    contains no client data, no account surfaces, no suitability logic, no report
    production workflow, and no advisory workflow state — those live in Protocol
    Wealth's closed systems. Planning endpoints accept de-identified inputs
    only.
  </p>

  <footer>
    <p style="margin:0 0 1rem">{disclaimer}</p>
    Nexus Core v{version} · Apache-2.0 · Patent Pending USPTO&nbsp;#64/034,229 ·
    Built by <a href="https://protocolwealthllc.com">Protocol Wealth, LLC</a>
    (SEC-registered RIA, CRD&nbsp;#335298).
  </footer>
</main>
</body>
</html>
"""

_MCP_LINE = (
    '<li><code>POST /mcp</code> — Model Context Protocol endpoint '
    '(connect any MCP-compatible AI client — <a href="/mcp-guide" '
    'style="color:#c7d2fe">setup guide</a>)</li>'
)

_MCP_GUIDE_CARD = (
    '<a class="card" href="/mcp-guide">'
    '<div class="t">MCP setup guide &rarr;</div>'
    '<div class="d">Connect Claude Desktop or any MCP client — hosted or local</div>'
    "</a>"
)


def render_landing(*, mcp_enabled: bool) -> str:
    """Return the landing-page HTML.

    Args:
        mcp_enabled: Whether the MCP HTTP transport is mounted; controls
            whether the ``/mcp`` endpoint and its setup guide are advertised.
    """
    return _PAGE.format(
        repo=_REPO_URL,
        version=__version__,
        disclaimer=_FULL_DISCLAIMER,
        mcp_line=_MCP_LINE if mcp_enabled else "",
        mcp_guide_card=_MCP_GUIDE_CARD if mcp_enabled else "",
    )


__all__ = ["render_landing"]
