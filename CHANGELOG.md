# Changelog

All notable changes to Nexus Core will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Healthcare / LTC stress S12

#### Added

- Added public-safe long-term-care stress inputs to deterministic cash-flow and
  Monte Carlo planning. `ltcShock` uses only de-identified numeric assumptions:
  onset age, current-dollar annual cost, duration, and healthcare-cost
  inflation.
- `project_cash_flow` now exposes LTC shock expense rows and total nominal shock
  cost when a shock is supplied. `monte_carlo_decumulation` now emits a
  same-seed with/without-shock impact block with success-probability delta,
  self-insured probability, and terminal-value comparison.

### Inherited IRA beneficiary decumulation S11

#### Added

- Added the public-safe `inherited_ira_analysis` planning tool. It compares
  lump-sum, equal-annual, and bracket-smoothed inherited traditional IRA
  distribution strategies under a 10-year frame, stacks taxable inherited
  distributions on beneficiary ordinary income using the injected federal
  ordinary-tax table, ranks strategies by net after-tax receipts, and returns an
  eligible-designated-beneficiary carve-out table.
- Added a JSON result schema, planning-tool registry wiring, MCP guide /
  `llms.txt` inventory updates, and focused unit/handler coverage. Inputs are
  numeric and de-identified only: no beneficiary names, account identifiers,
  raw transactions, notes, approvals, release state, or audit records.

### Performance analysis S4

#### Added

- Added the public-safe `performance_analysis` planning tool. It computes
  time-weighted return, money-weighted return / XIRR, fee drag, and
  benchmark-relative return deltas from de-identified numeric series only, with
  the canonical planning disclaimer. Symbols, holdings names, account
  identifiers, raw transaction rows, tax lots, notes, approvals, and audit
  workflows remain private-stack concerns.

### Risk-profile scoring S5

#### Added

- Added the public-safe `risk_profile_score` planning tool. It scores a fixed,
  PII-free questionnaire into the optimizer-compatible `riskProfile` enum,
  annual volatility band, suggested model weights, question/band metadata, and
  the canonical planning disclaimer. Advisor override, suitability approval, and
  audit workflows remain private-stack concerns.

### Wealth Roadmap report preset S6

#### Added

- Added the `wealth_roadmap` preset to `build_planning_report`. The preset
  emits the fixed "PW Wealth Roadmap" title, supports `focused` and `full`
  scopes, injects the required scope statement and focused-scope planning
  benefit notice, requires replay metadata, and stamps that metadata on every
  section.
- Added full-scope priority-action handling. Candidate actions remain
  `curated: false` until private-stack advisor curation. Public Roadmap requests
  reject `released` and caller-provided `curated` workflow state.

### Household and survivor modeling S9

#### Added

- Added `household_social_security_benefits`, a PII-free deterministic helper
  for simplified two-person Social Security own, age-reduced spousal,
  household, and survivor monthly benefit snapshots.
- Added optional `spouseSocialSecurity`, `survivorYear`, and
  `survivorFilingStatus` support to `income_layering`. The tool can now model
  a household Social Security stream before the first survivor-only modeling
  year, survivor benefit continuity after that year, and joint-to-single
  filing-status tax compression. The `IncomeLayeringResult` schema id is now
  `income-layering-result-0.1.2`.

### State/local tax layer S7

#### Added

- Added `engine/planning/state_tax.py`, a public-safe, data-driven 2026
  illustrative state-tax table covering no-income-tax states, PA/IL/MS/IA full
  retirement exclusions, and selected partial/senior exclusions for CO, NY, VA,
  NJ, MD, and DE.
- Added optional `state`, `residencyChange`, and `projectionYear` support to
  `tax_aware_withdrawal`, returning federal/state tax splits, state table
  versions, modeled/unmodeled flags, and explicit unknown-state notes.
- Added optional `state` and `residencyChange` support to `income_layering`,
  including per-year state code, federal/state tax totals, table versions, and
  state notes while preserving the existing federal-only response when omitted.
- Expanded the Roth composite's older `StateConversionRule` reference mapping
  for the S7 no-income and full-retirement-exclusion states that fit that rule
  shape.

#### Fixed

- Shared capped/tiered state retirement exclusions across pension, annuity, RMD,
  and discretionary traditional-withdrawal components in a year instead of
  applying the cap once per layer.

### Historical blend S3

#### Added

- Added the public-safe `historical_blend` planning tool for Wealth Roadmap
  historical-context exhibits: calendar-year returns, YTD / last-quarter
  non-annualized windows, trailing 1/3/5/7/10-year annualized windows,
  growth-of-dollar, and annualized mean / ±2σ / ±4σ bands.
- Added a dedicated hypothetical index-blend disclaimer covering reinvested
  income, excluded fees/taxes/costs, non-direct index investability, and past
  performance language.

### Income layering S2

#### Added

- Added the public-safe `income_layering` planning tool for deterministic
  per-year stacked income timelines: earned income, Social Security,
  pension/annuity streams, forced RMDs, tax-aware portfolio withdrawals, and
  optional federal bracket-fill layering.
- Added an `IncomeLayeringResult` JSON Schema and native-MCP/REST discovery
  entries so consumers can render the Income Lab timeline without creating a
  separate tax or RMD kernel.

### Multi-account waterfall S8

#### Added

- Added optional account-type buckets to `project_cash_flow`:
  `accountBalances` / `accountReturns` split the deterministic portfolio across
  taxable, traditional, and Roth balances while preserving the historical
  single-bucket response shape when omitted. Surplus saves to taxable; deficits
  draw taxable → traditional → Roth. Traditional withdrawals drive ordinary tax
  and the optional early-withdrawal penalty model before age 59.5; Roth draws
  are not treated as ordinary income in multi-account mode.
- Added optional `goals` to `monte_carlo_decumulation` and `solve_goal` as a
  deterministic gateway-level funding schedule. Goals are sorted by priority,
  earlier projection year, input order, and funding-year index, then funded
  path-by-path after base spending and before growth. Results include the
  generated schedule plus per-goal funding probabilities / funded-amount
  percentiles for replay.

### Education funding S1

#### Added

- Added the public-safe `education_funding` planning tool for multi-student
  cost inflation, projected education savings, and closed-form monthly / annual
  / lump-sum savings needs.
- Added the `education_vehicle_rules` planning tool with a 2026 reference
  comparison table for 529 plans, Coverdell ESAs, and UGMA/UTMA custodial
  accounts.

### Monte Carlo report diagnostics

#### Added

- Added report-grade diagnostics to `monte_carlo_decumulation`: a Wilson 95%
  confidence interval around `successProbability`, a sticky first-passage
  `depletionCurve`, failed-path `conditionalShortfall` percentiles, first-decade
  return deciles with per-decile success rates, and a deterministic
  `runManifest` carrying engine version, a de-identified assumptions hash, path
  count, horizon, seeds, return model, and whether the Wilson half-width meets
  the 1.5 percentage-point report tolerance.
- Added `guardrailStats` when Guyton-Klinger guardrails are enabled, summarizing
  cut/raise counts and first-cut timing without changing the existing
  `guardrailActivity` field.

### Tax table provider kernel

#### Fixed

- Centralized the illustrative federal tax-table and IRMAA reference lookup in a
  version-stamped provider registry so `tax.py`, `tax_bracket_headroom`,
  `roth_conversion`, `tax_aware_withdrawal`, `irmaa_headroom`, and the Roth
  composite do not drift across duplicate bracket/tier kernels.
- Made reference table lookup fail closed for unregistered tax/source years
  instead of silently reusing the current basis.
- Added tax/IRMAA table-version stamps to public tax-tool outputs and the Roth
  composite assumptions / compact sequence output without changing the closed
  Roth result schema.

### RMD start-age policy kernel

#### Fixed

- Centralized the SECURE/SECURE 2.0 RMD start-age policy in `tax.rmd_start_age`
  so `rmd`, `tax_aware_withdrawal`, and the Roth composite no longer carry
  divergent age-73/age-75 logic.
- Added optional `birthYear` support to the `rmd` and `tax_aware_withdrawal`
  planning tool wrappers while preserving the age-only default for existing
  callers.
- Stamped RMD-aware outputs with `rmdStartAgePolicyVersion`
  (`secure2.0-goodfaith-73-per-89FR58644`) and documented the 1959 cohort's
  good-faith age-73 treatment pending final regulations.

### Monte Carlo Student-t covariance scaling

#### Fixed

- Corrected the `student_t` return model in `monte_carlo_decumulation` so the
  multivariate Student-t draw is scaled to the caller-supplied covariance matrix
  instead of inflating variance by `dof / (dof - 2)`. With the current 5-degree
  model, archived Student-t runs before this fix overstated volatility by about
  29% versus the stated CMA covariance.
- Added regression coverage that the Student-t branch empirically matches the
  target covariance and pins the old unscaled shape-matrix formula as the known
  bad variance-inflation case.

### Docs/state closeout — private consumer boundary and PWOS market import

#### Changed

- Reconciled root docs to the current access model: hosted native `/mcp` remains
  a public OAuth-compatible demo surface, while hosted REST/JSON calculation
  paths are service-key gated for trusted server callers such as `pw-api`.
- Documented that PWOS/PWPortal browser apps should not hold Nexus service keys;
  they should call their own BFF/API routes, with `pw-api` supplying the
  server-to-server Nexus credential.
- Recorded the PWOS `/market-data` Seeking Alpha CSV/XLSX import as a private
  ingestion path after PR #993 and advisor verification of a 380-row import
  (`7c30414f`). Nexus consumes only de-identified candidate symbols and
  caller-supplied option-chain facts after private ingestion.
- Clarified the provider boundary: MBOUM backs equity option expirations/chains
  plus quote/history fallback coverage; MarketStack is a market quote/history
  fallback, not an options-chain provider.

#### Fixed

- Updated the source-rendered landing-page quickstart to show anonymous
  `/health` plus service-key REST/JSON examples instead of unauthenticated
  hosted `/api/*` calls.
- Corrected the SHA-256 digest fixture in the access-gate test and updated the
  landing-page quickstart test for the primary `/api/planning/tools/{tool_id}`
  route.

### REST/JSON access boundary and public MCP demo profile

#### Added

- Added optional `NEXUS_ACCESS_MODE=restricted` / `NEXUS_API_KEYS` middleware for
  `/api/*`, `/api/planning/tools/*`, and legacy `/mcp/tools/*`, accepting either
  `Authorization: Bearer <key>` or `X-Nexus-Api-Key`. Default mode remains
  `public` so existing deployments do not break until secrets are rolled.
- Added `NEXUS_PUBLIC_MCP_PROFILE=demo` for hosted native `/mcp` deployments that
  should expose only closed-world demo tools (`option_price`, `collar_book`,
  `health`, `describe`) and avoid live provider-backed tool usage.
- Added primary planning REST aliases at `GET /api/planning/tools` and
  `POST /api/planning/tools/{tool_id}`; existing `/mcp/tools` aliases remain for
  compatibility.
- Updated source-rendered landing, MCP guide, `/llms.txt`, and root docs to
  describe the intended split: open-source demo MCP for low-risk public use and
  authenticated REST/JSON for production service consumers such as `pw-api`.

#### Changed

- Documented the hosted production posture as transparent OAuth plus
  `NEXUS_PUBLIC_MCP_PROFILE=demo` for `/mcp`, while REST/JSON and legacy
  planning aliases remain API-key gated.

### Collar book executable-fill modeling

#### Added

- Added conservative executable-fill fields to the multi-name collar-book engine
  (`engine/pricing/collar_book.py`) and both caller surfaces. Each selected row
  now reports `stock_price`, `shares`, optional `executable_net_credit`,
  `fill_haircut`, executable income, and executable annualized yield when the
  caller supplies either `executable_net_credit` or the executable bid/ask pair
  (`call_bid` minus `put_ask`). The book summary reports portfolio-level
  executable annual income/yield and the annualized fill haircut only when every
  held name has executable pricing.
- Updated the REST `POST /api/options/overlay/collar-book` parser and the MCP
  `collar_book` parser to accept `executable_net_credit`, `call_bid`, and
  `put_ask` as per-share inputs. The output remains an advisor research
  worksheet: no orders, no execution instructions, no individualized advice.
- Added route, MCP-parser, and engine coverage for bid-side call / ask-side put
  executable pricing, explicit executable-credit precedence, share counts, and
  partial-book behavior when not every held line has executable pricing.

### Cash-flow planning bridge tools

#### Added

- Exposed the Slice 1 cash-flow planning bridge functions through the existing
  read-only planning REST gateway and native MCP registry as
  `cashflow_planning_bridge`, `cash_reserve_analysis`, and
  `budget_pacing_projection`. These wrappers preserve the standard planning
  `contractVersion` envelope, reject identity-shaped keys through the existing
  gateway tripwire, and consume derived monthly-close aggregates only.
- Updated planning gateway/MCP tests and source-rendered `/llms.txt` +
  `/mcp-guide` copy for the current 27-tool planning surface. Slice 2 adds no
  raw Monarch CSV ingestion, transaction classification, merchant/payee fields,
  household records, workflow state, approval/release state, persistence, or
  audit trail.
- Added Slice 1 pure planning bridge functions in
  `src/nexus_core/engine/planning/cashflow_bridge.py`:
  `cashflow_planning_bridge`, `cash_reserve_analysis`, and
  `budget_pacing_projection`. These functions consume de-identified monthly-close
  aggregates only and return deterministic planning assumptions, cash-reserve
  status, and budget-pacing output.

### Hybrid planning boundary docs

#### Changed

- Clarified the Slice 0 architecture boundary for the PW Cash Flow OS + PW
  Planning Lab + PW Retirement Income Lab direction: `nexus-core` remains the
  public-safe calculation plane, may add pure planning-bridge analytics over
  de-identified monthly-close values, and must not ingest Monarch CSVs, raw
  transactions, merchant/payee strings, household records, advisor/client
  workflow state, approvals, release state, or audit trails.

### Docs/status and dependency hygiene

#### Changed

- Reconciled root docs and source-rendered public copy (`README.md`, `CLAUDE.md`,
  `CURRENT-STATE.md`, `ROADMAP.md`, `AUDIT.md`, `DEPLOY.md`, `/llms.txt`, and
  `/mcp-guide`) with the live 2026-07-01 surface: 23 planning tools,
  transparent MCP OAuth, public PII-free planning math, no open PRs, and
  issue-linked outstanding work.
- Restored `pyproject.toml` to the documented `pandas>=2.2,<3.0` boundary so the
  `[backtest]`/`[all]` extras remain compatible with `alphalens-reloaded`.
- Removed the unused core `redis` runtime dependency and the stale
  `requirements-serve.lock` entry; the in-process rate limiter still documents
  Redis only as a future shared-store option.
- Cleaned current NOTICE / third-party license attribution so retired
  FinanceToolkit and Ethereum-ETL references remain only in historical
  changelog/planning context, not in active dependency notices.
- Refreshed secondary contributor/security/example/test docs so the local gate,
  canonical status docs, and vulnerability-reporting path match the current
  repo posture.
- Created GitHub tracking issues #198-#203 and linked outstanding/future-build
  roadmap lanes from the status docs. #197 remains the public-safe
  planning/report extraction tracker.

### Guyton-Klinger dynamic withdrawals (decumulation guardrails)

#### Added

- **`monte_carlo_decumulation` now accepts an optional `guardrails` config**
  selecting Guyton-Klinger dynamic withdrawals — a path-dependent withdrawal
  rule that replaces the static `net_spend_by_year` schedule from the first
  decumulation year onward. The three rules run vectorized across paths against
  each path's own initial withdrawal rate (captured when decumulation begins):
  the **withdrawal rule** raises the prior draw by `inflation` each year but
  freezes that raise after a down year when the rate is already elevated
  (`freezeAfterLoss`); the **capital-preservation rule** cuts the draw by `cut`
  (default 10%) when the rate rises more than `band` (default 20%) above the
  initial rate (suspended in the final `preservationFinalYears`, default 15);
  the **prosperity rule** raises the draw by `raise` (default 10%) when the rate
  falls more than `band` below the initial rate. New `GuardrailParams` dataclass
  in `engine/planning/monte_carlo.py`; gateway parsing + validation in
  `app/planning/tools.py` (the `guardrails` body field, `rule: "guyton_klinger"`).
- **New response fields when `guardrails` is supplied** — `withdrawalRule`,
  `spendingByYear` (p10/p50/p90 per-year realized-spend bands, so the dynamic
  cuts/raises are visible), and `guardrailActivity` (`pathsWithCut` /
  `pathsWithRaise` + the band/cut/raise echo). Omitting `guardrails` leaves the
  static-withdrawal mechanics unchanged and omits guardrail-only fields.
  `mypy --strict` + `ruff` clean; +13 tests (engine + gateway).

### Retired the FMP / FinanceToolkit path

#### Removed

- **`src/nexus_core/financials/` module + the `[financials]` extra +
  `financetoolkit` dependency.** FMP (Financial Modeling Prep, reached via the
  FinanceToolkit adapter) is no longer a supported data vendor. The module
  (statements/ratios/performance/risk/models + the `from_finance_toolkit`
  adapter) was unreachable — imported by nothing in the app / MCP / engine path —
  so removal is behavior-neutral. Its three dedicated tests
  (`test_financials_{models,ratios,performance_risk}.py`) were removed with it,
  and `financials` was dropped from the `[all]` extra. The supported research
  data sources are **MBOUM** (primary), **MarketStack** (EOD + corporate
  actions), and keyless **SEC EDGAR** (fundamentals / Form 4 / 13F), plus free /
  already-keyed feeds (FRED, etc.). Stale "FMP" mentions in `data/providers.py`,
  `engine/scoring/emf/{fscore,perez}.py` comments, `CLAUDE.md`, `ROADMAP.md`, and
  `docs/STOCK-RESEARCH-ENHANCEMENT.md` were updated to reflect the retirement.

### Docs — stock-idea analysis: capability review + enhancement scaffold (planning)

#### Added

- **`docs/STOCK-RESEARCH-ENHANCEMENT.md`** — a planning/scoping doc (ships no
  production tool) for evaluating an individual stock idea via Claude Code /
  Claude.ai over `nexusmcp.site/mcp`. Reviews what the MCP surface does today
  (regime + 8-check `score_asset` + price only), a prioritized **gap matrix**
  against the **already-held MBOUM / MarketStack / SEC EDGAR** data
  (the rich MBOUM research surface is called only for quotes/history), an
  **architecture** for an equity-research vertical (a sibling `ResearchDataProvider`
  protocol modeled on `MacroDataProvider`; read-only `analyst_consensus` /
  `earnings_estimates` / `fundamentals_statements` / `key_statistics` /
  `equity_option_chain` / `equity_iv_skew` / `screen_equities` / `insider_activity` /
  `institutional_holders` / `company_news` tools + a composite
  `stock_research_dossier`; equity options reuse the **generalized** pricing engine,
  not a route-layer reimplementation), the Claude Code connection + analysis
  playbook that work today, and the scoped CML-vs-EMF **backtest harness** (a future
  `src/nexus_core/research/` subpackage). Documents three **load-bearing gates**:
  (A) MBOUM data-redistribution rights before any research data ships publicly;
  (B) the MBOUM research endpoints are unverified — a live-key probe is task #0;
  (C) the backtest is SEC-Marketing-Rule-regulated performance/comparison content
  needing a hard off-the-public-surface boundary + CCO sign-off + copyright review
  **before** it is built. Findings were adversarially verified for compliance,
  repo-boundary, and feasibility.
- **`examples/stock_research_agent.py`** — a runnable Claude Agent SDK reference
  agent over the hosted MCP server that evaluates one equity idea through the
  **regime + EMF durability** lens (`current_regime` → `score_asset` →
  `get_quote`/`get_price_history` → `get_economic_series`) into a graded
  **REGIME×SCORE** dossier. Uses only shipped, read-only tools (no scaffold
  required) and renders the valuation / analyst / estimates / equity-IV /
  news legs as explicit **gap** lines — never fabricated. Output is a
  confidence-tiered assessment, not a buy/sell call. README + the planned-examples
  list updated.

### Planning — optimizer-driven allocation + report assembly (planning tools 19 → 21)

#### Added

- **`optimize_allocation` planning tool (MCP + REST)** — optimizer-driven target
  asset-class weights. Composes the engine's capital-market assumptions (forward
  house-view returns or a `historical` mean, real-data volatility, and a
  Ledoit-Wolf-shrunk correlation matrix) into a mean-variance optimization. Drive
  it with a `riskProfile` (conservative..aggressive → a mean-variance
  risk-aversion), an explicit `objective` (`max_sharpe` / `min_volatility` /
  `max_quadratic_utility` / `efficient_return` / `efficient_risk`), or — by
  default — an objective selected for the **live macro regime**. Returns weights +
  expected return/volatility/Sharpe + the regime context. Illustration only.
- **`build_planning_report` planning tool (MCP + REST)** — assembles the
  de-identified outputs of the other planning tools into one ordered,
  render-ready report envelope: canonical section order (executive summary →
  regime → assumptions → allocation → analytics → projection → withdrawal → tax →
  Social Security → risk → appendix), auto-derived findings for recognized section
  kinds, consolidated assumptions, and the comprehensive disclaimer. PII-free; not
  an IPS.
- **`engine.optimization.optimize_from_moments(mu, Sigma, asset_ids, ...)`** — a
  new optimizer entry point that takes forward moments directly (so it can be
  driven by capital-market assumptions rather than a realized price history),
  spanning `max_sharpe` / `min_volatility` / `max_quadratic_utility` /
  `efficient_return` / `efficient_risk`.

#### Changed

- **`serve` extra now includes `PyPortfolioOpt`** so `optimize_allocation` works on
  the public surface (the heavier Riskfolio-Lib / skfolio backends stay in the
  `[optimization]` extra). Requires a redeploy to take effect.

### Uniswap V3 — enumerate the positions an address owns

#### Added

- **`GET /api/lp/uniswap-v3/{chain}/positions?owner=`** — list the open
  (liquidity > 0) Uniswap V3 positions an EVM address owns, on ethereum / base /
  optimism / polygon. Per position: pool, fee tier, tick range, in-range, current
  token amounts, and uncollected fees — in **token units** (no USD; valuation
  still needs the per-token prices the analytics route takes). Anonymous public
  on-chain data (input is a public address + chain). Complements the existing
  by-`token_id` analytics route, which required you to already know the NFT id.
- **`TheGraphClient.fetch_v3_positions_by_owner(chain, owner)`** — the subgraph
  `positions(where: {owner, liquidity_gt: 0})` enumeration backing it; the
  single-position + by-owner queries now share one `_parse_position` helper.

### Monte Carlo decumulation — spend schedule + sequence diagnostics

#### Added

- **Input: `spendSchedule`** on `monte_carlo_decumulation` — optional gross-spend
  adjustments after `retirementAge`: recurring `delta` bumps/reductions, age-range
  `override` amounts, and `one_time` lump expenses. This makes late-life shocks
  such as LTC costs first-class instead of forcing a flat-spend proxy.
- **Output: `depletionStats`** — failed-path count/probability plus conditional
  depletion-year percentiles, and depletion-age percentiles when `currentAge` is
  known through the planning gateway.
- **Output: `firstDecadeReturnVsOutcome`** — median first-decade annual return for
  successful vs. failed paths, exposing sequence-of-returns sensitivity without
  changing the existing success/terminal/median-balance fields.

### Dependencies — make `[all]` (and `[backtest]`/`[onchain]`) installable again

The `[all]` extra was unsatisfiable — two latent conflicts blocked any resolution
of the full graph:

#### Changed

- **`pandas` pinned to `>=2.2,<3.0`** (was `>=3.0.3`). `alphalens-reloaded` (the
  `[backtest]` extra) caps `pandas<3.0` — pandas 3.0 broke it and there is no
  pandas-3-compatible release — so the project follows suit to keep `[backtest]`
  installable + working at its latest (0.4.6). The core engine uses no
  pandas-3-only API (verified), so the deployed `serve` surface is unaffected.
  Lift the cap if/when alphalens-reloaded ships pandas-3 support.

#### Removed

- **`ethereum-etl` dropped from the `[onchain]` extra.** It is unused (nothing in
  `src/` imports it) and its latest release (2.4.2) pins `web3<6`, irreconcilable
  with the extra's `web3>=7.16.0`. The onchain data layer reads via HTTP providers
  (DeBank / Tatum / TheGraph / Jupiter / DeFiLlama), not direct RPC; `web3` (kept
  at the modern v7) remains for any future direct-RPC reader.

With both, `uv lock` resolves the entire `[all]` graph (298 packages) — every
other extra stays at its latest (zipline 3.1.1, web3 7.16.0, torch 2.12.0,
numpy 2.4.6); only pandas holds at 2.3.3.

### PlanningContract v1.1.0 — employer-plan balances, survivor compression, structured ACA

Additive, backward-compatible minor bump (a v1.0.0 caller still works; new fields
default/optional). `PLANNING_CONTRACT_VERSION` 1.0.0 → **1.1.0**.

#### Added

- **Input: `accounts.employer_plan_aggregate`** (`engine/planning/case.py` + schema)
  — pre-tax 401(k)/403(b) money. Not directly convertible (roll to an IRA first), but
  it's folded into the **do-nothing RMD-drag pool** (the projection is now on the
  Traditional IRA + employer plan).
- **Output: survivor-year compression** on `DoNothingProjection`
  (`survivor_first_year_rmd_marginal_rate`) — for a married-joint plan, the marginal
  rate the first-year RMD would face if the surviving spouse filed **single** (the
  ~half-width brackets); `None` when filing is already single/mfs. Computed from the
  injected bracket table's single schedule (no new input needed).
- **Output: structured ACA interaction** on `YearAnalysis.aca` (`AcaInteraction`) —
  promotes the prior notes-only ACA estimate to a structured field (cliff_mode,
  MAGI %-of-FPL before/after, PTC before/after, incremental loss, hard-cliff crossing)
  when an `AcaSituation` is injected; `None` otherwise. The human note is retained.
- Output JSON-Schema (`result_schema.py`) regenerates with the new fields; both
  schema `$id`s bumped to 1.1.0.
- +4 tests (employer-plan RMD pool, survivor rate for mfj vs none for single, ACA
  structured field present/absent, employer-plan round-trip). Full suite green;
  coverage 88%.

### ACA premium-tax-credit cliff — flag-with-magnitude (no contract change)

The composite Roth/IRMAA analysis can now **quantify** the ACA marketplace
premium-tax-credit (PTC) cliff for a pre-65, marketplace-enrolled household,
instead of only flagging it. It is an **injected parameter** — `analyze_roth_conversion`
/ `sequence_conversions` gain an optional `aca: AcaSituation | None` (like
`state_rule`), so **PlanningContract v1.0.0 and the output shape are unchanged**
(the estimate is surfaced in the per-year `notes`, not a new field).

#### Added

- **`AcaSituation`** (`engine/planning/tables.py`) — injected ACA config: household
  size, benchmark (SLCSP) premium, marketplace enrollment, FPL figures, the
  applicable-percentage ramp, and `cliff_mode` (`hard_400fpl` — the pre-2021 /
  post-2025 hard 400%-FPL cliff; `capped_8_5` — the 2021–2025 ARPA/IRA 8.5% cap).
  `from_dict` + `reference_aca_situation(...)` (illustrative 2024-basis FPL incl.
  AK/HI).
- **`engine/planning/aca.py`** — pure `aca_ptc(magi, situation)` +
  `aca_cliff_estimate(magi_before, magi_after, situation)` (PTC erosion + hard-cliff
  crossing). Documented as a flag-with-magnitude estimate, not a precise PTC
  determination; uses the conversion-year IRMAA MAGI as the ACA MAGI proxy.
- When an `AcaSituation` is injected, the year note reads e.g. *"ACA cliff CROSSED:
  the conversion lifts MAGI from 350% to 425% of FPL … estimated PTC loss ~$13,240/yr"*;
  absent the injection, the prior qualitative flag is kept.
- Gateway: `POST /mcp/tools/{analyze_roth_conversion,sequence_conversions}` accept an
  optional `aca` object in the body (omitted on the public/reference path).
- 18 new tests (PTC math, the hard cliff vs 8.5% cap, the cross-cliff estimate, and
  the composite note quantified-vs-generic). Full suite green; coverage 88%.

### Multi-year Roth-conversion + IRMAA planning (PlanningContract v1.0.0)

A composite planning capability that sizes a Roth conversion for a ~60-something
retiree across multiple years when the binding constraint is **IRMAA (Medicare
premium surcharges), not the tax bracket**. All tax/IRMAA figures are *injected*
tables — the engine reads no built-in dollar amount — so a caller can snapshot the
exact basis used into a retention record. PII-free by construction.

#### Added

- **PlanningContract v1.0.0 — the canonical PII-free case shape.** A frozen
  dataclass (`engine/planning/case.py`) + a canonical JSON-Schema
  (`engine/planning/planning_contract.schema.json`, the cross-language source of
  truth) + a strict `from_dict` validator. Opaque `case_id`, birth *years* not
  DOBs, aggregated balances — no identity field anywhere, in input or output.
  Nested unknown keys are rejected (closes a PII-smuggling gap), non-finite
  numbers are rejected, and `tax_year` must be the earliest `intent.years`. The
  output `RothConversionAnalysis` shape (`engine/planning/analysis.py`) has a
  drift-proof JSON-Schema *generated* from the dataclasses
  (`engine/planning/result_schema.py`).
- **`irmaa_headroom`** (`engine/planning/irmaa.py`) — room before the next
  *projected* IRMAA cliff. IRMAA runs on a 2-year MAGI lookback (a conversion in
  year N drives premiums in N+2) and CMS publishes the N+2 floors late, so this
  projects the source-year tiers forward at an inflation assumption (rounded to
  $1k) and holds a buffer below the projected floor. Returns the projection
  inputs for snapshotting. It is a cliff: $1 over a floor applies the whole
  tier's surcharge, per beneficiary.
- **`analyze_roth_conversion`** (`engine/planning/roth_analysis.py`) — the
  composite. Per year: `bracket_ceiling` vs `irmaa_ceiling`, takes `min(...)`
  (IRMAA usually binds for 60s), gates by `taxable_liquidity` (tax paid from
  *outside* the IRA), applies IRC §72 pro-rata when nondeductible basis is
  present, and surfaces the Social-Security tax torpedo, the LTCG-stacking
  interaction (0%→15%→20%), NIIT (3.8%), state treatment (e.g. PA exempts
  conversions past retirement age), the IRMAA cliff cost if crossed, the breakeven
  retirement rate, and the do-nothing RMD drag (SECURE 2.0 start age 73/75). OBBBA
  (2025) made the brackets permanent, so the rationale is the gap-year window, not
  a TCJA sunset.
- **`sequence_conversions`** (`engine/planning/roth_analysis.py`) — the multi-year
  sequencer: the per-year split + totals across the intent years against both
  ceilings, drawing down the running IRA balance.
- **Injected tables** (`engine/planning/tables.py`) — `BracketTable`,
  `IrmaaTable`/`IrmaaTier`, `StateConversionRule` with wire-form `from_dict`
  parsers + illustrative `reference_*` factories (clearly labelled; verify against
  IRS/CMS). The income→tax model (`engine/planning/income_model.py`) computes
  taxable Social Security, AGI, the IRMAA + NIIT MAGIs, and the three federal tax
  components together so the interactions are captured.
- **Exposed on the internal service + MCP.** New gateway tool ids
  `analyze_roth_conversion`, `sequence_conversions`, `irmaa_headroom`
  (`POST /mcp/tools/{id}`, snake_case body; `analyze_*`/`sequence_*` take the
  PlanningContract under `contract`, with optional injected tables flagged
  `caller_provided` vs `engine_reference` in the snapshot). The same handlers are
  registered as native MCP tools. Fail-closed PII scan + disclaimer apply.
- **Tests.** ~100 new tests: the cliff (just-under vs just-over a tier), the
  projection math + buffer, pro-rata with basis, the binding-ceiling = `min(...)`
  selection, the liquidity gate, a 2-year split, the SS torpedo, LTCG stacking,
  NIIT, state treatment, contract round-trip/validation, schema in-sync, and the
  serializable + identity-free output.

#### Changed

- `ordinary_tax`, `bracket_headroom`, and `roth_conversion` gained optional
  `brackets` / `std_deduction` arguments (backward-compatible; default to the
  built-in table) so the composite can inject a snapshot-able bracket basis.

### Platform hardening — compliance, security, reliability, MCP, EMF coverage

A broad pass making the public deployment agent-reliable and audit-ready. Test
suite grew 636 → 724; `mypy --strict` + ruff are now CI-enforced (previously
neither ran in CI). Deployed at `nexus-core-00040`.

#### Added

- **Call-side vol skew — `crypto_vol_skew` (which strike is richest to write).**
  `engine/pricing/skew.vol_skew` gives IV + Black-Scholes **vega by strike** at one
  expiry (nearest a target tenor), framed for a covered-call writer: the **25Δ call
  skew** (`IV(25Δ call) − IV(ATM)` — positive ⇒ OTM calls richer, favorable for OTM
  overwriting), the **richest OTM strike** (highest IV), and per-strike vega (the
  vol exposure shorted). Completes the strike-selection trio with the term structure
  (which tenor) and the regime tilt (how far OTM). REST
  `GET /api/options/crypto/{ccy}/vol-skew?target_days=` + MCP `crypto_vol_skew`.
  Inverse vega is a USD-space BS approximation (noted). 4 engine + 1 route + 1 MCP
  test.
- **Crypto-options agent quickstart + worked prompts.** `examples/crypto_options_agent.py`
  — a Claude Agent SDK agent over the hosted MCP server (`nexusmcp.site/mcp`) that
  drives the overwriting suite conversationally (live regime → regime-tilted strike
  → IV term structure → coin-yield → put/collar/stress), least-privilege allowlist,
  public/illustrative inputs only. Plus three crypto-options worked prompts added to
  the `/mcp` connect guide. Lets the suite be driven from Claude end to end.
- **IV term structure — `crypto_iv_term_structure` (which tenor pays richest to
  write).** `engine/pricing/option_chain.iv_term_structure` builds the near-ATM
  implied-vol curve across expiries from the live Deribit chain: per-tenor near-ATM
  IV + mean IV, the richest tenor (highest near-ATM IV), and the curve shape
  (backwardation = near-term richer, contango = rising). REST
  `GET /api/options/crypto/{ccy}/iv-term-structure` + MCP `crypto_iv_term_structure`.
  A near-ATM illustration over listed calls, not a fitted surface. 3 engine + 1
  route + 1 MCP test.
- **Tunable regime tilt — a `defensiveness` risk knob on `crypto_regime_overwrite`.**
  A single scalar that scales the *magnitude* of the regime→delta tilt: `0` = no
  tilt (neutral), `1` = house default, `>1` = amplified (more defensive in fragile
  regimes, more aggressive in benign ones). `regime_adjusted_target_delta` now takes
  `defensiveness`; the effective multiplier is `1 + (house - 1) × defensiveness`
  (clamped). Surfaced on the REST route (`?defensiveness=`, [0,5]) + the MCP tool,
  and echoed in the response so the applied policy is transparent. Lets an operator
  dial their risk preference without a code change. +3 tests.
- **MCP coverage for the structured crypto-options tools.** The ladder / roll /
  book-MTM / scenario operations (REST-only since the overwriting suite landed)
  are now also native MCP tools: `crypto_covered_call_ladder`, `crypto_option_roll`,
  `crypto_options_book_mtm`, `crypto_options_scenario` (structured `legs` /
  `positions` list params, validated with human-readable errors). The full crypto
  overwriting + hedge surface is now reachable from agents, not just REST. +2 tests.
- **Regime-conditioned covered-call strike selection (the EMF differentiator).**
  `engine/pricing/regime_overlay.py` tilts the written call's *target delta* by the
  LIVE EMF macro regime: defensive (further OTM, lower delta) in fragile regimes
  (crisis/stagflation/deflationary), richer-premium (closer strike) in expansion.
  The per-regime delta multipliers are the single documented tuning point; it then
  selects the matching strike from the live Deribit chain and illustrates it. REST
  `GET /api/options/crypto/{currency}/regime-overwrite` (the route 503s without a
  regime engine) + MCP `crypto_regime_overwrite`; the regime engine is now threaded
  into the options router + crypto MCP tools. 5 engine + 1 route + 2 MCP tests.
- **Coin-denominated protective put + collar (engine + REST + MCP).** Completes
  the hedge side of the crypto overwriting toolkit:
  `crypto_overlays.crypto_protective_put` (floor, cost-of-protection, P(protection
  pays)) and `crypto_collar` (put floor + financing short call → net credit/debit,
  upside cap + downside protection). Settlement-aware (inverse premiums in coin),
  reusing the `premium_usd` bridge. REST `GET /api/options/crypto/{currency}/
  {protective-put,collar}` + MCP `crypto_protective_put` / `crypto_collar`. 5
  engine + 3 route + 1 MCP test.
- **Crypto options covered-call *overwriting* suite (engine + REST + MCP).** A
  settlement-aware analytics layer for writing calls against a crypto treasury,
  built on the existing Black-Scholes engine + Deribit client (BTC/ETH inverse,
  SOL/XRP/TRX/AVAX linear). New pure `engine/pricing/` modules:
  - `crypto_overlays.crypto_covered_call` — inverse (coin-settled) vs linear
    (USDC) covered call. Surfaces the coin-denominated yield/income that a
    coin-treasury overwrite actually earns, alongside the unified USD metrics
    (static + annualized yield, cushion, return-if-assigned, breakeven, P(OTM)).
  - `option_chain.{rank_covered_calls, select_by_delta}` — rank a chain's OTM
    calls by annualized covered-call yield; pick a strike by target delta.
  - `overwrite.{covered_call_ladder, roll_analysis}` — a calendar/strike ladder
    (coverage, blended yield, per-leg) and roll up/out economics (net credit,
    realized P&L, roll type).
  - `options_book.{book_mtm, scenario_stress}` — mark a multi-leg book + aggregate
    net Greeks (incl. the underlying coin delta), and a spot×IV stress grid with
    short-call assignment flags. Inverse Greeks are a documented USD-space BS
    approximation (directional, not exact settlement P&L).

  Surfaced as REST `GET/POST /api/options/crypto/{currency}/...` (covered-call,
  covered-call-chain, ladder, roll, book/mtm, book/scenario; live spot +
  settlement from the Deribit index) and as MCP tools `crypto_covered_call` +
  `crypto_covered_call_chain`. 17 engine + 11 route + 2 MCP tests. Educational
  illustration only — booking under an ISDA/CSA, execution (FalconX), and
  custody/collateral (Anchorage) are explicitly out of scope.
- **Three more planning calculators (engine + REST/MCP tools), planning tools
  13 → 16.** All pure + deterministic in `engine/planning/`, with matching gateway
  tools (JSON `body`, `contractVersion` echo); no contract-version bump (additive
  tool ids, 0.1.0):
  - `fire` — FIRE / Coast-FIRE: the FIRE number (`annualSpend ÷ swr`), the coast
    number needed today (no further contributions compound to the FIRE number by
    the retirement age), projected balance at retirement, and years/age to
    financial independence with level contributions.
  - `risk_metrics` — return-series risk statistics: annualized return / volatility,
    Sharpe, Sortino, maximum drawdown, and historical VaR / CVaR (95%); pure Python,
    no numpy/empyrical dependency.
  - `rebalance` — rebalance-to-target: per-asset drift from target weights and the
    self-financing trade list (with one-way turnover), over the same blended
    portfolio the other portfolio tools use.

  10 engine tests + 6 gateway tests; the native-MCP registration test now asserts
  every planning tool id.
- **Portfolio X-ray — regime-aware structural diagnostics (engine + REST/MCP tool),
  planning tools 12 → 13.** `engine.planning.portfolio_xray` reads a de-identified
  portfolio (blended weights + per-asset return/vol/λ + account-type mix) and
  returns portfolio metrics (weighted return, weighted-avg vol, concentration via
  Herfindahl + effective holdings, portfolio λ, growth sleeve, account mix) and a
  list of structured findings — concentration, tax-location spread, growth posture,
  and the differentiator: **regime sensitivity conditioned on the LIVE macro
  regime** (a high portfolio λ in an adverse regime is flagged). The
  `portfolio_xray` tool injects the live regime. Pure + deterministic; 5 engine
  tests + 2 gateway tests; no contract-version bump (additive tool id, 0.1.0).
- **Four new planning calculators (engine + REST/MCP tools), planning tools 8 → 12.**
  All pure + deterministic in `engine/planning/`, reusing existing tables, with
  matching gateway tools (a JSON `body`, `contractVersion` echo):
  - **`rmd`** — IRS Uniform Lifetime Table required minimum distribution (reuses
    `tax.rmd_factor`).
  - **`tax_bracket_headroom`** — marginal bracket + ordinary-income room before the
    next federal rate, or up to a target rate ("Roth-fill"); reuses
    `tax.ordinary_brackets` + `standard_deduction` (now public).
  - **`social_security_claiming`** — benefit at each claim age 62–70 from the PIA
    (SSA early-reduction / delayed-credit factors) + breakeven ages.
  - **`regime_conditioned_swr`** — a base safe withdrawal rate adjusted by an
    illustrative per-regime multiplier; the gateway tool injects the LIVE regime.
  - +25 engine tests + 8 gateway tests; `llms.txt` / MCP guide / README updated to
    12 planning tools. No contract-version bump (additive tool ids, `0.1.0`).
- **`roth_conversion` + `sequence_of_returns_stress` are now planning tools.**
  Both engine primitives are exposed as REST tools (`POST /mcp/tools/{id}`) and
  native MCP tools (`/mcp` HTTP + stdio) via the same generic handler registry —
  taking a JSON `body` and echoing `contractVersion`. The two planning-tool count
  goes 6 → 8 (`tools/list`, `/mcp/tools`, the MCP guide, and `llms.txt` updated).
  Gateway tests cover happy-path + a validation case for each.
- **Roth conversion calculator (`engine.planning.roth_conversion`).** Should you
  convert pre-tax dollars to Roth this year? Computes the conversion's *true
  incremental* federal tax by reusing the engine's progressive bracket model
  (`ordinary_tax(income + conversion) − ordinary_tax(income)`), so it captures
  bracket creep instead of assuming a flat marginal rate, then compares the
  after-tax terminal value of converting now vs. leaving the dollars pre-tax and
  taxing them at a retirement marginal rate. Reports `conversionTax`,
  `effectiveConversionRate`, `rothSeed` / `externalTaxPaidToday` (taxes paid from
  the conversion vs. outside funds), the two `*AfterTaxValue`s, `netBenefit`, and
  `breakevenRetirementRate`. Pure + deterministic; documented federal-only
  simplifications; 11 tests, 100% module coverage. Engine primitive — no
  wire-contract change (tool/contract/UI exposure is a follow-up).
- **Sequence-of-returns stress (`engine.planning.sequence_of_returns_stress`).**
  A pure, deterministic complement to the Monte Carlo: hold a fixed multiset of
  annual returns constant and replay the same withdrawal schedule worst-first /
  best-first / as-given. Since the arithmetic mean is identical across orderings,
  the terminal spread (`sequenceRiskGap`) is attributable purely to ordering —
  and with no withdrawals it is provably zero. Reports per-ordering terminal
  balance + depletion year. Within-year mechanic (withdraw at start, grow, floor
  at zero) matches `monte_carlo_decumulation`. 11 tests, 100% module coverage; no
  wire-contract change (engine primitive — tool/contract exposure is a follow-up).
- **Machine-readable AI-disclosure card** (`GET /.well-known/ai-disclosure.json`
  + an `llms.txt` pointer). Conforms to the sibling
  `@protocolwealthos/disclosure-card` open-standard schema (dogfooding pwos-core's
  flagship adoptable standard) and **mirrors Protocol Wealth's published "AI and
  Technology Disclosure"** at <https://protocolwealthllc.com/disclosures/>, which
  the card links to as the authoritative human-readable source: human adviser +
  compliance oversight before any client-facing recommendation, AI never the sole
  basis for advisory decisions / no final investment decisions / no trade
  execution, data minimization, and supervisory records of AI-assisted workflows.
  Values stay accurate to this read-only, model-less, no-client-data service
  (`model.provider: "none"`, zero retention, PII `block`). A test validates the
  card against a vendored copy of the published JSON Schema.
- **Planning tools are now native MCP tools.** The six pwplan-core planning
  tools (`monte_carlo_decumulation`, `glide_path`, `tax_aware_withdrawal`,
  `correlation_matrix`, `capital_market_assumptions`, `regime_return_generator`)
  register in `tools/list` over both the `/mcp` HTTP transport and stdio — not
  only via the REST gateway — reusing the same handlers (contractVersion `0.1.0`).
- **MCP setup guide — Claude Code + worked examples.** `/mcp-guide` now documents
  the Claude Code path (`claude mcp add --transport http` + a shareable
  `.mcp.json`), an "example prompts" section that drives the regime and planning
  tools in plain language, and a worked `monte_carlo_decumulation` request
  showing the load-bearing response fields. The native planning tools take the
  request as a JSON `body` argument (now called out in the guide). +2 guide tests.
- **`examples/planning_agent.py` — reference Claude Agent SDK agent.** A PII-free
  example that wires the Claude Agent SDK to the *hosted* nexus-core MCP server
  and lets Claude orchestrate the planning flow end to end (current regime → real
  capital-market assumptions → Monte Carlo decumulation → tax-aware withdrawal).
  Least-privilege `allowed_tools` (read-only regime + planning tools only),
  headless `permission_mode`, de-identified inputs. The SDK is a demo-only dep
  (lazy-imported), not a nexus-core dependency; the module is import-safe without it.
- **`health` and `describe` MCP tools.** `health` reports per-upstream status
  (market quotes, FRED, Deribit, DefiLlama); `describe` returns the tool catalog
  by category, the symbology rules, and the planning contract version.
- **`get_quotes` batch tool** — up to 25 quotes per call.
- **Read-only tool annotations** (`readOnlyHint`) on every MCP tool, so clients
  can auto-approve calls.
- **Data provenance** — quotes carry `as_of` (the data point's session date),
  `source` (the provider), and `market_status` (`current` / `last_close`); FRED
  responses carry `as_of` (observation date) + `source`. A Friday close pulled
  on a Saturday now reads as `last_close`, not a live price.
- **Regime breadth + precious-metals signals** — `breadth` = % of the 11 SPDR
  sector ETFs above their 200-day MA; `precious_metals_signal` = GLD vs its
  200-day MA (bullish/neutral/bearish). Free, no new API.
- **Agent + discovery files** — `/llms.txt` (llmstxt.org), `AGENTS.md`,
  `/.well-known/security.txt` (RFC 9116), and a `Connecting pwplan-core` section
  in `/mcp-guide`.
- **OpenAPI** `servers` block (hosted base URL) + per-tag descriptions.
- **CI** — `.github/workflows/ci.yml` runs `ruff` + `mypy --strict` + `pytest`
  with an 80% coverage floor on every push/PR.
- **EMF coverage** — ASAN gained five sector buckets (technology_hardware,
  communication, materials, utilities, real_estate); Perez resolves capex-light
  sectors (banks/REITs) from revenue growth; `layer_for` routes crypto
  (BTC→L1, ETH→L2) and sector/commodity ETFs to a durability layer.

#### Changed

- **Canonical disclaimers** — a single `disclaimers.py` (TERSE / MC / FULL +
  Safeguards) wired across every MCP tool, REST route, web page, and the OpenAPI
  description; the prior seven ad-hoc strings now share one auditable text that
  also covers tax / legal / AI-generated-content / as-is.
- **Score tier gating** — `score_asset` returns `NOT APPLICABLE` + a `tier_note`
  when fewer than half the checks evaluate (e.g. ETFs/crypto with no SEC
  fundamentals), instead of a verdict-shaped `BELOW THRESHOLD`.
- **ASAN fail-safe** — an unclassifiable sector is now *not evaluated*
  (`passed=None`) rather than auto-passed (which silently inflated scores, e.g.
  AAPL 6/8 HIGH → a true 5/8 MODERATE).
- `layer_assignment` is hoisted to the top level of a score result.
- `fastmcp` pinned `>=3.0.0,<4`.

#### Fixed

- **`mypy --strict` is green** — fixed 12 pre-existing errors that had drifted
  in undetected (no CI ran mypy before).
- **`defi_protocol`** now returns TVL — derived from `currentChainTvls` with an
  `excludeTotalDataChart` query param that also avoids the multi-MB-payload
  timeout that broke aave/uniswap.
- **FRED resilience** — `get_series` retries on a 429 (rate-limit burst) and
  logs an upstream 4xx (invalid key) at WARNING instead of silent "No data".
- **Option input validation** at the MCP tools — `days<0` / `spot<=0` /
  `strike<=0` / `volatility<0` are rejected (was: silent raw intrinsic), while
  the valid `days=0` / `volatility=0` Black-Scholes limits still work.
- README quick-start used non-existent APIs and linked dead `/opensource`
  `/patent` routes; stale `~594`/`~580` test counts across docs.

#### Security

- **`mask_error_details=True`** on the MCP server — an unexpected tool exception
  can no longer leak `str(e)` (upstream URL/key/path) to the client.
- **Security-headers middleware** — `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy` on every response; a CSP on HTML
  responses only.

### Added — Deribit crypto options coverage: SOL fix + XRP/TRX/AVAX

- **Crypto option underliers expanded to six** — `GET /api/options/crypto/{currency}/instruments`
  now covers **BTC, ETH, SOL, XRP, TRX, AVAX**. Deribit migrated all altcoin
  options to USDC-settled (linear) books listed under a single `USDC` umbrella,
  so `data/derivatives/deribit.py` now queries that umbrella and filters by
  `<CODE>_USDC-…` instrument-name prefix for the linear underliers, while BTC/ETH
  keep their coin-settled (inverse) books. **Fixes** SOL silently returning zero
  instruments (it had been queried as `currency=SOL`, which Deribit now answers
  with an empty book). Keyless — no new secret.
- **`GET /api/options/crypto/currencies`** — new discovery endpoint listing the
  supported underliers and each one's settlement model (`inverse` / `linear_usdc`).
- `DeribitClient.supported_currencies()` / `settlement_model()` are now the single
  source of truth for the REST routes and the `crypto_option_instruments` MCP tool
  (no more hard-coded currency triples).

### Added — Multi-chain LP, Aerodrome Slipstream, position vs-benchmark, and Solana SPL prices

- **Aerodrome Slipstream LP analytics (Base, on-chain RPC)** —
  `GET /api/lp/aerodrome/{token_id}/analytics`. Slipstream is a Uniswap-V3 CLMM
  sibling, so the pure `engine/lp/uniswap_v3.py` math drives it unchanged. No
  canonical Slipstream subgraph exists on The Graph, so position state is read
  directly on-chain via Tatum RPC (`data/onchain/slipstream.py`): NFPM
  `positions` → CLFactory `getPool` → CLPool `slot0` → token `decimals`/`symbol`.
  Reports position value, in-range status, token amounts, and uncollected fees
  (decoded `tokensOwed`). Impermanent loss (needs deposit history), fee APR
  (needs pool volume), and AERO gauge reward APR are **not** available in
  on-chain-only mode and are reported as null/zero (`data_mode: onchain_rpc`).
  Envio indexing for full coverage (IL + fee APR + gauge APR) is a documented
  follow-on.
- **Multi-chain Uniswap V3 LP analytics** — `GET /api/lp/uniswap-v3/{chain}/{token_id}/analytics`
  now spans **ethereum, base, optimism, polygon**. The CLMM math in
  `engine/lp/uniswap_v3.py` is pure and protocol-agnostic, so the same engine
  drives every chain (per-chain config in `data/onchain/thegraph.py`). USD
  prices remain required query params; returns position value, in-range flag,
  exact IL-vs-HODL, fee-APR estimate, uncollected fees (Tatum `tokensOwed`),
  and Merkl reward APR → total APR. Arbitrum is **not** supported — its
  published subgraph ID uses an incompatible schema.
- **Position vs-benchmark** — `GET /api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark`
  compares a live LP position against hold-strategy benchmark returns over a
  window, reusing `engine/benchmarks.py`. Same required USD-price params as the
  analytics endpoint.
- **Solana SPL token USD prices** — `data/onchain/jupiter.py` (Jupiter v3,
  keyless) backing `GET /api/solana/price/{mint}` and
  `GET /api/solana/prices?mints=`. No API key required; degrades gracefully when
  the upstream is unavailable.

### Added — On-chain data, LP analytics, benchmarks, and a private market-data store (2026-05-19 → 2026-05-28)

- **Multi-chain native balances** — `data/onchain/tatum.py` (Tatum) backing
  `GET /api/chain/chains`, `GET /api/chain/balance/{chain}/{address}` (EVM
  `eth_getBalance` + Solana `getBalance`), and `GET /api/chain/native/{address}`.
  Requires `TATUM_API_KEY`; degrades to empty/None when absent.
- **Anonymous EVM wallet balance** — `data/onchain/debank.py` (DeBank) backing
  `GET /api/wallet/{address}`. No client data, no auth. Requires `DEBANK_API_KEY`.
- **DeFi vault discovery** — `data/onchain/vaultsfyi.py` (vaults.fyi v2) backing
  `GET /api/vaults` and `GET /api/vaults/chains`. Response parsing reads
  `apy` / `chain` / `vaultId`. Requires `VAULTSFYI_API_KEY`.
- **Uniswap V3 LP position analytics** — `engine/lp/uniswap_v3.py` pure CLMM
  math (tick math, `get_amounts_for_liquidity`, exact impermanent-loss-vs-HODL,
  fee-APR estimate) plus `data/onchain/{thegraph,merkl}.py` backing
  `GET /api/lp/chains` and
  `GET /api/lp/uniswap-v3/{chain}/{token_id}/analytics`. Returns position
  value, in-range flag, exact IL-vs-HODL, fee-APR, uncollected fees
  (RPC `tokensOwed` via Tatum), and Merkl reward APR → total APR. USD prices
  are required query params. Sources: The Graph + RPC + Merkl;
  requires `THEGRAPH_API_KEY` (and `TATUM_API_KEY` for uncollected fees).
- **Hold-strategy benchmarks** — `engine/benchmarks.py` (base-100, buy-and-hold)
  backing `GET /api/benchmarks`, `GET /api/benchmarks/series?days=` (on-demand
  from CoinGecko), and `GET /api/benchmarks/history?days=` (from persisted daily
  snapshots). Compositions: BTC/ETH/SOL, ETH-USDC 50/50·60/40·70/30,
  ETH-BTC 50/50; USDC held at $1.
- **Private market-data persistence** — `data/db.py` + `data/snapshots.py`
  (asyncpg) against a private-IP-only Cloud SQL instance (`nexus-marketdata`,
  POSTGRES_16) reached via Direct VPC egress. `GET /health/db` probes
  connectivity. `DATABASE_URL` gates persistence and
  `/api/benchmarks/history` (503 when unset).
- **Daily snapshot Cloud Run Job** — `jobs/daily_snapshot.py`, invoked via the
  `nexus-core snapshot` CLI command, run by a Cloud Run Job
  (`nexus-snapshot-job`) on an OAuth service-account identity, triggered by
  Cloud Scheduler (`nexus-daily-snapshot`, daily 01:00 America/New_York).
  No shared secret; no public write route.
- **Educational options overlays + crypto options** — Black-Scholes overlays at
  `GET /api/options/price` and `GET /api/options/overlay/{covered-call,cash-secured-put,collar}`,
  plus Deribit crypto options at `GET /api/options/crypto/{currency}/instruments`
  and `GET /api/options/crypto/instrument/{instrument_name}` (`data/derivatives`).

### Changed — Snapshot write path moved off the public surface (2026-05-19)

- The daily snapshot is now a Cloud Run Job (`nexus-core snapshot`), not an
  HTTP route. The public write endpoint was dropped; the public surface remains
  read-only.

### Fixed — Spoofing-resistant rate limiting (2026-05-28)

- The in-process rate limiter now resolves the client IP spoofing-resistantly:
  prefers `CF-Connecting-IP`, else the rightmost `X-Forwarded-For` entry.
  Layered behind a Cloudflare methods rule (blocks non-GET/POST/OPTIONS) and an
  edge rate-limit on cost endpoints. `NEXUS_RATE_LIMIT_PER_MIN` defaults to 60.

### Added — Tier-2: score explainability + deterministic replay + cross-link doc (2026-05-27)

- **`src/nexus_core/engine/scoring/explanation.py`** — new module exposing
  `ScoreExplanation`, `CheckExplanation`, `SignalContribution`, and
  `build_score_explanation()`. The explanation is *sanitized by
  construction*: `SignalContribution` carries only `(name, status,
  supports_regime)` — NO `current_value`, NO `threshold_info`, NO numeric
  cutoff. Downstream consumers can render an explanation surface without
  leaking the operator's production threshold values.
- **`src/nexus_core/engine/scoring/framework.py`** — `ScoreResult` gained
  `as_of: date | None = None` and `explanation: ScoreExplanation | None =
  None` (both default `None` for backward compat).
  `ScoringFramework.score(ctx, *, subject=None, as_of=None)` — new
  `as_of` keyword param; the score auto-populates the `explanation` and
  echoes `as_of` onto the result. `to_dict()` serializes both new fields.
- **`src/nexus_core/engine/regime/signals.py`** — `RegimeResult` gained
  `as_of: date | None = None`; `to_dict()` emits ISO date when set.
- **`src/nexus_core/engine/regime/classifier.py`** —
  `RegimeClassifier.classify(..., as_of=None)` accepts and echoes
  `as_of`. The classifier is unchanged on the classification logic
  itself — `as_of` is metadata for reproducible replay.
- **`src/nexus_core/engine/regime/engine.py`** —
  `RegimeEngine.fetch_signals(*, force_refresh=False, as_of=None)` and
  `RegimeEngine.classify(signals=None, *, prediction_market=None,
  as_of=None)`. When `as_of` is set, `fetch_signals` bypasses the cache
  and forwards to `SignalFetcher.fetch(as_of=...)` if supported (TypeError
  fallback to plain `.fetch()` for providers without `as_of` support).
- **`tests/test_explanation.py`** — N2 tests. Includes
  `test_signal_contributions_strip_threshold_and_raw_value` which asserts
  serialized contributions have ONLY the three sanitized keys (name /
  status / supports_regime); other tests exercise the per-check
  partitioning, the dict-or-object regime input shape, the framework
  integration path, and the `to_dict()` round-trip.
- **`tests/test_replay.py`** — N3 tests. Same-`as_of` same-result identity
  asserted for the classifier + the scoring framework (including the
  `ScoreExplanation`'s `to_dict()`).
- **`examples/deterministic_replay.py`** — runnable worked example with
  synthetic signals; zero data dependencies. Asserts byte-identical JSON
  serialization across two calls with the same `as_of`.
- **`docs/CROSS-LINK-PWOS-CORE.md`** — N4 conceptual note: three join
  points between this repo's outputs and `pwos-core`'s disclosure-card
  + provenance + HITL primitives.
- **`HANDOFF.md`** — extended with Tier-2 wiring contract; cross-references
  `pwos-core/HANDOFF.md` for the authoritative wiring instructions.
- Public-surface compatibility preserved: new fields default to `None`;
  `to_dict()` shape is additive; no symbol renamed or removed; no regime
  taxonomy change; no new threshold value added or modified. Apache-2.0 +
  USPTO #64/034,229 + OIN posture unchanged.

### Changed — Cross-repo governance parity with `pwos-core` (2026-05-27)

- **No new governance files needed in this repo.** `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and `CHANGELOG.md` already match the canonical PW open-source shape and were the source-of-truth pattern that `pwos-core`'s parallel hardening copied from. This entry records the cross-repo work for the audit trail; no file in this repo was modified except this CHANGELOG.
- **`pwos-core` side (sibling repo)** of the same iteration: CONTRIBUTING rewritten to remove fictional commands and list all 18 published packages; SECURITY scope tightened to pwos-core primitives; CODE_OF_CONDUCT project-name typo fixed; README gained a *What's Open vs Private* section mirroring this repo's, plus a rewrite of the "LLM autonomously selects and executes tools" line to surface the human-in-the-loop boundary between advisor IDE chat and client-facing writes.

### Changed — Public-repo honesty disclaimer + claim reconciliation (2026-05-14)

- **`README.md`** — added `## Status` block before `## What This Is`: this is a reference framework and starting point, not a production-ready product; adopters are responsible for adding their own PII controls, access control, input validation, authentication, and data-handling boundaries; the framework makes no AI-provider data-retention guarantees.
- **`README.md`** — Architecture diagram: replaced the unsubstantiated "Multi-tier access control" and "Transport-layer PII filtering" lines under MCP Tool Registry with an honest "Pluggable ResponseFilter hooks (adopter-supplied auth / PII / audit)" line that matches the actual code in `src/nexus_core/mcp/server/app.py`.
- **`docs/ARCHITECTURE.md`** — rewrote the "MCP Tool Pattern" section: the prior code example referenced a `check_tier(...)` function that does not exist in the codebase; replaced with the real `ResponseFilter` hook pattern. Replaced the "Tiered Access" table (PUBLIC / USER / CLIENT / ADVISOR scoring scopes claimed as built-in) with an "Access Control and Tiering (Adopter-Supplied)" section that states plainly the framework does not enforce access tiers and the scaffold treats all callers as trusted.
- No code change. Reconciles a public-repo audit finding flagging README + ARCHITECTURE EXISTS-tense capability claims for access control and PII filtering that the code did not back. Apache-2.0 + USPTO #64/034,229 defensive-licensing posture unchanged.

### Added — v0.3.0: Financials + Optimization absorption

- **`nexus_core.financials`** — new package, license-clean Apache 2.0:
  - `statements.py` — Pydantic models for `IncomeStatement`,
    `BalanceSheet`, `CashFlowStatement`, `StatisticsStatement`,
    `StatementBundle` (canonical envelope), with `Period` enum.
  - `ratios.py` — five families of ratios as pure functions:
    `liquidity`, `solvency`, `efficiency`, `profitability`,
    `valuation`. Returns typed `RatioPanel` subclasses.
  - `models.py` — DCF (perpetuity-growth), CAPM, WACC, DuPont
    (3-step + 5-step), Altman Z-Score (manufacturing variant) with
    distress-zone classification.
  - `performance.py` — Sharpe, Treynor, Information Ratio, Jensen
    alpha + beta, all annualized; `all_performance` composes.
  - `risk.py` — VaR family (historical / Gaussian / Cornish-Fisher),
    CVaR, downside volatility, max drawdown.
  - `adapter.py` — `from_finance_toolkit(toolkit)` reads a fetched
    `financetoolkit.Toolkit` instance and produces a
    `StatementBundle`. Optional `[financials]` extra unlocks the
    bridge; everything else works without it.
- **`nexus_core.engine.optimization`** expansion — twelve entry points:
  - PyPortfolioOpt-backed (existing): `optimize`, `optimize_for_regime`,
    `max_sharpe`, `min_volatility`, `target_return`, `target_risk`, `hrp`.
  - Riskfolio-Lib-backed (new): `risk_parity` (24+ risk measures),
    `hierarchical_risk_parity` (richer than PyPortfolioOpt's HRPOpt),
    `min_cvar`.
  - Black-Litterman (new): immutable `View` value object with
    `absolute_view` / `relative_view` builders, plus
    `black_litterman_posterior` to feed any optimizer's `mu` input.
  - Discrete allocation (new): `discrete_allocate` with `lp` /
    `greedy` methods, returns `DiscreteAllocationResult` with
    integer shares + leftover cash.
- **`pyproject.toml`** — new `[financials]` extra (`financetoolkit>=2.0.0`).
- **Tests:** 33 new (26 financials + 7 optimization shapes).
  `pytest tests/` reports 90 passed.
- **Attribution:** FinanceToolkit (MIT), PyPortfolioOpt (MIT),
  Riskfolio-Lib (BSD-3) added/updated in `NOTICE` and
  `docs/attribution.md`.

### Added — Phase 3a (regime + scoring engines)
- `nexus_core.engine.regime` — Multi-signal regime classification:
  - `RegimeCode` / `ClientType` / `SignalDirection` enums
  - `RegimeThresholds` / `ForcedLiquidationThresholds` (configurable)
  - `RegimeSignals` / `SignalStatus` / `RegimeResult` dataclasses
  - `HysteresisState` — generic asymmetric enter/exit state machine
  - `RegimeClassifier` — pure `signals → result` function
  - `SignalFetcher` — provider-backed signal fetching with fallbacks
  - `RegimeEngine` — orchestrator with caching and regime tracking
  - Forced-liquidation dampener: VIX spike, breadth collapse, correlation
    spike, volume spike detection + `evaluate_dampener()` aggregator
- `nexus_core.engine.scoring` — N-check scoring framework:
  - `Check` protocol, `CheckResult` dataclass, `ScoringContext`
  - `ScoringFramework` orchestrator
  - `ConfidenceTier` enum with `classify_tier()` helper
  - `CHECK_METADATA` — academic source attribution for standard 8 checks
  - Enhancements: `consistency_enhancement`, `base_rate_enhancement`,
    `adversarial_brief_enhancement`
  - Formatters: `format_public`, `format_advisor`, `format_structured`
- `nexus_core.mcp.server` — FastMCP server scaffold with regime + scoring tools
- `nexus_core.data.providers` — `MarketDataProvider` / `MacroDataProvider`
  protocols
- Third-party wrappers:
  - `nexus_core.engine.optimization.pypfopt_wrapper` — PyPortfolioOpt with
    regime-aware method selection (MIT)
  - `nexus_core.data.edgar.edgartools_wrapper` — structured SEC filing access (MIT)
  - `nexus_core.ai.sentiment.finbert_wrapper` — FinBERT sentiment with
    optional PII redaction hook (Apache 2.0)
- Tests: 57 unit tests covering thresholds, hysteresis, dampener, classifier,
  engine, and scoring (all green)
- Examples: `basic_regime.py`, `basic_scoring.py`, `mcp_server.py`

### Added — Phase 1+2 (scaffolding)
- Attribution infrastructure (NOTICE, THIRD_PARTY_LICENSES.md,
  docs/attribution.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md)
- Directory scaffolding (src/nexus_core/ with 8 modules)
- pyproject.toml with optional dependency groups:
  - optimization (PyPortfolioOpt, Riskfolio-Lib, skfolio)
  - risk (empyrical-reloaded, pyfolio-reloaded, ffn)
  - pricing (QuantLib, FinancePy)
  - edgar (edgartools, Arelle, sec-parser)
  - market (yfinance)
  - ai (FinBERT, FinRobot, FinRL — heavy)
  - backtest (zipline-reloaded, alphalens)
  - compliance (Moov Watchman client)
  - onchain (Ethereum-ETL, web3)
  - planning (Monte Carlo retirement)
- License compliance CI workflow (forbids GPL/AGPL/SSPL)

### Changed
- Expanded README to include "Built on the shoulders of giants" attribution
- License: Apache 2.0 with defensive patent grant
- `pyproject.toml` ruff config: ignore PLR (complexity) and UP042 —
  domain logic is inherently branchy and `str + Enum` supports 3.12+

## [0.0.1] - 2026-04-12

- Initial public release of docs
