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

# Planning agent (requires pip install claude-agent-sdk + ANTHROPIC_API_KEY;
# no nexus-core install needed — it calls the public hosted MCP server)
python examples/planning_agent.py
```

Contributions welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md).
