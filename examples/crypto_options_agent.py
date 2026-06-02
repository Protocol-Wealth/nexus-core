# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Reference crypto-options agent — Claude Agent SDK over the hosted nexus-core MCP.

A minimal agent that lets Claude run nexus-core's settlement-aware crypto
covered-call **overwriting** suite conversationally: read the live macro regime,
let the regime tilt the strike (``crypto_regime_overwrite``), check where vol is
richest across tenors (``crypto_iv_term_structure``), and illustrate the chosen
covered call's coin yield (``crypto_covered_call``) — plus the hedge side
(``crypto_protective_put`` / ``crypto_collar``).

It talks to the PUBLIC hosted server at ``nexusmcp.site/mcp`` (no account, no key,
read-only), so you do NOT need to install or run nexus-core to try it.

Run::

    pip install claude-agent-sdk      # not a nexus-core dependency; this demo only
    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/crypto_options_agent.py

Educational illustration only — nothing here is investment, tax, legal, or
financial advice. Inputs are PUBLIC, illustrative parameters (a coin, a strike, a
tenor) — no positions, balances, identity, custody, or counterparty context. The
actual program (ISDA/CSA booking, execution, custody) is out of scope.
"""

from __future__ import annotations

import asyncio

#: The public, read-only hosted MCP endpoint (MCP over HTTP / Streamable HTTP).
MCP_URL = "https://nexusmcp.site/mcp/"

#: Key for the server in the SDK's mcp_servers map; tool names derive from it as
#: ``mcp__<key>__<tool_id>``.
SERVER_KEY = "nexus"

#: Least-privilege allowlist: the live regime read + the crypto-options suite.
#: Everything else (equities, planning, on-chain) stays off.
_CRYPTO_OPTIONS_TOOLS = (
    "current_regime",
    "crypto_regime_overwrite",
    "crypto_iv_term_structure",
    "crypto_covered_call_chain",
    "crypto_covered_call",
    "crypto_protective_put",
    "crypto_collar",
    "crypto_options_scenario",
)
ALLOWED_TOOLS = [f"mcp__{SERVER_KEY}__{name}" for name in _CRYPTO_OPTIONS_TOOLS]

SYSTEM_PROMPT = (
    "You are a regime-aware crypto-options overwriting assistant backed by the "
    "nexus-core engine, exposed as MCP tools. Work the problem with the tools "
    "rather than guessing numbers:\n"
    "  1. Read the current macro regime (current_regime).\n"
    "  2. For a covered-call overwrite, call crypto_regime_overwrite — it pulls "
    "the live regime server-side and tilts the strike (defensive / further OTM "
    "in fragile regimes; closer for more premium in benign ones). The "
    "`defensiveness` arg scales that tilt (0 neutral, 1 default, >1 amplified).\n"
    "  3. Use crypto_iv_term_structure to see which expiry is richest to write, "
    "and crypto_covered_call_chain to rank strikes by annualized yield.\n"
    "  4. Report the coin-denominated yield for BTC/ETH (inverse settlement — the "
    "premium grows the coin stack) alongside the USD figures.\n"
    "  5. For downside, use crypto_protective_put / crypto_collar; to stress an "
    "open book, crypto_options_scenario.\n"
    "These tools take PLAIN scalar arguments (currency, strike, days, coins, …) — "
    "not a JSON body. Inputs are public, illustrative parameters only; never send "
    "positions, balances, identity, or counterparty data. Always state that "
    "results are illustrative model output, not advice, and that booking, "
    "execution, and custody are out of scope."
)

# A public, illustrative overwriting question — a coin, a tenor, a quantity.
PROMPT = (
    "I hold 5 BTC and want to write covered calls against it over roughly the "
    "next 45 days. Given the current macro regime, what strike should I write, "
    "and what coin yield does it earn? Show me which expiry is richest on the IV "
    "term structure, and how the position would fare if BTC moved ±30%. Keep it "
    "concise."
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
