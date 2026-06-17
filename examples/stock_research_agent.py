# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Reference stock-idea agent — Claude Agent SDK over the hosted nexus-core MCP.

A minimal agent that lets Claude evaluate a single equity idea (e.g. a name a
research service has flagged) through nexus-core's **regime + EMF durability**
lens, conversationally. It reads the live macro regime, runs the 8-check
``score_asset`` durability assessment, pulls price/trend context, and synthesizes
a graded **REGIME×SCORE dossier** — explicitly labelling the legs nexus-core does
NOT surface today (valuation, analyst consensus, forward estimates, real equity
IV/skew, news/sentiment) as gaps rather than inventing them.

It talks to the PUBLIC hosted server at ``nexusmcp.site/mcp`` (no account, no key,
read-only), so you do NOT need to install or run nexus-core to try it.

Run::

    pip install claude-agent-sdk      # not a nexus-core dependency; this demo only
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/stock_research_agent.py

Educational illustration only — nothing here is investment, tax, legal, or
financial advice. The dossier is a **graded assessment with explicit confidence,
not a buy/sell/hold call**: nexus-core emits a probabilistic confidence *tier*,
never a verdict, and a human makes any decision. See ``docs/STOCK-RESEARCH-
ENHANCEMENT.md`` for the planned tools that fill the labelled gaps.
"""

from __future__ import annotations

import asyncio

#: The public, read-only hosted MCP endpoint (MCP over HTTP / Streamable HTTP).
MCP_URL = "https://nexusmcp.site/mcp/"

#: Key for the server in the SDK's mcp_servers map; tool names derive from it as
#: ``mcp__<key>__<tool_id>``.
SERVER_KEY = "nexus"

#: Least-privilege allowlist: the live regime read + the EMF score + price/macro
#: context. Every one is a SHIPPED, read-only tool today — no enhancement scaffold
#: required. (The valuation / analyst / estimates / equity-IV / news tools that
#: would complete the buy-case are not yet built; see docs/STOCK-RESEARCH-
#: ENHANCEMENT.md. ``describe``/``health`` are orientation/diagnostics.)
_STOCK_RESEARCH_TOOLS = (
    "describe",
    "health",
    "current_regime",
    "regime_signals",
    "score_asset",
    "get_quote",
    "get_price_history",
    "get_economic_series",
)
ALLOWED_TOOLS = [f"mcp__{SERVER_KEY}__{name}" for name in _STOCK_RESEARCH_TOOLS]

SYSTEM_PROMPT = (
    "You are a regime-aware equity-research assistant backed by the nexus-core "
    "engine, exposed as MCP tools. Evaluate ONE stock idea by working the tools "
    "rather than guessing numbers, then deliver a graded dossier:\n"
    "  1. Orient: call describe (tool catalog + the per-family symbology rules) "
    "and health (which upstreams are live). Equities use a Yahoo ticker (AAPL, "
    "SPY, ^GSPC).\n"
    "  2. Frame: call current_regime + regime_signals. The live macro regime "
    "(GROWTH / TRANSITION / HARD_ASSET / DEFLATION / REPRESSION) is the lens every "
    "later step is read through — it is the SAME regime score_asset injects into "
    "its alignment checks, so it is not optional context.\n"
    "  3. Spine: call score_asset(ticker) — the 8-check EMF durability assessment. "
    "Capture the confidence TIER, the passed-count, and EVERY per-check verdict, "
    "especially check 6 (Regime Alignment — is the asset's durability layer "
    "favored in THIS regime?) and check 7 (Sector Tailwind). A check that returns "
    "insufficient_data is NOT a fail — report it as such.\n"
    "  4. Price/trend: call get_quote (PRICE ONLY — no change/%/volume/valuation) "
    "and get_price_history(days=365), then note the 1y trend, drawdown, and "
    "position-in-range from the bars.\n"
    "  5. Macro: call get_economic_series('DGS10') for the rate/curve backdrop "
    "behind the regime read.\n"
    "  6. Synthesize a REGIME×SCORE cross-check and name exactly ONE cell:\n"
    "     (a) regime FAVORS the layer AND tier HIGH/MODERATE -> 'durable idea "
    "aligned with the tape';\n"
    "     (b) regime favors BUT tier weak -> 'right environment, fails the quality "
    "rubric';\n"
    "     (c) regime HOSTILE BUT tier strong -> 'good company, wrong regime — "
    "size/timing caution';\n"
    "     (d) hostile AND weak -> 'no edge on either axis'.\n"
    "     Cite the specific check verdicts and regime signals that put it there.\n"
    "HONESTY RULE (non-negotiable): nexus-core does NOT surface valuation (P/E, "
    "DCF), analyst consensus / price targets, forward EPS/revenue estimates, real "
    "equity options IV/skew, or news/sentiment today. Render each of those as an "
    "explicit '— not available from nexus-core today (planned: see the research "
    "scaffold)' line. NEVER fabricate them, and NEVER restate any output as advice, "
    "a recommendation, a price target, or a guarantee. PRESERVE the `disclaimer` "
    "field. The deliverable is a confidence-tiered ASSESSMENT, not a buy/sell call."
)

# A public, illustrative stock-idea question — a single ticker, evaluated as a
# candidate. Swap NVDA for any Yahoo-style ticker.
PROMPT = (
    "Evaluate NVDA as a buy idea. Give me the live macro regime, the EMF "
    "durability score with the per-check breakdown, the 1-year price/trend "
    "context, and the rate backdrop — then a one-line REGIME×SCORE verdict cell "
    "and a short 'what would change the read' note that names the buy-case legs "
    "nexus-core can't see yet. Keep it concise."
)


async def main() -> None:
    """Connect the Agent SDK to the hosted nexus-core MCP server and ask once."""
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query
    except ImportError as exc:  # pragma: no cover - demo dependency, not a repo dep
        raise SystemExit(
            "This example needs the Claude Agent SDK and an API key:\n"
            "    pip install claude-agent-sdk\n"
            "    export ANTHROPIC_API_KEY=sk-ant-...\n"
        ) from exc

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        mcp_servers={SERVER_KEY: {"type": "http", "url": MCP_URL}},
        allowed_tools=ALLOWED_TOOLS,
        # Headless: auto-allow the pre-approved read-only tools, prompt for nothing,
        # deny anything not on the allowlist.
        permission_mode="dontAsk",
    )

    async for message in query(prompt=PROMPT, options=options):
        _print_message(message)


def _print_message(message: object) -> None:
    """Best-effort, SDK-version-tolerant rendering of a streamed message."""
    content = getattr(message, "content", None)
    if isinstance(content, list):
        for block in content:
            text = getattr(block, "text", None)
            if text:
                print(text)
            tool_name = getattr(block, "name", None)
            if tool_name:  # a tool-use block
                print(f"  -> calling {tool_name}")
    result = getattr(message, "result", None)
    if isinstance(result, str) and result:
        print(result)


if __name__ == "__main__":
    asyncio.run(main())
