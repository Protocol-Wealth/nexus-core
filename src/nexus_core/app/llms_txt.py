# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""``/llms.txt`` for the nexus-core public deployment.

Follows the llmstxt.org convention: an H1 name, a blockquote summary, short
prose, then markdown link sections. Aimed at an LLM/agent deciding how to USE
the hosted server. Served at the web root as ``text/markdown`` (mirrors how
``landing.py`` / ``mcp_guide.py`` render self-contained content).
"""

from __future__ import annotations

from .. import __version__
from ..disclaimers import FULL as _FULL_DISCLAIMER

_BODY = """\
# Nexus Core

> Open, regime-adaptive financial-analysis engine exposed as Model Context
> Protocol (MCP) tools and a read-only REST API. Public — no account, no API
> key, no authentication. Educational and informational use only — not advice.
> Operated by Protocol Wealth, LLC (SEC-registered RIA, CRD #335298). Apache-2.0.

Nexus Core gives an AI client regime-aware market, macro, options, DeFi, and
PII-free retirement-planning analysis. Every response is read-only and carries
an educational, not-advice disclaimer. It holds no client data and no PII.

Two ways to call it:
- **MCP (recommended for AI clients):** connect to `https://nexusmcp.site/mcp`
  (Streamable HTTP, transparent OAuth — no login). The tool list from
  `tools/list` after connecting is always authoritative. Call `describe` for the
  catalog + symbology and `health` for per-upstream status.
- **REST:** base `https://nexusmcp.site` (e.g. `GET /api/regime`). Interactive
  docs at `/docs`; machine-readable schema at `/openapi.json`.

**Symbology (important — the same asset differs per tool):** equities/ETFs/
indices use Yahoo tickers (`AAPL`, `SPY`, `^GSPC`); crypto *quotes* use a
CoinGecko coin id (`bitcoin`, not `BTC-USD`); crypto *scoring* uses a Yahoo-style
pair (`BTC-USD`); crypto *options* use a Deribit code (`BTC`, `ETH`, `SOL`).

## Setup
- [MCP setup guide](https://nexusmcp.site/mcp-guide): connect Claude.ai, Claude
  Desktop (via `mcp-remote`), Cursor, or any MCP client — hosted or local.
- MCP endpoint: `https://nexusmcp.site/mcp` (Streamable HTTP, public).
- Local stdio server: `pip install "nexus-core[mcp]"` then `nexus-core mcp`.

## Docs
- [Interactive REST docs](https://nexusmcp.site/docs)
- [OpenAPI schema](https://nexusmcp.site/openapi.json)
- [Source + README (GitHub)](https://github.com/Protocol-Wealth/nexus-core)

## Tools
- **Regime** (`current_regime`, `regime_signals`) — macro regime classification + raw signals.
- **Scoring** (`score_asset`) — 8-check EMF durability score on SEC EDGAR fundamentals; a confidence tier, not a buy/sell call. Use `BTC-USD` for crypto.
- **Market** (`get_quote`, `get_quotes`, `get_price_history`) — quotes + OHLCV. Use `bitcoin` (coin id) here, not `BTC-USD`.
- **Economic** (`get_economic_series`) — FRED series (e.g. `DGS10`, `DFII10`).
- **Options** (`option_price`, `covered_call`, `cash_secured_put`, `collar`) — Black-Scholes price/Greeks + overlay illustrations. Educational, not recommendations.
- **Crypto options** (`crypto_option_instruments`, `crypto_option_ticker`) — Deribit BTC/ETH/SOL/XRP/TRX/AVAX.
- **DeFi** (`defi_protocols`, `defi_protocol`, `defi_chains`) — DefiLlama TVL.
- **Planning** (`monte_carlo_decumulation`, `glide_path`, `tax_aware_withdrawal`, `correlation_matrix`, `capital_market_assumptions`, `regime_return_generator`, `roth_conversion`, `sequence_of_returns_stress`) — PII-free retirement math. De-identified inputs only (age, never date of birth).
- **Meta** (`health`, `describe`) — upstream status + the tool catalog/symbology.

## Planning over REST (pwplan-core contract v0.1.0)
- Handshake: `GET https://nexusmcp.site/mcp/tools` → `{ "contractVersion": "0.1.0", "tools": [...] }`. Confirm `contractVersion` before sending work.
- Invoke: `POST https://nexusmcp.site/mcp/tools/{tool_id}` with a JSON body. Every success echoes `contractVersion`. Errors are plain text (400 invalid, 404 unknown tool, 422 infeasible).
- PII-free by construction: send `age`, never date of birth; no name/email/SSN/address (rejected 400).

## Usage rules for agents
- Read-only, side-effect-free. Rate limit 60 requests/min per IP (`/health` and `/mcp` exempt).
- Do NOT present outputs as recommendations, advice, or guarantees. Preserve the `disclaimer` field on every response.

## Disclaimer
{disclaimer}

## Security
- Policy: https://nexusmcp.site/.well-known/security.txt — report to security@protocolwealthllc.com

---
Nexus Core v{version} · Apache-2.0 · https://github.com/Protocol-Wealth/nexus-core
"""


def render_llms_txt() -> str:
    """Return the ``/llms.txt`` markdown body.

    Uses ``str.replace`` rather than ``str.format`` because the body contains
    literal braces (JSON examples, ``{tool_id}``) that would collide with
    format placeholders.
    """
    return _BODY.replace("{version}", __version__).replace("{disclaimer}", _FULL_DISCLAIMER)


__all__ = ["render_llms_txt"]
