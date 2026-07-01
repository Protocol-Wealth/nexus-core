# NEXT-STEPS.md — nexus-core

A hand-off for new contributors (interns). Read this with
[`CLAUDE.md`](CLAUDE.md) (operating rules + invariants), [`README.md`](README.md)
(architecture), [`CURRENT-STATE.md`](CURRENT-STATE.md) (as-built inventory), and
[`ROADMAP.md`](ROADMAP.md) (what's live vs next). This file is the **prioritized
to-do list**; keep it current as you finish items.

_Last updated: 2026-07-01. Live deployment: [nexusmcp.site](https://nexusmcp.site)
health verified `{"status":"ok","service":"nexus-core","version":"0.1.0"}`._

## Orient yourself in 5 minutes

- **What this is:** the open, read-only public surface of the Protocol Wealth
  research engine — a REST API + an MCP server, no account/API key and no client
  data. Remote MCP clients may use transparent OAuth with no user login.
  Deployed to Cloud Run at `nexusmcp.site`.
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

### Public-safe planning/report analytics extraction (#197)

The active next track is GitHub issue #197: decide which generic, PII-free
analytics from private PWOS producer work belong in nexus-core as educational
substrate. Candidate work includes allocation decomposition, diversification
readiness, index-proxy replay/backtest boundaries, model-portfolio context,
education-reference context, source-quality signals, and report-input coverage.
Keep report production, artifact receipts, client context, suitability, and
private workflow state out unless deliberately generalized.

### Planning assumptions provenance (#198)

Add source and last-verified metadata to reference planning assumptions and echo
it in planning outputs.

### Crypto-options follow-ups (#200)

The covered-call **overwriting + hedge suite** is live (see ROADMAP § Options).
Remaining small PRs: put-side skew / risk-reversal, coin-denominated collar
laddering, IV-rank / percentile context, and config surface for
`regime_overlay` delta multipliers.

### Platform (#199; see ROADMAP § Next for detail)

Aerodrome Slipstream full coverage via Envio, Base subgraph data-quality,
subgraph health-gate, Uniswap V4, Solana CLMM, persisted LP PnL history.

### Additional tracked backlog

- #201 agent analytics capabilities: equity options IV, `score_portfolio`,
  DeFi yield/risk, symbol resolver, score provenance/versioning.
- #202 governance/tooling cleanup: EMF numbering, display-only signal decision,
  and possible `ruff format` gate.
- #203 equity-research vertical gates and public-safe buildout.

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
