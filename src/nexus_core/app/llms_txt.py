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
> Protocol (MCP) tools and a read-only REST API. Native MCP can run as a public
> demo endpoint; REST/JSON calculation surfaces may require a service API key.
> Remote MCP clients may complete transparent OAuth with no login.
> Educational and informational use only — not advice.
> Operated by Protocol Wealth, LLC (SEC-registered RIA, CRD #335298). Apache-2.0.

Nexus Core gives an AI client regime-aware market, macro, options, DeFi, and
PII-free retirement-planning analysis. Every response is read-only and carries
an educational, not-advice disclaimer. It holds no client data and no PII.

Two ways to call it:
- **MCP (recommended for AI clients):** connect to `https://nexusmcp.site/mcp`
  (Streamable HTTP public demo surface, transparent OAuth — no login). The tool list from
  `tools/list` after connecting is always authoritative. Call `describe` for the
  catalog + symbology and `health` for per-upstream status.
- **REST:** base `https://nexusmcp.site` (e.g. `GET /api/regime`). Interactive
  docs at `/docs`; machine-readable schema at `/openapi.json`. Production
  callers should authenticate through the service-key REST/JSON path.

**Symbology (important — the same asset differs per tool):** equities/ETFs/
indices use Yahoo tickers (`AAPL`, `SPY`, `^GSPC`); crypto *quotes* use a
CoinGecko coin id (`bitcoin`, not `BTC-USD`); crypto *scoring* uses a Yahoo-style
pair (`BTC-USD`); crypto *options* use a Deribit code (`BTC`, `ETH`, `SOL`).

## Setup
- [MCP setup guide](https://nexusmcp.site/mcp-guide): connect Claude.ai, Claude
  Desktop (via `mcp-remote`), Cursor, or any MCP client — hosted or local.
- MCP endpoint: `https://nexusmcp.site/mcp` (Streamable HTTP public demo surface; transparent OAuth where the client requires it).
- Local stdio server: `pip install "nexus-core[mcp] @ git+https://github.com/Protocol-Wealth/nexus-core.git"` then `nexus-core mcp`.

## Docs
- [Interactive REST docs](https://nexusmcp.site/docs)
- [OpenAPI schema](https://nexusmcp.site/openapi.json)
- [Source + README (GitHub)](https://github.com/Protocol-Wealth/nexus-core)

## Tools
- **Regime** (`current_regime`, `regime_signals`) — macro regime classification + raw signals.
- **Scoring** (`score_asset`, `classify_layer`) — 8-check EMF durability score on SEC EDGAR fundamentals; a confidence tier, not a buy/sell call. Use `BTC-USD` for crypto. `classify_layer` returns an asset's EMF durability layer (L1 Foundation .. L7 Catalyst) with its display name, durability horizon, λ decay ceiling, per-regime target weights, and the rule that decided the classification (ticker map / asset-class route / sector keyword / sector default) — pure compute over the published layer maps, no upstream call.
- **Market** (`get_quote`, `get_quotes`, `get_price_history`) — quotes + OHLCV. Use `bitcoin` (coin id) here, not `BTC-USD`.
- **Economic** (`get_economic_series`) — FRED series (e.g. `DGS10`, `DFII10`).
- **Options** (`option_price`, `covered_call`, `cash_secured_put`, `collar`, `equity_collar_screen`, `collar_book`, `equity_option_expirations`, `equity_option_chain`) — Black-Scholes price/Greeks + overlay illustrations, a batch (≤25 tickers) dividend-aware theoretical collar screen, a multi-name collar-book assembly worksheet (≤50 pre-screened candidates; whole-contract sizing with position/sector caps plus optional executable-fill haircut from bid-side call / ask-side put pricing — advisor research worksheet, no orders), and MBOUM-backed listed equity option expirations + single-expiration chains (bid/ask, OI, IV, delta). Educational, not recommendations.
- **Crypto options** (`crypto_option_instruments`, `crypto_option_ticker`) — Deribit BTC/ETH/SOL/XRP/TRX/AVAX.
- **DeFi** (`defi_protocols`, `defi_protocol`, `defi_chains`) — DefiLlama TVL.
- **Planning** (`monte_carlo_decumulation`, `solve_goal`, `analyze_goals`, `project_cash_flow`, `cashflow_planning_bridge`, `cash_reserve_analysis`, `budget_pacing_projection`, `education_funding`, `education_vehicle_rules`, `income_layering`, `glide_path`, `tax_aware_withdrawal`, `correlation_matrix`, `capital_market_assumptions`, `historical_blend`, `regime_return_generator`, `roth_conversion`, `sequence_of_returns_stress`, `rmd`, `tax_bracket_headroom`, `inherited_ira_analysis`, `social_security_claiming`, `regime_conditioned_swr`, `portfolio_xray`, `optimize_allocation`, `risk_profile_score`, `fire`, `risk_metrics`, `performance_analysis`, `rebalance`, `irmaa_headroom`, `analyze_roth_conversion`, `sequence_conversions`, `build_planning_report`) — 34 PII-free retirement/planning math tools. De-identified inputs only (age and optional birth year where the tax policy requires it, never date of birth); `project_cash_flow` can optionally model taxable/traditional/Roth planning buckets and an `ltcShock` healthcare-cost stress, `income_layering` stacks earned income, Social Security, pensions/annuities, RMDs, tax-aware withdrawals, optional state-tax layers, and optional spouse/survivor modeling, `inherited_ira_analysis` compares 10-year inherited IRA beneficiary distribution strategies from numeric assumptions only and is not a separate annual RMD compliance calculator, `risk_profile_score` maps fixed questionnaire answers to the optimizer-compatible `riskProfile` enum, `performance_analysis` computes TWR, MWR/XIRR, fee drag, and benchmark-relative return deltas from numeric series only, `historical_blend` builds hypothetical index-blend history from public asset-class proxy returns, Monte Carlo tools can path-fund opaque goals by priority and emit a same-seed with/without-LTC-shock impact block (`ltcShock` is not combined with `guardrails` in S12 v1), `build_planning_report` supports the default custom assembler plus `preset: "wealth_roadmap"` for the PW Wealth Roadmap structured report, and bridge tools consume derived monthly-close aggregates, not raw transactions.
- **Meta** (`health`, `describe`) — upstream status + the tool catalog/symbology.

## Planning over REST (pwplan-core contract v0.1.0)
- Handshake: `GET https://nexusmcp.site/api/planning/tools` → `{ "contractVersion": "0.1.0", "tools": [...] }`. Confirm `contractVersion` before sending work.
- Invoke: `POST https://nexusmcp.site/api/planning/tools/{tool_id}` with a JSON body. Every success echoes `contractVersion`. Errors are plain text (400 invalid, 404 unknown tool, 422 infeasible). Legacy `/mcp/tools` aliases remain for older clients.
- PII-free by construction: send `age`, never date of birth; no name/email/SSN/address (rejected 400).

## Usage rules for agents
- Read-only, side-effect-free. Rate limit 60 requests/min per IP (`/health` and `/mcp` exempt).
- Do NOT present outputs as recommendations, advice, or guarantees. Preserve the `disclaimer` field on every response.

## Disclaimer
{disclaimer}

## Security
- Policy: https://nexusmcp.site/.well-known/security.txt — report to security@protocolwealthllc.com

## Disclosure
- AI & Technology Disclosure (canonical, human-readable): https://protocolwealthllc.com/disclosures/
- Machine-readable AI disclosure card: https://nexusmcp.site/.well-known/ai-disclosure.json — mirrors the disclosure above (pwos-core disclosure-card schema: model, data handling, oversight, PII, audit posture).

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
