# Roadmap

Where Nexus Core is, what's landing now, and what's next. This is the
deployable public surface — the read-only REST API + MCP transport that runs
at [nexusmcp.site](https://nexusmcp.site), including its optional service-key
REST boundary — not the full `nexus_core` library
(optimization, risk, pricing, EDGAR, AI). For the library capabilities see the
[README](README.md); for what the deployment exposes and excludes see
[AUDIT.md](AUDIT.md).

Honest by design: "Done" means it runs in production today. No dates, no
guarantees, no marketing.

## Landing Now

Production Nexus now runs as a split surface: hosted native `/mcp` can remain a
public OAuth-compatible demo endpoint with only closed-world demo tools, while
`/api/*`, `/api/planning/tools/*`, and legacy `/mcp/tools/*` are gated by
`NEXUS_ACCESS_MODE=restricted` + `NEXUS_API_KEYS`. `pw-api` owns the
server-to-server key path. Browser apps such as PWOS and PWPortal should call
their own BFF/API routes and never hold Nexus service keys.

The hardened onchain-accounting engine is deployed on that restricted REST
surface at commit `e5f4d84`, Cloud Run revision `nexus-core-00070-zhx`. The
`0.2.0` accounting gateway exposes historical pricing, de-identified event
decoding, account-scoped FIFO cost basis/replay, and realized-PnL aggregation.
It is calculation substrate only: private ingestion, client linkage, statement
production, review, and retention remain in the private stack. The deployed
image completes #259 by registering the same four calculation handlers in
native MCP full mode; the hosted demo MCP tool set excludes accounting.
Accounting contract `0.2.0` implements #260's FIFO/PnL semantics, exact
remaining-basis conservation, method-pinned replay, and root-lineage hardening.
CCO/CIO/CTO approved methodology 2.0/FIFO for operational use on 2026-07-17.
The private `pw-api` consumer, exact-artifact controls, and founder client
dogfood now proceed without a separate methodology runtime gate.

Current source also corrects the Monte Carlo `student_t` return model so its
fat-tailed draw is scaled to the caller-supplied covariance matrix. Student-t
results generated before this fix overstated variance by `dof / (dof - 2)`;
for the current 5-degree model that was about 1.667x variance, or about 1.29x
volatility.

Current source also centralizes the RMD start-age policy. `rmd`,
`tax_aware_withdrawal`, and the Roth composite now use the same
SECURE/SECURE 2.0 birth-year table, with age-only callers remaining compatible
at the legacy age-73 default and birth-year-aware callers receiving the 1960+
age-75 rule plus the documented 1959 good-faith age-73 treatment.

Current source also centralizes illustrative federal tax and IRMAA reference
tables behind a version-stamped provider registry. Tax-sensitive public tools
fail closed for unregistered table years instead of silently reusing a stale
basis, and outputs carry the table version needed for reproducible report
manifests.

Current source also adds Monte Carlo report diagnostics for Wealth Roadmap
consumers: Wilson confidence intervals around success probability, sticky
depletion curves, failed-path conditional shortfall, first-decade return decile
exhibits, run manifests with de-identified assumption hashes and confidence
quality flags, and Guyton-Klinger cut/raise timing stats. These are additive
response fields; existing request shapes remain unchanged.

Current source also starts the S1 education-funding slice: `education_funding`
adds multi-student education cost FV and savings-need calculations, and
`education_vehicle_rules` adds a 2026 reference comparison table for 529 plans,
Coverdell ESAs, and UGMA/UTMA custodial accounts. Inputs stay de-identified.

Current source also adds the S8 deterministic planning waterfall. `project_cash_flow`
can remain a single-bucket projection for existing callers, or accept optional
taxable / traditional / Roth `accountBalances` with per-bucket returns,
taxable-first withdrawals, and a simplified early-withdrawal penalty model.
`monte_carlo_decumulation` and `solve_goal` can accept optional de-identified
`goals`; the gateway sorts those goals by priority, earlier projection year,
input order, and funding-year index, then the engine funds them path-by-path
after base spending and before growth. Results return the generated schedule and
per-goal funding statistics for replay.

Current source also adds the S2 income-layering slice. `income_layering` composes
earned income, Social Security claiming assumptions, pension/annuity streams,
forced RMDs, tax-aware portfolio withdrawals, and optional bracket-fill analysis
into a per-year stacked income timeline. Inputs are de-identified numeric
assumptions and account-type buckets only; no labels, account IDs, raw
transactions, or client records enter the public engine.

Current source also adds the S3 historical-blend slice. `historical_blend`
builds calendar-year returns, trailing 1/3/5/7/10-year windows, YTD and
last-quarter non-annualized windows, growth-of-dollar, and annualized mean /
sigma-band exhibits from aligned monthly public proxy returns. The wrapper
sources public asset-class histories; the pure engine sees only de-identified
return series and weights.

Current source also adds the S7 illustrative state/local tax layer. The
data-driven 2026 table covers no-income-tax states, PA/IL/MS/IA full retirement
exclusions, and selected partial/senior exclusions for CO/NY/VA/NJ/MD/DE.
`tax_aware_withdrawal` and `income_layering` accept optional 2-letter `state`
and deterministic `residencyChange` inputs, expose federal/state tax splits and
table versions when modeled, and mark unknown states unmodeled rather than
assuming zero. The public engine still accepts only de-identified numeric inputs
and state codes, never raw addresses or private account records. The Roth
composite's older conversion-rule table is aligned for the no-income and
full-retirement-exclusion states that fit that simpler rule shape.

Current source also adds the S9 household/survivor layer. `social_security.py`
now has a simplified two-person Social Security helper for own, age-reduced
spousal, household, and survivor benefit snapshots. `income_layering` can accept
optional spouse Social Security and first-survivor-year filing-status inputs,
then show survivor benefit continuity and joint-to-single tax compression in the
yearly timeline. The public boundary remains de-identified: PIAs, claim ages,
filing statuses, ages, and numeric assumptions only.

Current source also adds the S6 PW Wealth Roadmap report preset.
`build_planning_report` accepts `preset: "wealth_roadmap"` and keeps
`preset: "custom"` as the default. The Roadmap preset fixes the display title,
supports `focused` and `full` scopes, injects the required scope statement and
focused-scope planning-benefit notice, requires and stamps every section with
replay metadata, and emits full-scope priority actions as candidate observations
only. The public engine rejects `released` and caller-provided `curated`
workflow state. It emits structured report JSON only; branded PDF rendering,
release approval, archive records, and client delivery stay in the private stack.

Current source also adds the S11 inherited IRA / beneficiary decumulation slice.
`inherited_ira_analysis` compares lump-sum, equal-annual, and bracket-smoothed
inherited traditional IRA distribution strategies under a 10-year frame, stacks
taxable inherited distributions on beneficiary ordinary income using the
injected federal ordinary-tax table, ranks strategies by net after-tax receipts,
and returns an eligible-designated-beneficiary carve-out table. The result also
states that v1 is a strategy comparison, not a separate beneficiary
life-expectancy annual RMD compliance calculator. Inputs remain numeric and
de-identified only. Spousal rollover elections, trust/estate-specific rules,
state tax, client delivery, and books-and-records workflow stay outside the
public engine.

Current source also adds the S12 healthcare / long-term-care stress slice.
`project_cash_flow` and `monte_carlo_decumulation` accept optional `ltcShock`
plus `healthcareInflationRate`. The shock is de-identified numeric input only:
onset age, current-dollar annual cost, duration, and cost inflation. Cash-flow
rows expose base expenses and LTC shock expenses when present; Monte Carlo emits
a same-seed with/without-shock success-probability delta, self-insured
probability, and terminal-value comparison. S12 v1 rejects `ltcShock` +
Guyton-Klinger guardrails together; run those as separate scenarios. Diagnosis,
claims, provider names, insurance-policy data, release approval, archive
records, and client delivery stay in the private stack.

The collar-book realistic-fill layer is part of current source. The engine plus
REST/MCP parsers accept midpoint `net_credit` and optional executable pricing
(`executable_net_credit` or `call_bid` minus `put_ask`) and return stock price,
share count, per-position fill haircut, executable income/yield, and
portfolio-level executable yield only when every held line has executable
pricing. This is still an educational advisor worksheet: no live-chain
attestation, no custodian execution record, no orders, and no individualized
advice.

The private stock-screen import path lives outside this repo. PWOS `/market-data`
now imports Seeking Alpha CSV/XLSX research screens and persisted a 380-row
advisor-verified import (`7c30414f`) after PR #993. Nexus should only receive
de-identified candidate symbols, pre-screened fields, and option-chain facts
after private ingestion in PWOS/pw-api.

## Done

The current production surface. Python 3.12 · FastAPI · FastMCP · sync
`httpx` · `asyncpg` · `mypy --strict` · `ruff`. CI-gated test suite. Read-only,
no client data. Native MCP can run as a public demo endpoint; REST/JSON paths can
be service-key gated. Remote MCP may use transparent OAuth with no login. Every
external integration degrades
gracefully to `None` / empty / `503` when its key is absent.

### Regime & scoring

- **`GET /api/regime`, `/api/regime/signals`** — EMF regime classification
  (`engine/regime`, `RegimeEngine`).
- **`GET /api/score/{ticker}`** — 8-check EMF scoring on SEC EDGAR
  fundamentals (`engine/scoring/emf`).
- **Score explainability + deterministic replay** — sanitized
  `ScoreExplanation` (per-check pass/fail + signal contributions, no threshold
  values) and an `as_of` parameter for reproducible regime/scoring replay.

### Market, macro & economic data

- **`GET /api/market/quote/{symbol}`, `/api/market/history/{symbol}`** —
  composite market data (yfinance / MBOUM / MarketStack / CoinGecko).
- **`GET /api/economic/{series_id}`** — FRED economic series.
- **`GET /api/solana/price/{mint}`, `/api/solana/prices?mints=`** — Solana SPL
  token USD prices via Jupiter v3 (`data/onchain/jupiter.py`, keyless).

### Options (educational overlays)

- **`GET /api/options/price`** — Black-Scholes pricing (`engine/pricing`).
- **`GET /api/options/overlay/{covered-call,cash-secured-put,collar}`** —
  educational equity/ETF overlay structures.
- **`GET /api/options/crypto/currencies`,
  `/api/options/crypto/{currency}/instruments`,
  `/api/options/crypto/instrument/{instrument_name}`** — Deribit crypto options
  on BTC/ETH (coin-settled inverse) + SOL/XRP/TRX/AVAX (USDC-settled linear,
  read from Deribit's `USDC` umbrella) (`data/derivatives`). Keyless.
- **Crypto covered-call overwriting + hedge suite** — settlement-aware analytics
  for writing calls against a crypto treasury, live spot/settlement from the
  Deribit index. Pure engine in
  `engine/pricing/{crypto_overlays,option_chain,overwrite,options_book,regime_overlay,skew}.py`;
  exposed as REST `GET/POST /api/options/crypto/{ccy}/...` and as MCP tools:
  - `covered-call` / `covered-call-chain` — coin-denominated yield + chain ranked
    by annualized yield.
  - `iv-term-structure` (which tenor pays richest) + `vol-skew` (IV + vega by
    strike, 25Δ call skew, richest strike — which strike to write).
  - `regime-overwrite` — strike delta tilted by the LIVE EMF regime, with a
    `defensiveness` risk knob.
  - `protective-put` / `collar` — coin-denominated downside hedges.
  - `ladder` / `roll` / `book/mtm` / `book/scenario` — calendar ladder, roll
    economics, book MTM + net Greeks, spot×IV stress.

  Educational illustration only — booking (ISDA/CSA), execution (FalconX), and
  custody (Anchorage) are out of scope; the production program lives elsewhere.

### Onchain & DeFi

- **Onchain accounting P0-P5 (#248, PRs #254-#258, #262, #264)** — the separate
  `app/accounting` contract/gateway and `engine/accounting` package provide a
  multi-oracle price historian (`price_history`), protocol-aware de-identified
  event decoding (`decode_onchain_events`), FIFO lot/cost-basis analysis
  (`compute_cost_basis`), and realized-PnL/year rollups
  (`onchain_pnl_report`). Unknown prices and basis remain explicit rather than
  fabricated as zero; identity-shaped keys fail closed; canonical accounting/tax
  disclaimers are attached. Contract `0.2.0` is deployed through restricted REST
  on `nexus-core-00070-zhx`; the deployed image also registers the four
  calculation handlers in native MCP full mode while excluding them from demo
  mode. Issues #248 and #259 are complete and closed.
- **`GET /api/wallet/{address}`** — anonymous EVM wallet balance (DeBank).
- **`GET /api/chain/chains`, `/api/chain/balance/{chain}/{address}`,
  `/api/chain/native/{address}`** — multi-chain native balances via Tatum
  (EVM `eth_getBalance` + Solana `getBalance`).
- **`GET /api/vaults`, `/api/vaults/chains`** — DeFi vault discovery
  (vaults.fyi v2).
- **`GET /api/lp/chains`, `/api/lp/uniswap-v3/{chain}/positions?owner=`,
  `/api/lp/uniswap-v3/{chain}/{token_id}/analytics`,
  `/api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark`** — Uniswap V3 position
  analytics across **ethereum, base, optimism, polygon**. `positions?owner=`
  enumerates open positions an address owns (token units, no USD). By-token
  analytics add value, in-range status, **exact** impermanent-loss-vs-HODL,
  fee-APR estimate, uncollected fees (RPC `tokensOwed` via Tatum), and Merkl
  reward APR rolled into total APR. `vs-benchmark` adds hold-strategy benchmark
  returns over a window —
  the "was LPing worth it?" comparison. Pure CLMM math in
  `engine/lp/uniswap_v3.py` (tick math, `get_amounts_for_liquidity`, exact IL)
  is protocol-agnostic and reused across chains. USD prices are required query
  params. (The Graph + RPC + Merkl.) Arbitrum is **not** supported — its
  published subgraph ID uses an incompatible schema.

### Benchmarks

- **`GET /api/benchmarks`, `/api/benchmarks/series?days=`,
  `/api/benchmarks/history?days=`** — base-100 hold-strategy benchmark returns
  (BTC/ETH/SOL + ETH-USDC 50/50, 60/40, 70/30 + ETH-BTC 50/50; USDC held at
  $1; buy-and-hold). `/series` is computed on-demand from CoinGecko;
  `/history` reads persisted daily snapshots. Composition math in
  `engine/benchmarks.py`.

### Platform & operations

- **`GET /health`, `/health/db`** — liveness + DB connectivity probe.
- **`GET /api/usage`** — provider usage / quota report.
- **`POST /mcp`** — MCP-over-HTTP transport (FastMCP, also `nexus-core mcp` over
  stdio) exposing the above as tools, plus `health` / `describe` / `get_quotes`
  and the 34 current-source planning tools in full mode; demo mode registers
  only closed-world demo tools. `GET /api/planning/tools` +
  `POST /api/planning/tools/{id}` are the REST planning gateway
  (contractVersion `0.1.0`) for service/browser callers, with `/mcp/tools`
  compatibility aliases.
  The same handler set serves native MCP and REST, including
  `solve_goal`, `analyze_goals`, `project_cash_flow`, `income_layering`,
  the cash-flow bridge trio,
  `optimize_allocation`, `risk_profile_score`,
  `performance_analysis`, `build_planning_report`, and the Roth/IRMAA tools
  `analyze_roth_conversion`, `sequence_conversions`, and `irmaa_headroom`.
- **Persistence** — private Cloud SQL (`nexus-marketdata`, POSTGRES_16,
  private-IP-only on `pwllc-prod-vpc`, backups + deletion protection).
  Reached over Direct VPC egress; `asyncpg` (`data/db.py`, `data/snapshots.py`).
- **Daily snapshots** — `jobs/daily_snapshot.py` runs as a Cloud Run Job
  (`nexus-snapshot-job`, `nexus-core snapshot`) triggered by Cloud Scheduler
  (`nexus-daily-snapshot`, daily 01:00 America/New_York) under an OAuth
  service-account identity — **not** an HTTP write route, **not** a shared
  secret.
- **Spoofing-resistant rate limiter** — in-process per-IP limiter resolves the
  client IP from `CF-Connecting-IP` (else rightmost `X-Forwarded-For`).
  Cloudflare methods rule blocks non-GET/POST/OPTIONS; edge rate-limit on cost
  endpoints. Secrets live only in Google Secret Manager.

### Compliance, agents & platform hardening

- **CI quality gate** — `ruff` + `mypy --strict` + `pytest` (80% floor) on every
  push/PR. **Disclaimers** are canonical (`disclaimers.py`) across every surface;
  `score_asset` emits `NOT APPLICABLE` (not a verdict) on insufficient coverage.
- **MCP ergonomics** — `readOnlyHint` annotations; `health` (per-upstream status)
  + `describe` (catalog + symbology) tools; `get_quotes` batch; native planning tools.
- **Transparent MCP OAuth** — anonymous OAuth 2.1 / PKCE / Dynamic Client
  Registration flow for remote MCP clients, backed by stateless HMAC-signed tokens
  when `MCP_OAUTH_SIGNING_KEY` is set.
- **Data provenance** — quotes/FRED carry `as_of` / `source` / `market_status`.
- **Regime signals** — `breadth` (% sectors > 200DMA) + `precious_metals_signal`.
- **Agent/discovery** — `/llms.txt`, `AGENTS.md`, `/.well-known/security.txt`,
  security-headers middleware, OpenAPI servers/tags.
- **EMF coverage** — ASAN fail-safe + 5 sector buckets; Perez capex-light path;
  crypto/ETF durability-layer router (aligned with `SHARED/strategy/emf-canonical.md`).

## Next

Prioritized. Top item first.

**Accounting statement consumer — open `pw-api#789`.** Nexus technical issue
#260 is complete and deployed contract `0.2.0` now scopes FIFO books by account,
handles linked same-owner transfers and explicit fees, conserves authoritative
basis across snapshot boundaries, supports method-pinned replay, and returns
deterministic lineage plus structured completeness. Methodology 2.0/FIFO is
operationally approved. Finish and deploy the private consumer, retain
authenticated linkage and exact-artifact delivery controls, then record founder
client dogfood and partner review as post-deployment evidence.

**Public-safe planning/report analytics extraction — open issue #197.** Decide
which generic, PII-free analytics from private PWOS producer work belong in
nexus-core as educational substrate: allocation decomposition, diversification
readiness, index-proxy replay/backtest boundaries, model-portfolio context,
education-reference context, source-quality signals, and report-input coverage.
For the hybrid PW Cash Flow OS + PW Planning Lab + PW Retirement Income Lab
direction, this also includes public-safe planning-bridge analytics that consume
derived monthly-close values — for example cash-reserve analysis, budget pacing,
goal-funding deltas, or retirement-income guardrail inputs. Keep private/custodian
transaction ingestion, client-linked classification, Monarch import parsing,
report production, artifact receipts, client context, suitability, approvals,
release workflow, audit trail, and private workflow state out unless deliberately
generalized. Slice 1 now has the
pure engine functions for `cashflow_planning_bridge`, `cash_reserve_analysis`,
and `budget_pacing_projection`; Slice 2 exposes those through the existing
planning gateway/native MCP registry as public-safe wrappers over derived
monthly-close aggregates only. Future `pwplan-core` work should consume synthetic
or de-identified outputs from these tools and must still keep real ingestion,
household workflow, approvals, release state, and audit trails private.

**Assumptions provenance — done in current source (#198).** Built-in reference
assumptions now carry origin + freshness metadata: federal tax, IRMAA, education
vehicle, simplified state conversion/state-tax, and ACA reference factories expose
`source` plus `last_verified`, and report-facing outputs surface matching
`*Source` / `*LastVerified` fields next to their table-version stamps. Caller-
injected tables stay supported and are distinguished as `caller_provided`. This
is additive manifest metadata only; private report production, approvals, release
state, client context, and audit trails remain outside nexus-core.

**LP/indexer expansion and data quality — open issue #199.**

1. **Aerodrome Slipstream — full coverage via Envio.** The on-chain RPC path
   is **live** today: `GET /api/lp/aerodrome/{token_id}/analytics` reads Base
   Slipstream positions directly on-chain via Tatum RPC
   (`data/onchain/slipstream.py`: NFPM `positions` → CLFactory `getPool` →
   CLPool `slot0` → token `decimals`/`symbol`) and feeds the same pure
   `engine/lp/uniswap_v3.py`. It reports value, in-range, token amounts, and
   uncollected fees (`data_mode: onchain_rpc`). What's missing is what the
   on-chain-only path structurally cannot derive: impermanent loss (needs
   deposit history), fee APR (needs pool volume), and AERO gauge reward APR.
   No canonical Slipstream V3-schema subgraph exists on The Graph (the
   name-matching ones are Revert-automation and ICHI-vault subgraphs), so the
   full-coverage path is an **Envio** client (or a self-hosted subgraph); the
   pure engine + decode-compatible NFPM
   (`0x827922686190790b37229fd06084350E74485b72`) are already wired for it.
2. **Arbitrum Uniswap V3** — needs a correct V3-schema subgraph ID. The
   published one is incompatible, which is why Arbitrum is excluded from the
   multi-chain LP surface today.
3. **Base subgraph data quality** — the public Base V3 deployment carries
   spam-token TVL contamination. It pollutes vault discovery and pool-aggregate
   fee APR; per-position value/IL stays accurate. Fix is likely a self-hosted,
   cleaner indexer.
4. **Subgraph health-gate** — read each subgraph's `_meta` block-lag and mark
   responses `degraded` when an indexer falls behind, so stale data is visible
   rather than silent.
5. **Uniswap V4 (Unichain) via Envio** — extend LP coverage to V4's
   singleton-pool model; shares the Envio client work with item 1.
6. **Solana CLMM (Raydium / Orca)** — a Q64.64 sibling of the existing tick
   engine. The Jupiter price layer is already shipped, so this is the math +
   indexing half.
7. **Persisted LP-position PnL history** — snapshot LP positions over time the
   way benchmarks are already snapshotted daily, enabling historical PnL/IL
   series.

Crypto-options follow-ups — open issue #200 (the overwriting suite above is shipped; these deepen it):
put-side skew / risk-reversal (downside vol vs the call wing); coin-denominated
collar laddering; IV-rank/percentile context on the term structure; and an optional
config surface for the `regime_overlay` delta multipliers (the `defensiveness` knob
is the per-request version today). The pwdemo.com browser + chat surface that drives
these tools is built/iterated in the separate **pw-demo** repo, not here.

Agent/analytics capability ideas — open issue #201 (from the consumer-diagnostic roadmap):
equity options chain plumbing exists through MBOUM expirations/chains and the
local collar-book worksheet now accepts executable fill inputs, but IV-rank /
VRP / 25Δ skew, a full stock-screen-to-chain pipeline, `score_portfolio`
(sleeve-level aggregate of the 8-check), `defi_yields` / `defi_risk`, a
`resolve_symbol` resolver, and structured provenance/versioning
(`framework_version`) on score outputs remain future work.

**Equity-research vertical — open issue #203; full plan in [`docs/STOCK-RESEARCH-ENHANCEMENT.md`](docs/STOCK-RESEARCH-ENHANCEMENT.md).**
Today an MCP client can run a stock idea through the regime + EMF durability lens
(`current_regime` + `score_asset` + price), but nothing else — no fundamentals
statements, valuation, analyst consensus, forward estimates, real equity options
IV/skew (only crypto/Deribit has them), screener, ownership flows, or news. The
private PWOS import path can now stage advisor research screens, but public Nexus
should still expose only licensed/public-safe calculations unless data-rights
review clears a richer surface. The keys for it are already held (the rich
**MBOUM** surface is used for quotes/history and equity option
expirations/chains; **MarketStack** is a market quote/history fallback, not an
options-chain provider; **SEC EDGAR** is keyless). The plan
adds a sibling `ResearchDataProvider` protocol (modeled on `MacroDataProvider`) +
a keyed MBOUM impl + a keyless-EDGAR impl, a set of read-only research MCP tools +
REST routes, and a composite `stock_research_dossier` that fuses regime + score +
the new data — reusing the existing options engine (generalized
side/settlement-agnostic) rather than reimplementing it. (FMP/FinanceToolkit was
**retired** — MBOUM + MarketStack + EDGAR are the supported sources.) **Three gates
are load-bearing:** (A) MBOUM **data-redistribution rights** must be cleared
before any research data ships on the public surface; (B) the MBOUM research
endpoints are **unverified** — a live-key probe is task #0; (C) the CML-vs-EMF
**backtest harness** (a future `src/nexus_core/research/` subpackage behind a
`[research]` extra) is SEC-Marketing-Rule-regulated performance/comparison content
and needs a hard code-enforced off-the-public-surface boundary + CCO sign-off +
copyright review **before it is built**. The keyless wins (surfacing the
already-fetched EDGAR fundamentals; fixing ASAN Check 8's missing
market-cap/ROE/op-margin/rev-growth inputs) clear those gates on their own and come
first. The gate-free Claude Code connection + reference agent
([`examples/stock_research_agent.py`](examples/stock_research_agent.py)) ship today.

---

Apache-2.0 · USPTO #64/034,229 (defensive) · OIN member. New work preserves
the public-surface contract: read-only educational outputs, no public write
routes, no client data, no breaking changes to existing response shapes, and
optional service-key gating for production REST/JSON consumers.
