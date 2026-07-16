# Archived contributor next-steps — nexus-core

> **Historical reference, not a prioritized backlog.** This file preserves the
> detailed 2026-07-07 contributor handoff. Current work is owned by
> [ROADMAP.md](ROADMAP.md) and GitHub Issues; deployed truth is in
> [CURRENT-STATE.md](CURRENT-STATE.md), and checks are recorded in
> [VALIDATION.md](VALIDATION.md). Read [`CLAUDE.md`](CLAUDE.md) for operating
> rules. Where the material below differs, those current sources win.

## Current pointer (2026-07-16 ET)

- `70bd5d5` is deployed on `nexus-core-00069-6m7` at 100% traffic.
- Onchain accounting contract `0.2.0` is live through restricted REST. Current
  source registers the same four calculation handlers in native MCP full mode;
  the hosted demo profile stays unchanged.
- Contract `0.2.0` implements #260's account/transfer/fee, calendar-term,
  period-replay, lineage, and completeness hardening. Statement wiring remains
  blocked pending `pw-api` compatibility and CIO/IC/CCO methodology review.
- The accounting engine is de-identified calculation substrate. Private
  custodian ingestion, wallet/client linkage, statement assembly, advisor review,
  tax-return preparation, release, and retention remain outside this repo.

## Archived 2026-07-07 contributor material

### Orient yourself in 5 minutes

- **What this is:** the open, read-only public surface of the Protocol Wealth
  research engine — a REST API + an MCP server with no client data. Native MCP
  can stay as a low-risk public demo surface; production REST/JSON consumers can
  require `NEXUS_ACCESS_MODE=restricted` + `NEXUS_API_KEYS`. Remote MCP clients
  may use transparent OAuth with no user login. Deployed to Cloud Run at
  `nexusmcp.site`.
- **Three sibling repos:** `nexus-core` (this — the engine + public API/MCP),
  `pwplan-core` (a thin PII-free **planning** UI that calls this engine's planning
  tools), and `pw-demo` (the public **demo site** at pwdemo.com — browser + chat
  surface that calls this engine's REST/MCP directly). Crypto-options UI work
  happens in **pw-demo**, not here and not pwplan-core.
- **Layout:** pure math in `src/nexus_core/engine/`; data adapters in
  `src/nexus_core/data/`; the FastAPI app + routers in `src/nexus_core/app/`; the
  MCP server in `src/nexus_core/mcp/server/app.py`. Engine functions are pure and
  clock-free; routers/tools do the I/O.
- **Cash Flow OS boundary:** Nexus may calculate from de-identified planning
  inputs and derived monthly-close values, but must not ingest Monarch CSVs or
  store raw transactions, merchant/payee strings, account nicknames, household
  records, advisor/client notes, approvals, release state, or audit trails.
- **Current Slice 2 state:** `cashflow_planning_bridge`,
  `cash_reserve_analysis`, and `budget_pacing_projection` live in
  `engine/planning/cashflow_bridge.py`, are exported from
  `nexus_core.engine.planning`, and are exposed through the existing planning
  gateway/native MCP registry as read-only public-safe tools. They consume
  derived monthly-close aggregates only. They do not ingest Monarch CSVs, raw
  transaction rows, merchant/payee strings, account nicknames, household records,
  client/advisor notes, approvals, release state, or audit trails.
- **Current collar-book state:** `engine/pricing/collar_book.py` sizes
  pre-screened collar candidates and now reports current/assumed stock price,
  shares, optional executable net credit, bid/ask fill haircut, executable
  income, and executable annualized yield. REST and MCP parsers accept
  `executable_net_credit` or `call_bid`/`put_ask`; this remains an advisor
  research worksheet with no live-chain attestation, order routing, or advice.
- **Current access-boundary state:** `NEXUS_PUBLIC_MCP_PROFILE=demo` limits
  native `/mcp` to closed-world demo tools. `NEXUS_ACCESS_MODE=restricted` plus
  `NEXUS_API_KEYS` gates `/api/*`, primary `/api/planning/tools/*`, and legacy
  `/mcp/tools/*`; `pw-api` should send its matching `NEXUS_SERVICE_API_KEY`.
- **Current RMD policy state:** `rmd`, `tax_aware_withdrawal`, and the Roth
  composite share `tax.rmd_start_age`. Age-only callers still default to 73;
  callers with a de-identified `birthYear` get the SECURE/SECURE 2.0 table,
  including 1960+ at 75 and the documented 1959 good-faith age-73 policy.
- **Current tax-table state:** `tax.py`, `tax_bracket_headroom`,
  `roth_conversion`, `tax_aware_withdrawal`, `irmaa_headroom`, and the Roth
  composite share the reference-table provider in `engine/planning/tables.py`.
  Reference table years are explicit; missing years fail closed, and
  tax-sensitive outputs include table-version stamps for reproducible reports.
- **Current Monte Carlo report state:** `monte_carlo_decumulation` returns the
  existing headline fields plus Wilson confidence intervals, a sticky depletion
  curve, failed-path conditional shortfall, first-decade return deciles, and a
  run manifest with engine version, de-identified assumptions hash, and
  confidence-width report-quality flags. Guardrail runs also return cut/raise
  timing stats.
- **Current education-funding state:** `education_funding` and
  `education_vehicle_rules` live in `engine/planning/education.py` and
  `engine/planning/tables.py`, are exported from `nexus_core.engine.planning`,
  and are exposed through the planning gateway/native MCP registry. Inputs are
  annual costs, year offsets, funding years, current savings, contributions, and
  opaque `subjectRef` values only.
- **Current S8 waterfall state:** `project_cash_flow` stays single-bucket when
  callers omit account buckets. With `accountBalances`, it reports taxable /
  traditional / Roth balances, taxable-first withdrawals, and early-withdrawal
  penalties. `monte_carlo_decumulation` and `solve_goal` accept optional
  de-identified `goals`; the wrapper sorts them by priority, earlier projection
  year, input order, and funding-year index, then the engine funds them
  path-by-path after base spending and before growth, echoing
  `goalFundingSchedule` and per-goal funding statistics.
- **Current S5 risk-profile state:** `risk_profile_score` lives in
  `engine/planning/risk_profile.py`, is exported from
  `nexus_core.engine.planning`, and is exposed through the planning
  gateway/native MCP registry. It scores fixed question ids and answer ids into
  the optimizer-compatible `riskProfile` enum, annual volatility band, suggested
  model weights, and canonical planning disclaimer. Advisor overrides,
  suitability approvals, and audit records stay private.
- **Current S4 performance-analysis state:** `performance_analysis` lives in
  `engine/planning/performance.py`, is exported from
  `nexus_core.engine.planning`, and is exposed through the planning
  gateway/native MCP registry. It computes time-weighted return,
  money-weighted return / XIRR, fee drag, and benchmark-relative return deltas
  from de-identified numeric series only. Symbols, holdings names, account
  identifiers, raw transaction rows, tax lots, notes, approvals, and audit
  records stay outside this public repo.
- **Current S11 inherited IRA state:** `inherited_ira_analysis` lives in
  `engine/planning/inherited_ira.py`, is exported from
  `nexus_core.engine.planning`, and is exposed through the planning
  gateway/native MCP registry. It compares lump-sum, equal-annual, and
  bracket-smoothed inherited traditional IRA distribution strategies under a
  10-year frame, ranks strategies by net after-tax receipts, and includes EDB
  carve-out notes. Its result states that v1 is a strategy comparison, not a
  separate beneficiary life-expectancy annual RMD compliance calculator. Inputs
  are numeric and de-identified only; spousal rollover elections,
  trust/estate-specific rules, state tax, client delivery, and audit workflows
  remain private / future scope.
- **Current S12 healthcare / LTC stress state:** `project_cash_flow` and
  `monte_carlo_decumulation` accept optional `ltcShock` plus
  `healthcareInflationRate`. The event uses onset age, current-dollar annual
  cost, duration, and healthcare-cost inflation only. Cash-flow rows expose
  `baseExpenses` and `ltcShockExpense`; Monte Carlo emits a same-seed
  with/without-shock success-probability delta, self-insured probability, and
  terminal-value comparison. S12 v1 rejects `ltcShock` + Guyton-Klinger
  guardrails together; run those as separate scenarios. Diagnosis, claims,
  provider names, policy data, delivery, approval, and audit workflows remain
  private / future scope.
- **Current S2 income-layering state:** `income_layering` composes earned income,
  Social Security, pension/annuity streams, forced RMDs, tax-aware withdrawals,
  and optional bracket-fill analysis into a stacked per-year income timeline.
  Inputs are numeric assumptions and account-type buckets only; private labels,
  account identifiers, raw transactions, approvals, and release/audit state stay
  outside the public repo.
- **Current S3 historical-blend state:** `historical_blend` converts public
  asset-class proxy histories into aligned monthly return exhibits: calendar-year
  returns, trailing windows, growth-of-dollar, and annualized mean/sigma bands.
  The wrapper does provider I/O; the engine remains pure and receives only
  de-identified return series and weights.
- **Current S7 state/local tax state:** `state_tax.py` provides a data-driven
  2026 reference table for no-income-tax states, full retirement exclusion
  states, and selected partial/senior exclusion states. `tax_aware_withdrawal`
  and `income_layering` accept optional 2-letter state/residency inputs and
  return federal/state tax splits when modeled. The Roth composite's simpler
  conversion-rule reference set is aligned for no-income and full-retirement
  exclusion states it can represent. Unknown states stay explicitly unmodeled;
  raw addresses, account identifiers, household records, approvals, and audit
  state remain private-stack concerns.
- **Current S9 household/survivor state:** `social_security.py` exports a
  simplified household Social Security snapshot helper with age-reduced spousal
  benefits. `income_layering` accepts optional spouse Social Security and
  first-survivor-year filing-status inputs so two-person cases can show survivor
  benefit continuity and the joint-to-single tax transition. The public engine
  still uses only PIAs, claim ages, filing statuses, ages, and numeric
  assumptions; private household links, user permissions, approvals, and audit
  records stay outside this repo.
- **Current S6 Wealth Roadmap state:** `build_planning_report` supports
  `preset: "wealth_roadmap"` with `focused` and `full` scopes, required scope /
  disclosure injection, required per-section replay metadata, and full-scope
  candidate priority actions. The public engine rejects `released` and
  caller-provided `curated` workflow state; private rendering, approval,
  archive, and client-delivery workflows stay outside this repo.

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

**Full-suite diagnostic note (2026-07-05):** Slice 1/Slice 2 targeted tests
passed, but `timeout 180 .venv/bin/python -m pytest -vv --maxfail=1` collected
1143 tests and timed out at `tests/test_app.py::test_landing_page`. That appears
unrelated to the cash-flow bridge engine/gateway work; investigate separately
before treating the full suite as a Slice 1/Slice 2 failure.

Conventional commits, SPDX header on every `.py`, and **DCO sign-off**
(`git commit -s`). Branch off `main`; open a PR; merge when the single CI job
("ruff + mypy + pytest") is green. `gh pr edit --body` may fail on a Projects-classic
GraphQL error — use `gh api -X PATCH repos/Protocol-Wealth/nexus-core/pulls/<n>`
for the body instead.

## Deploy

Production deploys are **maintainer-run** (a human authorizes each one). The
command lives in [`DEPLOY.md`](DEPLOY.md); run `gcloud run deploy` **from the repo
root** (running it from a different dir uploads the wrong source). After a deploy,
smoke the changed endpoints live — note `/api/*` and planning JSON gateway paths
may be service-key gated in restricted mode and are rate-limited (~60/min/IP),
so pace the calls.

## Prioritized next tasks

### Planning engine correctness queue

The first correctness items have landed locally: Student-t covariance scaling,
single-kernel RMD start-age policy, shared tax/IRMAA table providers, reference
assumption provenance (#198), Monte Carlo report diagnostics, S1 education
funding, S8 multi-account waterfall /
Monte Carlo goal scheduling, S2 income layering, S3 historical blend, S7
state/local tax coverage, S9 household/survivor modeling, S6 Wealth Roadmap
report assembly, S5 risk-profile scoring, and S4 performance analysis. Continue
with the consolidated Wealth Roadmap sequence from the next unmerged slice; keep
each item one PR and preserve the public/private planning boundary.

### Public-safe planning/report analytics extraction (#197)

The active next track is GitHub issue #197: decide which generic, PII-free
analytics from private PWOS producer work belong in nexus-core as educational
substrate. Candidate work includes allocation decomposition, diversification
readiness, index-proxy replay/backtest boundaries, model-portfolio context,
education-reference context, source-quality signals, and report-input coverage.
The hybrid planning-bridge candidate belongs here too: pure functions over
derived monthly-close values for cash reserves, budget pacing, goal funding, and
retirement-income guardrail inputs. Keep raw transaction classification, Monarch
imports, report production, artifact receipts, client context, suitability,
approvals, release workflow, audit trail, and private workflow state out unless
deliberately generalized.

Slice 1 has landed the pure engine layer for the first three bridge functions.
If accepted, Slice 2 should add MCP/REST wrappers and tests without changing the
raw-data boundary. Future `pwplan-core` work should consume only synthetic or
de-identified outputs from those wrappers.

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

- #201 agent analytics capabilities: IV-rank / VRP / 25-delta skew on equity
  chains, full stock-screen-to-chain pipeline, `score_portfolio`, DeFi
  yield/risk, symbol resolver, score provenance/versioning.
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
