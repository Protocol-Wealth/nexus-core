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
from ..disclaimers import FULL as _FULL_DISCLAIMER

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
    public demo tools. Remote clients may complete transparent OAuth with no
    login. You can use the hosted server or run your own.
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
  <h3>Claude Code</h3>
  <p>
    Claude Code speaks remote MCP over HTTP. Add the hosted server with one
    command:
  </p>
  <pre><code>claude mcp add --transport http nexus-core {mcp_url}</code></pre>
  <p>
    or commit a <code>.mcp.json</code> to your project root so the whole team
    picks it up:
  </p>
  <pre><code>{{
  "mcpServers": {{
    "nexus-core": {{
      "type": "http",
      "url": "{mcp_url}"
    }}
  }}
}}</code></pre>
  <p>
    Run <code>/mcp</code> inside Claude Code to confirm the connection and see the
    tool list.
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
    Any MCP-compatible AI client (Claude, GPT, Gemini), or an agent platform
    such as SmythOS, can register this read-only endpoint the same way — no
    account or API key.
  </p>
  <div class="note">
    <strong>Tools not showing up?</strong> Fully quit and reopen Claude Desktop
    (not just close the window). <code>mcp-remote</code> needs Node 18+ (check
    <code>node -v</code>); if <code>npx</code> errors, run
    <code>npx -y mcp-remote@latest {mcp_url}</code> once in a terminal to
    pre-cache it. For the claude.ai web connector, if it won't attach, remove and
    re-add it — the authorize step approves itself and needs no Client ID.
  </div>

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
    <tr><td>Planning</td><td>31 PII-free tools: Monte Carlo, goal funding, deterministic cash flow, education, income layering, allocation optimization, Roth/IRMAA, report assembly</td></tr>
  </table>
  <p>
    Everything is read-only, public, and educational — no side effects, no
    advice. The exact, always-current tool list is what your client shows after
    connecting (or call <code>tools/list</code>).
  </p>

  <h2>Try it — example prompts</h2>
  <p>
    Once connected, just ask in plain language; the client picks the tool and
    fills the arguments. A few prompts that exercise the regime engine and the
    planning tools end to end:
  </p>
  <ul>
    <li>&ldquo;What macro regime are we in right now, and which signals are driving it?&rdquo;</li>
    <li>&ldquo;Score AAPL on the EMF durability framework and explain each of the eight checks.&rdquo;</li>
    <li>&ldquo;Run a Monte Carlo decumulation: age 62, retiring at 65, $1.2M traditional + $300k Roth,
      60/40 then 80/20, $120k annual spend at 2.5% COLA, Social Security $42k from 67. Use the
      EMF-regime return model and report the probability of success.&rdquo;</li>
    <li>&ldquo;Pull the current capital-market assumptions, then re-run that plan with those real
      assumptions and compare the success probability.&rdquo;</li>
    <li>&ldquo;Build a tax-aware, RMD-first withdrawal plan for a $120k need at age 73 across those
      accounts.&rdquo;</li>
    <li>&ldquo;Given the current macro regime, which covered-call strike should I write on 5 BTC
      over the next 45 days? Show the regime tilt and the coin yield.&rdquo;</li>
    <li>&ldquo;Rank the live BTC OTM calls by annualized covered-call yield, and show the IV term
      structure so I can see which expiry pays richest.&rdquo;</li>
    <li>&ldquo;Illustrate a protective collar on 5 ETH with a 20%-OTM put floor and a 25%-OTM call
      cap, and stress the book for a &plusmn;30% spot move.&rdquo;</li>
  </ul>
  <div class="note">
    The planning tools take the request as a single JSON object in a
    <code>body</code> argument, matching the pwplan-core wire contract
    (<code>contractVersion 0.1.0</code>). The client assembles it from your
    prompt; inputs are de-identified — age, never date of birth.
  </div>

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
    no SDK. These are plain REST endpoints (distinct from the MCP transport
    above). Production callers can send a Nexus service API key through the
    REST/JSON boundary when restricted mode is enabled.
  </p>
  <h3>The handshake</h3>
  <p>
    Call <code>GET /api/planning/tools</code> first — it returns the contract version and
    the available tool ids, so the client can confirm compatibility before
    sending any work:
  </p>
  <pre><code>GET https://nexusmcp.site/api/planning/tools
&rarr; {{ "contractVersion": "0.1.0", "tools": [ ... ] }}</code></pre>
  <p>
    The wire contract is <code>contractVersion 0.1.0</code> — every successful
    tool response echoes it, and the client rejects a mismatch.
  </p>
  <h3>The planning tools</h3>
  <p>Invoke a tool with <code>POST /api/planning/tools/{{tool_id}}</code> and a JSON body. Legacy <code>/mcp/tools</code> aliases remain for older clients:</p>
  <ul>
    <li><code>monte_carlo_decumulation</code> — primary retirement decumulation simulation</li>
    <li><code>solve_goal</code> — solve one planning variable to a target success probability</li>
    <li><code>analyze_goals</code> — goal-funding status + shared-pool priority allocation</li>
    <li><code>project_cash_flow</code> — deterministic year-by-year cash-flow and net-worth projection</li>
    <li><code>cashflow_planning_bridge</code> — derived monthly close values into planning assumptions</li>
    <li><code>cash_reserve_analysis</code> — cash reserve coverage and funding status</li>
    <li><code>budget_pacing_projection</code> — month-end budget pace from aggregate spending</li>
    <li><code>education_funding</code> — education cost FV and savings-need solver</li>
    <li><code>education_vehicle_rules</code> — reference 529 / Coverdell / UGMA-UTMA rule table</li>
    <li><code>income_layering</code> — stacked retirement income timeline with Social Security, pensions/annuities, RMDs, tax-aware withdrawals, optional state-tax layers, and optional spouse/survivor modeling</li>
    <li><code>glide_path</code> — equity weight by age across the horizon</li>
    <li><code>tax_aware_withdrawal</code> — RMD-first, tax-efficient withdrawal sequencing with optional birthYear and state/residency policy</li>
    <li><code>correlation_matrix</code> — real-data return correlation across asset classes</li>
    <li><code>capital_market_assumptions</code> — forward return / volatility / correlation assumptions</li>
    <li><code>historical_blend</code> — historical index-blend returns, trailing windows, growth-of-dollar, and sigma bands</li>
    <li><code>regime_return_generator</code> — live regime + transition matrix for path generation</li>
    <li><code>roth_conversion</code> — convert-now vs. leave-pre-tax after-tax comparison + breakeven rate</li>
    <li><code>sequence_of_returns_stress</code> — ordering effect on a fixed return set (worst/best/as-given)</li>
    <li><code>rmd</code> — required minimum distribution (IRS Uniform Lifetime Table; optional birthYear policy)</li>
    <li><code>tax_bracket_headroom</code> — marginal bracket + room before the next rate (Roth-fill)</li>
    <li><code>social_security_claiming</code> — benefit by claim age 62–70 + breakeven ages</li>
    <li><code>regime_conditioned_swr</code> — base safe withdrawal rate adjusted for the live regime</li>
    <li><code>portfolio_xray</code> — regime-aware structural diagnostics (concentration, tax-location, regime sensitivity)</li>
    <li><code>optimize_allocation</code> — optimizer-driven target asset-class weights</li>
    <li><code>fire</code> — FIRE / Coast-FIRE calculator</li>
    <li><code>risk_metrics</code> — annualized return/volatility, Sharpe, Sortino, drawdown, VaR/CVaR</li>
    <li><code>rebalance</code> — target-vs-current drift and self-financing trade list</li>
    <li><code>irmaa_headroom</code> — projected Medicare IRMAA headroom</li>
    <li><code>analyze_roth_conversion</code> — composite Roth conversion analysis under tax + IRMAA ceilings</li>
    <li><code>sequence_conversions</code> — multi-year Roth conversion sequencing</li>
    <li><code>build_planning_report</code> — ordered, render-ready envelope from de-identified planning outputs</li>
  </ul>
  <div class="note">
    <code>monte_carlo_decumulation</code> takes an optional <code>retirementAge</code>:
    the portfolio accumulates untouched until that age, then decumulates. Omit it
    and the engine withdraws from <code>currentAge</code>; pwplan-core's UI defaults
    the field to <strong>65</strong>. Optional <code>spendSchedule</code> entries
    adjust the gross spend after retirement age: <code>delta</code> adds a
    recurring bump/reduction over an age range, <code>override</code> replaces
    the base spend for an age range, and <code>one_time</code> adds a single
    lump expense. Optional <code>guardrails</code> enables Guyton-Klinger
    dynamic withdrawals. Inputs are de-identified — the engine is PII-free and
    works on age, never date of birth. Monte Carlo and scenario outputs are
    illustrative model results from hypothetical assumptions — not predictions
    or guarantees of any individual outcome.
  </div>
  <h3>A worked request — the primary tool</h3>
  <p>
    <code>monte_carlo_decumulation</code> over a de-identified portfolio. The
    response echoes <code>contractVersion</code> and carries
    <code>successProbability</code> with a Wilson interval, a
    <code>terminalValues</code> percentile map, <code>medianBalanceByYear</code>,
    <code>depletionStats</code>, sticky <code>depletionCurve</code>,
    <code>conditionalShortfall</code>, <code>firstDecadeReturnVsOutcome</code>
    deciles, and a <code>regimePathSummary</code> for the regime-aware models:
  </p>
  <pre><code>curl -s {mcp_url}tools/monte_carlo_decumulation \\
  -H 'content-type: application/json' \\
  -d '{{
    "contractVersion": "0.1.0",
    "currentAge": 62, "retirementAge": 65, "horizonAge": 95,
    "accounts": [
      {{"type": "traditional", "balance": 1200000,
       "allocation": {{"us_equity": 0.6, "us_bonds": 0.4}}}}
    ],
    "assetClasses": [
      {{"id": "us_equity", "label": "US Equity",
       "expectedReturn": 0.07, "volatility": 0.16, "lambda": 0.35}},
      {{"id": "us_bonds", "label": "US Bonds",
       "expectedReturn": 0.03, "volatility": 0.05, "lambda": 0.1}}
    ],
    "annualSpend": 120000, "spendColaRate": 0.025,
    "guaranteedIncome": [
      {{"label": "Social Security", "annualAmount": 42000,
       "startAge": 67, "colaRate": 0.02}}
    ],
    "spendSchedule": [
      {{"mode": "delta", "startAge": 91, "endAge": 95, "amount": 70000}}
    ],
    "filingStatus": "married_joint", "returnModel": "emf_regime", "paths": 10000
  }}'</code></pre>

  <div class="grid"></div>

  <footer>
    <p style="margin:0 0 1rem">{disclaimer}</p>
    Nexus Core v{version} · Apache-2.0 ·
    <a href="/docs">REST API docs</a> ·
    <a href="{repo}">Source on GitHub</a>
  </footer>
</main>
</body>
</html>
"""


def render_mcp_guide() -> str:
    """Return the MCP setup-guide HTML."""
    return _PAGE.format(
        repo=_REPO_URL, mcp_url=_MCP_URL, version=__version__, disclaimer=_FULL_DISCLAIMER
    )


__all__ = ["render_mcp_guide"]
