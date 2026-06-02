# NEXT-STEPS.md — nexus-core

A hand-off for new contributors (interns). Read this with
[`CLAUDE.md`](CLAUDE.md) (operating rules + invariants), [`README.md`](README.md)
(architecture), [`CURRENT-STATE.md`](CURRENT-STATE.md) (as-built inventory), and
[`ROADMAP.md`](ROADMAP.md) (what's live vs next). This file is the **prioritized
to-do list**; keep it current as you finish items.

_Last updated: 2026-06-02. Live deployment: revision `nexus-core-00045-mdl` at
[nexusmcp.site](https://nexusmcp.site)._

## Orient yourself in 5 minutes

- **What this is:** the open, read-only public surface of the Protocol Wealth
  research engine — a REST API + an MCP server, no auth, no client data. Deployed
  to Cloud Run at `nexusmcp.site`.
- **Three sibling repos:** `nexus-core` (this — the engine + public API/MCP),
  `pwplan-core` (a thin PII-free **planning** UI that calls this engine's planning
  tools), and `pw-demo` (the public **demo site** at pwdemo.com — browser + chat
  surface that calls this engine's REST/MCP directly). Crypto-options UI work
  happens in **pw-demo**, not here and not pwplan-core.
- **Layout:** pure math in `src/nexus_core/engine/`; data adapters in
  `src/nexus_core/data/`; the FastAPI app + routers in `src/nexus_core/app/`; the
  MCP server in `src/nexus_core/mcp/server/app.py`. Engine functions are pure and
  clock-free; routers/tools do the I/O.

## Before you commit (the gate — mirrors CI)

Run these from the repo root and keep them green. **Use the project venv**, not
whatever is on your PATH:

```bash
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/        # (gate is `ruff check`; format the files you touch)
.venv/bin/mypy --strict src/nexus_core/          # MUST be the venv mypy (2.1.0)
.venv/bin/python -m pytest -q --cov=src/nexus_core --cov-fail-under=80
```

**Gotcha (will waste your afternoon):** a bare `mypy` on PATH may be an OLD
version (e.g. 1.14.1) that reports phantom errors disagreeing with CI. Always run
`.venv/bin/mypy`. Same for `pytest` (bare `python` can't import `nexus_core`).

Conventional commits, SPDX header on every `.py`, and **DCO sign-off**
(`git commit -s`). Branch off `main`; open a PR; merge when the single CI job
("ruff + mypy + pytest") is green. `gh pr edit --body` may fail on a Projects-classic
GraphQL error — use `gh api -X PATCH repos/Protocol-Wealth/nexus-core/pulls/<n>`
for the body instead.

## Deploy

Production deploys are **maintainer-run** (a human authorizes each one). The
command lives in [`DEPLOY.md`](DEPLOY.md); run `gcloud run deploy` **from the repo
root** (running it from a different dir uploads the wrong source). After a deploy,
smoke the changed endpoints live — note `/api/*` and `/mcp/tools/*` are
rate-limited (~60/min/IP), so pace the calls.

## Prioritized next tasks

### Crypto-options (the active track — deepen the shipped overwriting suite)

The covered-call **overwriting + hedge suite** is live (see ROADMAP § Options).
Engine: `engine/pricing/{crypto_overlays,option_chain,overwrite,options_book,regime_overlay,skew}.py`.
Good next pieces, each a small PR (engine fn → REST route in `app/options.py` →
MCP tool in `mcp/server/app.py` → hand-computed tests → docs):

1. **Put-side skew / risk-reversal.** `vol_skew` covers the call wing; add the put
   wing + the 25Δ risk-reversal (`IV(25Δ put) − IV(25Δ call)`) — the standard
   crypto skew signal. Mirror `engine/pricing/skew.py`.
2. **Coin-denominated collar laddering.** Extend `overwrite.covered_call_ladder`'s
   pattern to collars (put floor + financing call across tenors).
3. **IV-rank / percentile context** on `iv_term_structure` (where today's IV sits
   vs its own recent range) — needs a short history source or a snapshot.
4. **Config surface for the `regime_overlay` delta multipliers.** The
   `defensiveness` scalar is the per-request knob today; a server default
   (env-driven) would let the house view be set once.

### Platform (see ROADMAP § Next for detail)

Aerodrome Slipstream full coverage via Envio (#1), Arbitrum Uniswap V3 subgraph,
Base subgraph data-quality, subgraph health-gate, Uniswap V4, Solana CLMM,
persisted LP PnL history.

## In flight elsewhere (track, don't duplicate)

- **pw-demo** (`Protocol-Wealth/pw-demo`): the pwdemo.com browser surface + a
  streaming chat wired to this engine's MCP tools. Two open items handed to that
  repo's contributors: (a) a `cryptoOptions.ts` type fix (`Settlement` should be
  `"inverse" | "linear" | "linear_usdc"`; the per-tool endpoints return `"linear"`)
  + a `regimeColor()` fix (add the generic `inflationary`/`deflationary` cases);
  (b) the chat surface + new crypto panels (term structure, vol skew, defensiveness
  slider). The authoritative API contract for pw-demo is `nexusmcp.site/openapi.json`.

## Reference

- Worked agent patterns: `examples/planning_agent.py`,
  `examples/crypto_options_agent.py` (Claude Agent SDK over the hosted MCP).
- Connect guide + worked prompts: `GET nexusmcp.site/mcp` (rendered HTML).
- Cross-repo contract rules: [`CONTRIBUTING.md`](CONTRIBUTING.md).
