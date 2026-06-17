# Examples

Runnable examples for Nexus Core capabilities.

## Available

- **`basic_regime.py`** — Regime classification with stub data providers.
  Shows the `RegimeCode` + `RegimeThresholds` + `RegimeEngine` flow.
- **`basic_scoring.py`** — N-check scoring with custom checks, all three
  enhancements (consistency, base rate, adversarial brief), and formatters.
- **`mcp_server.py`** — Run nexus-core as a FastMCP server exposing regime
  and scoring tools. Install `nexus-core[mcp]` first.
- **`planning_agent.py`** — A PII-free Claude Agent SDK agent that drives the
  *hosted* nexus-core MCP server (`nexusmcp.site/mcp`) to answer a retirement
  question end to end: current regime → real capital-market assumptions → Monte
  Carlo decumulation → tax-aware withdrawal. No nexus-core install needed (it
  hits the public server); needs `pip install claude-agent-sdk` and an
  `ANTHROPIC_API_KEY`.
- **`crypto_options_agent.py`** — A Claude Agent SDK agent over the same hosted
  MCP server driving the settlement-aware crypto covered-call **overwriting**
  suite: live regime → regime-tilted strike (`crypto_regime_overwrite`) → IV term
  structure → coin-yield illustration, plus protective put / collar and a
  spot-shock stress. Public, illustrative inputs only (a coin, a strike, a tenor)
  — no positions/custody. Same install as the planning agent.
- **`roth_irmaa_agent.py`** — A Claude Agent SDK agent over the same hosted MCP
  server driving the **composite Roth-conversion + IRMAA** tool
  (`analyze_roth_conversion`): for a ~60-something MFJ couple it sizes the
  conversion across 2026+2027 under both the bracket and the *projected* IRMAA
  ceilings, reads the binding ceiling, the IRMAA cliff cost, the all-in tax, and
  the do-nothing RMD drag. PII-free (birth years + aggregated balances, never
  identity). Same install as the planning agent.
- **`stock_research_agent.py`** — A Claude Agent SDK agent over the same hosted
  MCP server that evaluates **one equity idea** through the regime + EMF
  durability lens: live regime (`current_regime`/`regime_signals`) → 8-check
  `score_asset` → price/trend (`get_quote`/`get_price_history`) → rate backdrop
  (`get_economic_series`) → a graded **REGIME×SCORE** dossier. Deliberately
  honest about today's shape — valuation, analyst consensus, forward estimates,
  real equity IV/skew, and news/sentiment are rendered as explicit *gap* lines,
  never fabricated (those tools are planned; see
  [`docs/STOCK-RESEARCH-ENHANCEMENT.md`](../docs/STOCK-RESEARCH-ENHANCEMENT.md)).
  Output is a confidence-tiered assessment, **not** a buy/sell call. Same install
  as the planning agent.

## Planned

- `portfolio_optimization.py` — PyPortfolioOpt wrapper in action
- `sec_research.py` — edgartools wrapper in action
- `retirement_projection.py` — Monte Carlo retirement simulation
- `tax_loss_harvest.py` — Wash-sale-aware TLH

## Running

```bash
# From repo root, after pip install -e .
python examples/basic_regime.py
python examples/basic_scoring.py

# MCP server (requires pip install -e ".[mcp]")
python examples/mcp_server.py

# Agents over the hosted MCP server (requires pip install claude-agent-sdk +
# ANTHROPIC_API_KEY; no nexus-core install needed — they call the public server)
python examples/planning_agent.py
python examples/crypto_options_agent.py
python examples/stock_research_agent.py
```

Contributions welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md).
