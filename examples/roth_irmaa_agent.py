# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Roth-conversion + IRMAA agent — Claude Agent SDK over the hosted nexus-core MCP.

The driving case for the composite planner: a ~60-something couple wants to convert
part of a Traditional IRA to Roth over two years, and the binding constraint is
**IRMAA (Medicare premium surcharges), not the tax bracket**. This agent lets Claude
size the conversion with the live ``analyze_roth_conversion`` tool — under both the
bracket and the *projected* IRMAA ceilings — and read the per-year recommendation,
the IRMAA cliff cost, the all-in tax, the do-nothing RMD drag, and (when an ACA
situation is supplied) the premium-tax-credit cliff.

It talks to the PUBLIC hosted server at ``nexusmcp.site/mcp`` (no account, no key,
read-only), so you do NOT need to install or run nexus-core to try it.

Run::

    pip install claude-agent-sdk      # not a nexus-core dependency; this demo only
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/roth_irmaa_agent.py

PII-free by construction: the engine plans on birth *years* + aggregated balances,
never identity. Educational only — not investment, tax, legal, or financial advice;
the IRMAA tiers are *projected* with a buffer (a documented fiduciary assumption),
and the figures are illustrative engine-reference tables, not a filing.
"""

from __future__ import annotations

import asyncio

#: The public, read-only hosted MCP endpoint (MCP over HTTP / Streamable HTTP).
MCP_URL = "https://nexusmcp.site/mcp/"

#: Key for the server in the SDK's mcp_servers map; tool names derive from it as
#: ``mcp__<key>__<tool_id>``.
SERVER_KEY = "nexus"

#: Least-privilege allowlist: only the composite Roth/IRMAA planning tools.
_PLANNING_TOOLS = (
    "analyze_roth_conversion",
    "sequence_conversions",
    "irmaa_headroom",
)
ALLOWED_TOOLS = [f"mcp__{SERVER_KEY}__{name}" for name in _PLANNING_TOOLS]

SYSTEM_PROMPT = (
    "You are a Roth-conversion + IRMAA planning assistant backed by the nexus-core "
    "engine, exposed as MCP tools. Work the problem with the tools rather than "
    "guessing numbers:\n"
    "  1. Call analyze_roth_conversion with the de-identified case to size the "
    "conversion for each year under BOTH the bracket ceiling and the projected "
    "IRMAA ceiling (it takes the smaller, gates by outside liquidity, and applies "
    "pro-rata when there is after-tax basis).\n"
    "  2. Read out, per year: the recommended amount, which ceiling binds, the IRMAA "
    "cliff cost if crossed, the all-in incremental tax, and the breakeven rate.\n"
    "  3. Surface the do-nothing RMD drag (why the gap-year window exists) and any "
    "ACA premium-tax-credit note.\n"
    "The tool takes the request as a single JSON object in a `body` argument: a "
    "PII-free PlanningContract under `body.contract` (case_id, tax_year, "
    "filing_status single|mfj|mfs, state_code, birth_years (YEARS not DOBs), "
    "income_ex_conversion, accounts, intent {target_rule, years}), plus optional "
    "`body.aca` to quantify the ACA cliff. Plan on age, never date of birth; never "
    "invent or request identity fields. Always note the IRMAA tiers are *projected* "
    "with a buffer and that these are illustrative results, not advice."
)

# A de-identified planning question — birth years, aggregated balances, intent only.
PROMPT = (
    "A married-filing-jointly couple, born 1962 and 1963, live in PA and are both on "
    "Medicare. For 2026 (before any conversion) they expect ~$30k pension, ~$48k gross "
    "Social Security, ~$5k taxable interest, ~$8k tax-exempt interest, ~$12k ordinary "
    "dividends (of which ~$9k qualified), and ~$10k long-term gains. They hold ~$1.4M "
    "across Traditional IRAs (no after-tax basis), ~$200k in Roth, and ~$250k of taxable "
    "cash to pay conversion tax. They want to convert over 2026 and 2027, filling up to "
    "just under the next IRMAA tier. How much should they convert each year, what binds, "
    "and what would crossing the IRMAA tier cost? Keep it concise."
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
