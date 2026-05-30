# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""MCP setup guide page for the nexus-core public deployment.

A single self-contained HTML document (no template engine, no static assets)
that explains how to connect an MCP client to the nexus-core server — either
the hosted endpoint at ``nexusmcp.site/mcp`` or a local ``nexus-core mcp``
process. Linked from the landing page.
"""

from __future__ import annotations

from .. import __version__

_REPO_URL = "https://github.com/Protocol-Wealth/nexus-core"
_MCP_URL = "https://nexusmcp.site/mcp/"

_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nexus Core — MCP server setup</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; min-height: 100vh;
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    background: #0b1020; color: #e6e9f0; line-height: 1.6;
  }}
  main {{ max-width: 760px; margin: 0 auto; padding: 3rem 1.5rem 5rem; }}
  .eyebrow {{
    font-size: .75rem; letter-spacing: .14em; text-transform: uppercase;
    color: #6f7da3; margin: 0 0 .75rem;
  }}
  a.back {{ color: #8b96b8; text-decoration: none; font-size: .9rem; }}
  a.back:hover {{ color: #c7d2fe; }}
  h1 {{ font-size: 2.1rem; line-height: 1.15; margin: .5rem 0 1rem; }}
  .lede {{ font-size: 1.1rem; color: #aab3cf; margin: 0 0 2rem; }}
  h2 {{ font-size: 1.2rem; margin: 2.5rem 0 .5rem; color: #fff; }}
  h3 {{ font-size: 1rem; margin: 1.5rem 0 .5rem; color: #cfd6e8; }}
  p {{ color: #aab3cf; }}
  ul {{ padding-left: 1.2rem; color: #aab3cf; }}
  li {{ margin: .25rem 0; }}
  code {{
    background: #1a2240; padding: .12rem .4rem; border-radius: 5px;
    font-size: .88em; color: #c7d2fe;
  }}
  pre {{
    background: #111830; border: 1px solid #1f2a48; border-radius: 10px;
    padding: 1rem 1.15rem; overflow-x: auto; font-size: .85rem; color: #d6def5;
  }}
  pre code {{ background: none; padding: 0; color: inherit; }}
  .note {{
    border-left: 3px solid #3a4f8a; background: #111830; padding: .75rem 1rem;
    border-radius: 0 8px 8px 0; margin: 1rem 0; font-size: .92rem;
  }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .92rem; }}
  th, td {{ text-align: left; padding: .5rem .6rem; border-bottom: 1px solid #1f2a48; }}
  th {{ color: #cfd6e8; }}
  td {{ color: #aab3cf; }}
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
  <a class="back" href="/">&larr; Back to Nexus Core</a>
  <h1>Connect to the MCP server</h1>
  <p class="lede">
    Nexus Core speaks the <a href="https://modelcontextprotocol.io" style="color:#c7d2fe">Model
    Context Protocol</a>, so any MCP-compatible AI client can call its
    regime-aware financial analysis as tools — no account, no API key, no auth.
    You can use the hosted server or run your own.
  </p>

  <h2>Option A — Use the hosted server (no install)</h2>
  <p>
    The server is live at <code>{mcp_url}</code> (MCP over HTTP / Streamable
    HTTP). Clients that support remote MCP servers can add that URL directly.
  </p>
  <h3>Claude.ai (web &amp; desktop app)</h3>
  <p>
    Settings &rarr; Connectors &rarr; <em>Add custom connector</em>, paste the URL above,
    and add it. Claude completes a <strong>transparent authorization automatically</strong> —
    there is no account or login (nexus-core is public); you may briefly see an authorize
    step that approves itself. No OAuth Client ID needs to be entered.
  </p>
  <h3>Claude Desktop</h3>
  <p>
    Claude Desktop connects to local processes, so bridge to the hosted URL with
    <code>mcp-remote</code>. Add this to your
    <code>claude_desktop_config.json</code> (Settings → Developer → Edit Config):
  </p>
  <pre><code>{{
  "mcpServers": {{
    "nexus-core": {{
      "command": "npx",
      "args": ["-y", "mcp-remote", "{mcp_url}"]
    }}
  }}
}}</code></pre>
  <p>
    Config file location — macOS:
    <code>~/Library/Application Support/Claude/claude_desktop_config.json</code>;
    Windows: <code>%APPDATA%\\Claude\\claude_desktop_config.json</code>. Restart
    Claude Desktop, then look for the nexus-core tools in the tools menu.
  </p>
  <h3>Other clients (Cursor, Cline, custom)</h3>
  <p>
    Most clients that support remote MCP servers accept the URL directly — point
    them at <code>{mcp_url}</code> with the HTTP / Streamable-HTTP transport.
  </p>

  <h2>Option B — Run it locally (stdio)</h2>
  <p>Install from source (Python 3.12+), then run the stdio server:</p>
  <pre><code>pip install "nexus-core[mcp] @ git+{repo}.git"

# optional: a free FRED API key sharpens the macro signals
export FRED_API_KEY=your_key

nexus-core mcp        # MCP server over stdio</code></pre>
  <p>Point Claude Desktop at the local command:</p>
  <pre><code>{{
  "mcpServers": {{
    "nexus-core": {{
      "command": "nexus-core",
      "args": ["mcp"]
    }}
  }}
}}</code></pre>
  <div class="note">
    The local stdio server and the hosted <code>/mcp</code> endpoint expose the
    <strong>same tool set</strong>. External integrations that need a key (e.g.
    FRED for macro precision) degrade gracefully when the key is absent.
  </div>

  <h2>What you get — the tools</h2>
  <table>
    <tr><th>Area</th><th>Tools</th></tr>
    <tr><td>Regime</td><td>current macro regime classification + raw signal readings</td></tr>
    <tr><td>Scoring</td><td>8-check EMF asset score on SEC EDGAR fundamentals</td></tr>
    <tr><td>Market</td><td>quotes &amp; OHLCV history (stocks, ETFs, indices, crypto)</td></tr>
    <tr><td>Economic</td><td>FRED economic series</td></tr>
    <tr><td>Options</td><td>Black-Scholes price + Greeks; covered-call / cash-secured-put / collar overlays</td></tr>
    <tr><td>Crypto options</td><td>Deribit instruments + IV/Greeks (BTC, ETH, SOL, XRP, TRX, AVAX)</td></tr>
    <tr><td>DeFi</td><td>DefiLlama TVL by protocol and chain</td></tr>
  </table>
  <p>
    Everything is read-only, public, and educational — no side effects, no
    advice. The exact, always-current tool list is what your client shows after
    connecting (or call <code>tools/list</code>).
  </p>

  <h2>Verify the connection</h2>
  <p>Inspect the server interactively with the official MCP Inspector:</p>
  <pre><code># hosted
npx @modelcontextprotocol/inspector {mcp_url}

# local
npx @modelcontextprotocol/inspector nexus-core mcp</code></pre>

  <h2>Connecting pwplan-core to nexus-core</h2>
  <p>
    <a href="https://github.com/Protocol-Wealth/pwplan-core" style="color:#c7d2fe">pwplan-core</a>
    is the open-source, browser-based financial-planning shell. It runs entirely
    in the browser and calls nexus-core's planning engine directly over HTTP —
    no account, no API key, no SDK. These are plain REST endpoints (distinct from
    the MCP transport above), served with permissive CORS so a browser can reach
    them.
  </p>
  <h3>The handshake</h3>
  <p>
    Call <code>GET /mcp/tools</code> first — it returns the contract version and
    the available tool ids, so the client can confirm compatibility before
    sending any work:
  </p>
  <pre><code>GET {mcp_url}tools
&rarr; {{ "contractVersion": "0.1.0", "tools": [ ... ] }}</code></pre>
  <p>
    The wire contract is <code>contractVersion 0.1.0</code> — every successful
    tool response echoes it, and the client rejects a mismatch.
  </p>
  <h3>The six planning tools</h3>
  <p>Invoke a tool with <code>POST /mcp/tools/{{tool_id}}</code> and a JSON body:</p>
  <ul>
    <li><code>monte_carlo_decumulation</code> — primary retirement decumulation simulation</li>
    <li><code>glide_path</code> — equity weight by age across the horizon</li>
    <li><code>tax_aware_withdrawal</code> — RMD-first, tax-efficient withdrawal sequencing</li>
    <li><code>correlation_matrix</code> — real-data return correlation across asset classes</li>
    <li><code>capital_market_assumptions</code> — forward return / volatility / correlation assumptions</li>
    <li><code>regime_return_generator</code> — live regime + transition matrix for path generation</li>
  </ul>
  <div class="note">
    <code>monte_carlo_decumulation</code> takes an optional <code>retirementAge</code>:
    the portfolio accumulates untouched until that age, then decumulates. Omit it
    and the engine withdraws from <code>currentAge</code>; pwplan-core's UI defaults
    the field to <strong>65</strong>. Inputs are de-identified — the engine is
    PII-free and works on age, never date of birth.
  </div>

  <div class="grid"></div>

  <footer>
    Nexus Core v{version} · Apache-2.0 ·
    <a href="/docs">REST API docs</a> ·
    <a href="{repo}">Source on GitHub</a><br>
    For educational and research purposes only. Not investment advice.
  </footer>
</main>
</body>
</html>
"""


def render_mcp_guide() -> str:
    """Return the MCP setup-guide HTML."""
    return _PAGE.format(repo=_REPO_URL, mcp_url=_MCP_URL, version=__version__)


__all__ = ["render_mcp_guide"]
