# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Reference planning agent — Claude Agent SDK over the hosted nexus-core MCP server.

A minimal, PII-free agent that lets Claude orchestrate nexus-core's regime and
planning tools to answer a retirement question end to end: read the current
macro regime, pull *real* capital-market assumptions, run a Monte Carlo
decumulation on those assumptions, and sketch a tax-aware withdrawal — the same
"real data, fake clients" flow the pwplan-core UI drives, but conversational.

It talks to the PUBLIC hosted server at ``nexusmcp.site/mcp`` (no account, no
key, read-only), so you do NOT need to install or run nexus-core to try it.

Run::

    pip install claude-agent-sdk      # not a nexus-core dependency; this demo only
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/planning_agent.py

Educational only — nothing here is investment, tax, legal, or financial advice.
Inputs are de-identified by construction: the engine plans on age, never date of
birth, and this agent never sends names or other identity fields.
"""

from __future__ import annotations

import asyncio

#: The public, read-only hosted MCP endpoint (MCP over HTTP / Streamable HTTP).
MCP_URL = "https://nexusmcp.site/mcp/"

#: Key for the server in the SDK's mcp_servers map; tool names derive from it as
#: ``mcp__<key>__<tool_id>``.
SERVER_KEY = "nexus"

#: Least-privilege allowlist: only the read-only regime + planning tools this
#: agent needs. Everything else (market, options, on-chain) stays off.
_PLANNING_TOOLS = (
    "current_regime",
    "regime_signals",
    "capital_market_assumptions",
    "correlation_matrix",
    "regime_return_generator",
    "monte_carlo_decumulation",
    "glide_path",
    "tax_aware_withdrawal",
)
ALLOWED_TOOLS = [f"mcp__{SERVER_KEY}__{name}" for name in _PLANNING_TOOLS]

SYSTEM_PROMPT = (
    "You are a regime-aware retirement-planning assistant backed by the "
    "nexus-core engine, exposed as MCP tools. Work the problem with the tools "
    "rather than guessing numbers:\n"
    "  1. Read the current macro regime (current_regime) and note what it "
    "implies for sequence-of-returns risk.\n"
    "  2. Pull real capital-market assumptions (capital_market_assumptions) for "
    "the relevant asset classes.\n"
    "  3. Run monte_carlo_decumulation with those assumptions, returnModel "
    "'emf_regime', and the user's de-identified portfolio.\n"
    "  4. If asked about withdrawals, use tax_aware_withdrawal.\n"
    "The planning tools take the request as a single JSON object in a `body` "
    "argument matching the pwplan-core wire contract (contractVersion 0.1.0). "
    "Plan on age, never date of birth; never invent or request identity fields. "
    "Report the success probability and the regime context plainly, and always "
    "note these are illustrative model results, not advice or a guarantee."
)

# A de-identified planning question — age, balances, allocations only.
PROMPT = (
    "A household, currently age 62, plans to retire at 65 with a 30-year "
    "horizon to age 95. They hold $1.2M in a traditional account (60% US "
    "equity / 40% US bonds) and $300k in a Roth (80/20). They want to spend "
    "$120k/year with a 2.5% COLA, and expect Social Security of $42k/year "
    "starting at 67; filing status married-joint. Using the current regime and "
    "real capital-market assumptions, what's their probability of success, and "
    "how sensitive is it to the regime? Keep it concise."
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
    """Best-effort, SDK-version-tolerant rendering of a streamed message.

    Duck-typed on purpose: prints assistant text + tool-call visibility + the
    final result without importing concrete message/block classes (which churn
    across SDK versions).
    """
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
