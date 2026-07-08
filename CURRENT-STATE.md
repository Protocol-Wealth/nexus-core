# Current state — nexus-core

A point-in-time snapshot of the local source/docs plus the most recent live
verification. For the architectural overview see [README.md](README.md); for
deploy mechanics see [DEPLOY.md](DEPLOY.md); for the public-surface audit see
[AUDIT.md](AUDIT.md).

- **Last docs closeout:** 2026-07-07 ET — root docs reconciled to the private
  consumer boundary: hosted native `/mcp` remains a public demo surface, hosted
  REST/JSON calculation paths are service-key gated, `pw-api` owns the
  server-to-server Nexus key, and PWOS/PWPortal browser clients should not hold
  Nexus credentials. Cross-repo PWOS market-research import PR #993 is merged
  and advisor-verified with `Saved 380 research rows (7c30414f)`; that raw
  CSV/XLSX ingestion remains private PWOS/pw-api data, not nexus-core data.
- **Last live verified:** 2026-07-06 ET / 2026-07-07 UTC — live `/health` OK;
  hosted REST/JSON planning paths require a Nexus API key; the pw-api service
  bearer key opened the then-current 27-tool planning contract; hosted native `/mcp` keeps
  transparent OAuth active and exposes only the demo MCP tools
  `option_price`, `collar_book`, `health`, and `describe`.
- **Last local update:** 2026-07-08 — current branch adds S12 healthcare / LTC
  stress support for `project_cash_flow` and `monte_carlo_decumulation`.
  `ltcShock` uses only de-identified numeric assumptions — onset age,
  current-dollar annual cost, duration, and healthcare-cost inflation. Cash flow
  rows expose base expenses and LTC shock expense when supplied; Monte Carlo
  emits a same-seed with/without-shock success-probability delta,
  self-insured probability, and terminal-value comparison. S12 v1 does not
  combine `ltcShock` with Guyton-Klinger guardrails; run those as separate
  scenarios. No diagnosis, provider, claim, policy, household identifier,
  approval, release, or audit state enters the public engine. `main` also adds S11
  `inherited_ira_analysis`: a public-safe inherited traditional IRA
  beneficiary strategy comparison for lump-sum, equal-annual, and
  bracket-smoothed 10-year-rule distributions. It uses only de-identified
  numeric assumptions, federal ordinary-income tax stacking, and
  eligible-designated-beneficiary carve-out notes; no beneficiary names, account
  identifiers, transaction rows, notes, approvals, release state, or audit
  records enter the public engine. `main` also adds S4
  `performance_analysis`: public-safe TWR, MWR/XIRR, fee-drag, and
  benchmark-relative return math over de-identified numeric series only. It
  accepts values, flows, fee rates, and return series; it does not accept
  symbols, holdings names, account labels, transaction rows, tax lots, notes,
  approvals, or audit workflow state. `main` also adds S5
  `risk_profile_score`: a fixed, PII-free questionnaire scorer that emits the
  optimizer-compatible `riskProfile` enum, annual volatility band, suggested
  weights, question/band metadata, and the canonical planning disclaimer.
  Advisor overrides, suitability approvals, and audit workflow state remain
  private. `main` also adds the S6 PW Wealth Roadmap preset to
  `build_planning_report`: `preset: "wealth_roadmap"` fixes the report title,
  supports `focused` / `full` scopes, injects the required scope statement and
  focused-scope planning-benefit notice, requires and stamps replay metadata on
  every section, and rejects public `released` / caller `curated` workflow state.
  `main` also adds the S9 household /
  survivor layer: `household_social_security_benefits` provides a simplified
  two-person Social Security own, age-reduced spousal, and survivor snapshot,
  and `income_layering` accepts optional spouse Social Security plus
  survivor-year transition inputs where `survivorYear` is the first
  survivor-only modeling / filing-status year. `main` also adds the S7
  illustrative state-tax layer: `tax_aware_withdrawal` and `income_layering`
  accept optional 2-letter
  `state` plus deterministic `residencyChange` inputs, expose federal/state tax
  splits and table versions when a reference rule is modeled, and keep unknown
  states explicitly unmodeled instead of assuming zero. `main` also adds the S3
  `historical_blend` planning tool: public proxy histories are
  converted to aligned monthly returns in the wrapper, while the pure engine
  emits calendar-year returns, trailing windows, growth-of-dollar, and annualized
  mean/sigma bands for Wealth Roadmap historical-context exhibits. `main` also
  adds S1 education funding, S8 deterministic/Monte Carlo goal-waterfall
  support, S2 income layering, report-grade Monte Carlo diagnostics for Wealth
  Roadmap consumers, the SECURE/SECURE 2.0 RMD start-age policy kernel,
  version-stamped federal tax/IRMAA reference tables, the Student-t Monte Carlo
  covariance-scaling correction, the 2026-07-05 Slice 0/1/2 cash-flow planning
  bridge work, collar-book executable-fill modeling, and the restricted
  REST/JSON access gate.
- **Repo:** [github.com/Protocol-Wealth/nexus-core](https://github.com/Protocol-Wealth/nexus-core) — public, Apache-2.0
- **Live:** [nexusmcp.site](https://nexusmcp.site) (Cloudflare → Cloud Run)
- **Version:** 0.1.0
- **Stack:** Python 3.12 · FastAPI · FastMCP · sync httpx · asyncpg · mypy `--strict` · ruff
- **Tests:** CI-gated test suite (`pytest`)
- **Posture:** read-only, no client data, transparent OAuth only for remote MCP
  handshakes, no public write endpoints. Hosted native `/mcp` is an
  OAuth-compatible open-source demo endpoint; `/api/*` and the planning JSON
  gateway are API-key gated with `NEXUS_ACCESS_MODE=restricted`.

## Hybrid planning boundary

For the PW Cash Flow OS + PW Planning Lab + PW Retirement Income Lab direction,
this repo remains the public-safe calculation engine. It may expose pure,
deterministic functions over de-identified planning inputs, derived
monthly-close values, pre-screened stock symbols, and caller-supplied option
facts. It must not ingest or store Monarch CSV exports, Seeking Alpha CSV/XLSX
workbooks, Schwab/custodian order or position files, raw import rows,
merchant/payee text, account nicknames, household/person identifiers,
advisor/client notes, document requests, approvals, release state, or compliance
audit trails. Private PWOS / pw-api / PWPortal owns those workflows and should
call Nexus only after de-identification and aggregation.

Slice 1 added the pure engine module
`src/nexus_core/engine/planning/cashflow_bridge.py` with
`cashflow_planning_bridge`, `cash_reserve_analysis`, and
`budget_pacing_projection`, exported from `nexus_core.engine.planning`. Slice 2
exposes those functions through the existing read-only planning gateway and
native MCP tool list. The wrappers accept only de-identified monthly-close
aggregates and do not ingest Monarch CSVs, raw transaction rows, merchant/payee
strings, account nicknames, household records, advisor/client notes, approvals,
release state, or audit trails.

## Local collar-book executable-fill update

Local source now supports a conservative execution worksheet for equity collar
books. Callers still supply pre-screened positions; Nexus does not pull live
chains, select trades, place orders, or make recommendations. When callers
provide midpoint `net_credit` plus either explicit `executable_net_credit` or
`call_bid` and `put_ask`, the collar-book output shows:

- per-position `stock_price`, `shares`, midpoint period/annual income, executable
  net credit, fill haircut, executable income, and executable annualized yield;
- book-level executable annual income/yield and annualized fill-haircut yield
  only when every held position has executable pricing; and
- `None` for book-level executable fields when at least one held position lacks
  executable pricing, avoiding a false mixed-denominator yield.

This is the realistic-fill layer for the PWOS screen-to-chain / collar
implementation workflow: bid-side call, ask-side put, still educational and
public-safe. It is not a live-chain attestation, custodian execution record,
client-specific recommendation, or order ticket. PWOS `/market-data` may import
and persist research-screen rows privately, then pass de-identified candidates
and chain-derived facts to Nexus for calculation.

## Public REST surface

Every REST endpoint is anonymous GET unless noted. The `/mcp` transport accepts
POST and may require a transparent OAuth bearer token when `MCP_OAUTH_SIGNING_KEY`
is configured; that flow has no user login and grants only public-scope access.
External integrations degrade gracefully — when a provider key is absent the
dependent endpoint returns `None` / empty / `503` rather than failing the service.

Restricted mode lets production consumers keep the public native MCP transport
as a low-risk demo while gating REST/JSON calculation paths. The hosted
deployment currently sets `NEXUS_PUBLIC_MCP_PROFILE=demo`, so OAuth MCP clients
see only `option_price`, `collar_book`, `health`, and `describe`. It also sets
`NEXUS_ACCESS_MODE=restricted` plus `NEXUS_API_KEYS`, requiring
`Authorization: Bearer <key>` or `X-Nexus-Api-Key` on `/api/*`,
`/api/planning/tools/*`, and legacy `/mcp/tools/*`. `pw-api` supplies the
matching `NEXUS_SERVICE_API_KEY`; browser apps should call PWOS/PWPortal BFF
routes rather than carrying Nexus credentials. CORS origin allow-lists remain a
browser control, not an authentication boundary.

### Meta

| Endpoint | Data source | Required key |
|----------|-------------|--------------|
| `GET /` | — (landing page) | — |
| `GET /health` | — (liveness probe) | — |
| `GET /health/db` | Cloud SQL connectivity probe | `DATABASE_URL` |
| `GET /api/usage` | in-process cache + provider usage report | — |
| `GET /docs` · `GET /openapi.json` | OpenAPI (servers block + per-tag descriptions) | — |
| `GET /mcp-guide` | MCP client setup guide (hosted + local) | — |
| `GET /llms.txt` | agent site map (llmstxt.org) | — |
| `GET /.well-known/security.txt` | RFC 9116 disclosure pointer → security@protocolwealthllc.com | — |
| `GET /.well-known/ai-disclosure.json` | machine-readable AI disclosure card | — |
| `GET /.well-known/oauth-protected-resource[/mcp]`, `GET /.well-known/oauth-authorization-server`, `POST /register`, `GET /authorize`, `POST /token` | transparent OAuth 2.1 / PKCE metadata and token flow for remote MCP clients | `MCP_OAUTH_SIGNING_KEY` enables issuing tokens |

### Regime & scoring

| Endpoint | Data source | Required key |
|----------|-------------|--------------|
| `GET /api/regime` | RegimeEngine — core: Gold/SPX vs 200WMA, real rates, DXY, VIX, credit spreads (BBB OAS); supplementary: yield curve, precious metals | `FRED_API_KEY` for macro precision |
| `GET /api/regime/signals` | RegimeEngine — raw per-signal readings | `FRED_API_KEY` for macro precision |
| `GET /api/score/{ticker}` | EMF 8-check scoring on SEC EDGAR XBRL fundamentals; supports `ScoreExplanation` + `as_of` deterministic replay | — (EDGAR is keyless) |

### Market & economic data

| Endpoint | Data source | Required key |
|----------|-------------|--------------|
| `GET /api/market/quote/{symbol}` | composite: yfinance / MBOUM / MarketStack / CoinGecko | keyless works; keys raise limits / add fallbacks |
| `GET /api/market/history/{symbol}` | composite (same providers) — OHLCV bars | keyless works; keys raise limits / add fallbacks |
| `GET /api/economic/{series_id}` | FRED | `FRED_API_KEY` |

### Options (educational overlays)

| Endpoint | Data source | Required key |
|----------|-------------|--------------|
| `GET /api/options/price` | Black-Scholes pricer + Greeks | — |
| `GET /api/options/overlay/covered-call` | Black-Scholes overlay illustration | — |
| `GET /api/options/overlay/cash-secured-put` | Black-Scholes overlay illustration | — |
| `GET /api/options/overlay/collar` | Black-Scholes overlay illustration | — |
| `POST /api/options/overlay/collar-screen` | batch equity collar screen; theoretical premiums | market-data key optional |
| `POST /api/options/overlay/collar-book` | advisor research worksheet; optional executable-fill haircut from call bid / put ask | — |
| `GET /api/options/equity/{symbol}/expirations` | MBOUM listed equity option expirations | `MBOUM_API_KEY` |
| `GET /api/options/equity/{symbol}/chain?expiration=` | MBOUM normalized single-expiration option chain | `MBOUM_API_KEY` |
| `GET /api/options/crypto/currencies` | Deribit — supported underliers + settlement model | — |
| `GET /api/options/crypto/{currency}/instruments` | Deribit — BTC/ETH (inverse) + SOL/XRP/TRX/AVAX (USDC-linear) | — |
| `GET /api/options/crypto/instrument/{instrument_name}` | Deribit | — |

Crypto option underliers: **BTC, ETH** are coin-settled (inverse, queried as `currency=BTC|ETH`);
**SOL, XRP, TRX, AVAX** are USDC-settled (linear) and listed under Deribit's `USDC` umbrella as
`<CODE>_USDC-…` — the client queries the umbrella and filters by instrument-name prefix. Keyless.

### On-chain & DeFi

| Endpoint | Data source | Required key |
|----------|-------------|--------------|
| `GET /api/wallet/{address}` | DeBank — anonymous EVM wallet balance | `DEBANK_API_KEY` |
| `GET /api/chain/chains` | Tatum — supported chains | — |
| `GET /api/chain/balance/{chain}/{address}` | Tatum — EVM `eth_getBalance` / Solana `getBalance` | `TATUM_API_KEY` |
| `GET /api/chain/native/{address}` | Tatum — native balances | `TATUM_API_KEY` |
| `GET /api/vaults` | vaults.fyi v2 — vault discovery | `VAULTSFYI_API_KEY` |
| `GET /api/vaults/chains` | vaults.fyi v2 — chains with vault data | `VAULTSFYI_API_KEY` |
| `GET /api/lp/chains` | — chains/versions with LP analytics | — |
| `GET /api/lp/uniswap-v3/{chain}/positions?owner=` | The Graph — positions owned by a public EVM address | `THEGRAPH_API_KEY`; token units only, no USD valuation |
| `GET /api/lp/uniswap-v3/{chain}/{token_id}/analytics` | The Graph + RPC (Tatum) + Merkl | `THEGRAPH_API_KEY`, `TATUM_API_KEY` (uncollected fees); USD prices are required query params |
| `GET /api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark` | same + hold-strategy benchmark returns over a window | `THEGRAPH_API_KEY`, `TATUM_API_KEY`; USD prices are required query params |
| `GET /api/lp/aerodrome/{token_id}/analytics` | Aerodrome Slipstream on **Base**, read on-chain via Tatum RPC (no subgraph) | `TATUM_API_KEY`; USD prices required. `data_mode: onchain_rpc` — value/in-range/amounts/uncollected fees only; IL, fee APR, AERO gauge APR null/zero |

Uniswap V3 analytics computes value, in-range status, **exact** impermanent-loss-vs-HODL,
fee-APR estimate, uncollected fees (RPC `tokensOwed`), and Merkl reward APR → total APR.
LP coverage spans **ethereum, base, optimism, polygon** (Arbitrum's published subgraph
ID uses an incompatible schema → unsupported). `vs-benchmark` adds hold-strategy
benchmark returns over the position window. The CLMM math in `engine/lp/uniswap_v3.py`
is pure and protocol-agnostic — reused across all chains.

Aerodrome Slipstream (a Uniswap-V3 CLMM sibling) is read directly on-chain on Base via
Tatum RPC — no Slipstream subgraph exists on The Graph, so `data/onchain/slipstream.py`
walks NFPM `positions` → CLFactory `getPool` → CLPool `slot0` → token `decimals`/`symbol`
and feeds the same engine. It reports value, in-range, token amounts, and uncollected
fees (`data_mode: onchain_rpc`); IL, fee APR, and AERO gauge reward APR need an indexer
(Envio) and are reported null/zero.

### Solana prices

| Endpoint | Data source | Required key |
|----------|-------------|--------------|
| `GET /api/solana/price/{mint}` | Jupiter v3 — single SPL token USD price | — (keyless) |
| `GET /api/solana/prices?mints=` | Jupiter v3 — batch SPL token USD prices | — (keyless) |

### Benchmarks

| Endpoint | Data source | Required key |
|----------|-------------|--------------|
| `GET /api/benchmarks` | base-100 hold-strategy composition definitions | — |
| `GET /api/benchmarks/series?days=` | CoinGecko — on-demand base-100 returns | `COINGECKO_API_KEY` raises limits |
| `GET /api/benchmarks/history?days=` | persisted daily snapshots (Cloud SQL) | `DATABASE_URL` (`503` when unset) |

Compositions are buy-and-hold, base-100: BTC / ETH / SOL singles; ETH-USDC 50/50,
60/40, 70/30; ETH-BTC 50/50. USDC is held at $1.

### MCP

| Endpoint | Data source | Required key |
|----------|-------------|--------------|
| `POST /mcp` | FastMCP-over-HTTP transport (also `nexus-core mcp` over stdio) | — |
| `GET /api/planning/tools` | planning contract handshake — `{contractVersion, tools[]}` | optional `NEXUS_API_KEYS` in restricted mode |
| `POST /api/planning/tools/{tool_id}` | planning gateway — invoke a planning tool (JSON in/out, PII-free) | optional `NEXUS_API_KEYS` in restricted mode |
| `GET /mcp/tools`, `POST /mcp/tools/{tool_id}` | legacy planning gateway aliases | optional `NEXUS_API_KEYS` in restricted mode |

**MCP tool surface** (in `tools/list`, identical over HTTP + stdio; every tool is
read-only with `readOnlyHint` + the educational disclaimer):

- **Regime** — `current_regime`, `regime_signals`
- **Scoring** — `score_asset` (EMF 8-check; emits `NOT APPLICABLE` + `tier_note` on insufficient coverage)
- **Market** — `get_quote`, `get_quotes` (batch), `get_price_history` (carry `as_of` / `source` / `market_status`)
- **Economic** — `get_economic_series` (carries `as_of` observation date + `source`)
- **Options** — `option_price`, `covered_call`, `cash_secured_put`, `collar`,
  `equity_collar_screen`, `collar_book` (advisor worksheet with optional
  executable-fill haircut), `equity_option_expirations`, `equity_option_chain`
- **Crypto options** — `crypto_option_instruments`, `crypto_option_ticker`,
  `crypto_covered_call` (settlement-aware overwrite), `crypto_covered_call_chain`
  (rank OTM calls by yield), `crypto_protective_put`, `crypto_collar`,
  `crypto_regime_overwrite` (strike tilted by the live EMF regime + a tunable
  `defensiveness` knob), `crypto_iv_term_structure` (near-ATM IV by tenor),
  `crypto_vol_skew` (call-side IV + vega by strike), plus
  the structured `crypto_covered_call_ladder` / `crypto_option_roll` /
  `crypto_options_book_mtm` / `crypto_options_scenario`. Full overwriting + hedge
  suite is on BOTH the REST surface (`/api/options/crypto/{currency}/...`) and MCP.
- **DeFi** — `defi_protocols`, `defi_protocol`, `defi_chains`
- **Planning** (34 in current source; live deployment can lag source) — `monte_carlo_decumulation`, `solve_goal`, `analyze_goals`, `project_cash_flow`, `cashflow_planning_bridge`, `cash_reserve_analysis`, `budget_pacing_projection`, `education_funding`, `education_vehicle_rules`, `income_layering`, `glide_path`, `tax_aware_withdrawal`, `correlation_matrix`, `capital_market_assumptions`, `historical_blend`, `regime_return_generator`, `roth_conversion`, `sequence_of_returns_stress`, `rmd`, `tax_bracket_headroom`, `inherited_ira_analysis`, `social_security_claiming`, `regime_conditioned_swr`, `portfolio_xray`, `optimize_allocation`, `risk_profile_score`, `fire`, `risk_metrics`, `performance_analysis`, `rebalance`, `irmaa_headroom`, `analyze_roth_conversion`, `sequence_conversions`, `build_planning_report`
- **Meta** — `health` (per-upstream status), `describe` (catalog + symbology + contract version)

All 34 current-source planning tools are served both natively through MCP and via
the REST/JSON gateway (`POST /api/planning/tools/{id}`) for browser/server
callers — same handlers, contractVersion `0.1.0`. Legacy `/mcp/tools/{id}`
aliases remain. The composite Roth/IRMAA case contract is
`PLANNING_CONTRACT_VERSION = 1.1.0`; the gateway envelope remains `0.1.0`.

## Code layout

| Area | Modules |
|------|---------|
| Data — onchain | `data/onchain/{debank,tatum,thegraph,merkl,vaultsfyi,defillama,jupiter}.py` |
| Data — market | `data/market/{coingecko,mboum,marketstack,yfinance}_provider` + cache + composite |
| Data — macro | `data/macro` (FRED) |
| Data — fundamentals | `data/edgar` (SEC) |
| Data — derivatives | `data/derivatives` (Deribit) |
| Data — persistence | `data/db.py` + `data/snapshots.py` (asyncpg) |
| Engine | `engine/regime` (RegimeEngine), `engine/scoring/emf` (8-check) + `engine/scoring/framework` (`ScoreExplanation` / `as_of` replay), `engine/pricing` (Black-Scholes), `engine/lp/uniswap_v3.py` (CLMM tick math, `get_amounts_for_liquidity`, exact IL, fee APR), `engine/benchmarks.py` (base-100 + buy-and-hold) |
| Jobs | `jobs/daily_snapshot.py` |
| CLI | `nexus-core {serve \| mcp \| snapshot}` |

## Persistence & snapshot pipeline

- **Cloud SQL `nexus-marketdata`** — POSTGRES_16, **private-IP-only** on
  `pwllc-prod-vpc`, backups + deletion protection enabled. Holds the daily
  benchmark snapshots that back `/api/benchmarks/history`.
- **Web service → DB** via Direct VPC egress
  (`--network=pwllc-prod-vpc --subnet=pwllc-prod-cloud-run-us-central1
  --vpc-egress=private-ranges-only`) plus `--add-cloudsql-instances` and the
  runtime SA's `roles/cloudsql.client`.
- **Daily benchmark snapshot** is written by **Cloud Run Job `nexus-snapshot-job`**
  (runs `nexus-core snapshot`), triggered by **Cloud Scheduler
  `nexus-daily-snapshot`** at **01:00 America/New_York** daily, using an OAuth
  service-account identity (no shared secret). It is a Job, **not an HTTP route** —
  there is no public write endpoint.

## Infrastructure

| Resource | Identity / detail |
|----------|-------------------|
| Cloud Run service | `nexus-core` — region `us-central1`, `--allow-unauthenticated`, Direct VPC egress, `--add-cloudsql-instances`, provider keys + `DATABASE_URL` via `--set-secrets` |
| Cloud Run Job | `nexus-snapshot-job` — `--command nexus-core --args snapshot`, `--set-cloudsql-instances` (note: not `--add-`), Direct VPC egress, `DATABASE_URL` + `COINGECKO_API_KEY` |
| Cloud Scheduler | `nexus-daily-snapshot` — HTTP trigger, `--oauth-service-account-email` (not a static token), daily 01:00 ET |
| Cloud SQL | `nexus-marketdata` — POSTGRES_16, private IP only, on `pwllc-prod-vpc` |
| Runtime SA | `nexus-core-run@pwllc-prod` |

### Secrets (Google Secret Manager)

`nexus-fred-api-key`, `nexus-mboum-api-key`, `nexus-marketstack-api-key`,
`nexus-coingecko-api-key`, `nexus-eia-api-key`, `nexus-bea-api-key`,
`nexus-debank-api-key`, `nexus-tatum-api-key`, `nexus-vaultsfyi-api-key`,
`nexus-thegraph-api-key`, `nexus-marketdata-database-url`, plus the deployment's
`MCP_OAUTH_SIGNING_KEY` secret when transparent MCP OAuth is enabled.

### Environment variables

| Variable | Effect |
|----------|--------|
| `FRED_API_KEY` | `/api/economic/*` + macro precision for `/api/regime` |
| `MBOUM_API_KEY` | MBOUM market-data fallback |
| `MARKETSTACK_API_KEY` | MarketStack market-data fallback |
| `COINGECKO_API_KEY` | Raises CoinGecko limits (keyless works) |
| `EIA_API_KEY` | EIA energy data |
| `BEA_API_KEY` | BEA economic data |
| `DEBANK_API_KEY` | `/api/wallet` |
| `TATUM_API_KEY` | `/api/chain` + LP uncollected fees |
| `VAULTSFYI_API_KEY` | `/api/vaults` |
| `THEGRAPH_API_KEY` | `/api/lp` |
| `DATABASE_URL` | persistence + `/api/benchmarks/history` (`503` when unset) |
| `MCP_OAUTH_SIGNING_KEY` | stateless transparent OAuth for remote `/mcp`; omit locally to keep `/mcp` open |
| `NEXUS_PUBLIC_MCP_PROFILE` | `full` (default) or `demo`; demo limits native `/mcp` to closed-world demo tools |
| `NEXUS_ACCESS_MODE` | `public` (default) or `restricted`; restricted mode gates `/api/*` and planning JSON gateway paths |
| `NEXUS_API_KEYS` | comma-separated raw service keys or `sha256:<hex>` digests |
| `NEXUS_RATE_LIMIT_PER_MIN` | per-IP request budget (default `60`) |
| `NEXUS_CORS_ORIGINS` | CORS allow-list |

Every external integration degrades gracefully to `None` / empty / `503` when its
key is absent.

## Security posture

- Public, read-only. **No public write endpoints** — the daily snapshot runs as a
  Cloud Run Job, not an HTTP route.
- Cloud SQL is private-IP-only; reached over Direct VPC egress with a service-account
  identity. No credentials in config — secrets live only in Secret Manager.
- In-process rate limiter resolves the client IP spoofing-resistantly
  (`CF-Connecting-IP`, else rightmost `X-Forwarded-For`).
- Transparent MCP OAuth uses stateless HMAC-signed client ids, authorization
  codes, and bearer/refresh tokens when `MCP_OAUTH_SIGNING_KEY` is set. It exists
  for remote MCP client compatibility, not user authentication.
- Cloudflare methods rule blocks non-`GET`/`POST`/`OPTIONS`; edge rate-limit on the
  cost endpoints.
- No client data, no PII at risk.
- **Disclaimers** — one canonical `disclaimers.py` (educational / not advice / AI / as-is)
  on every MCP tool, REST route, web page, and the OpenAPI description.
- **Security headers** (`security_headers.py`, outermost) — `nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy` on every response; CSP on HTML only.
  Errors are masked (`mask_error_details=True`) so no `str(e)` leaks to the wire.
- **CI** gates `ruff` + `mypy --strict` + `pytest` (80% floor) on every push/PR.

## Recent work

- **Docs/status reconciliation (2026-07-01)** — verified live `/health`, `/mcp/tools`,
  OpenAPI, OAuth metadata, `/llms.txt`, GitHub issues, and local `main`; reconciled
  docs around 23 planning tools, public PII-free planning, transparent MCP OAuth,
  and open GitHub issue tracking (#197-#203).
- **Cash-flow planning bridge engine functions (2026-07-05)** —
  `cashflow_planning_bridge`, `cash_reserve_analysis`, and
  `budget_pacing_projection` exist as pure, deterministic `engine/planning`
  functions and are exposed through the existing planning gateway/native MCP
  registry as read-only public-safe tools. They consume de-identified
  monthly-close aggregates only; production ingestion and workflow remain private
  PWOS/pw-api/PWPortal responsibilities.
- **Collar-book executable-fill modeling (2026-07-06)** — local source now
  reports stock price, share count, bid/ask fill haircut, executable income, and
  executable annualized yield for pre-screened collar-book candidates when the
  caller supplies executable pricing. REST and MCP parsers accept the same
  optional fields; the output remains a public-safe advisor research worksheet.
- **Guyton-Klinger dynamic withdrawals** — `monte_carlo_decumulation` accepts
  optional `guardrails` and returns `withdrawalRule`, `spendingByYear`,
  `guardrailActivity`, and report-oriented `guardrailStats` only when enabled.
- **S8 deterministic waterfall state** — `project_cash_flow` remains
  single-bucket by default. When callers pass `accountBalances`, the engine
  returns per-year `accountBalances`, `withdrawalsByAccount`, `ordinaryTaxes`,
  and `earlyWithdrawalPenalty`; deficits draw taxable → traditional → Roth and
  surplus saves to taxable. Traditional withdrawals are ordinary-taxable; Roth
  draws are not ordinary income in multi-account mode. `monte_carlo_decumulation`
  and `solve_goal` can also accept de-identified `goals`, echo the generated
  `goalFundingSchedule`, and return per-goal path-level funding statistics.
- **S7 state/local tax state** — `engine/planning/state_tax.py` provides a
  data-driven 2026 reference table for no-income-tax states, full retirement
  exclusion states (PA/IL/MS/IA), and selected partial/senior exclusion states
  (CO/NY/VA/NJ/MD/DE). `tax_aware_withdrawal` and `income_layering` accept only
  state codes, ages, filing status, and numeric income components; they return
  optional federal/state tax splits and table versions. The Roth composite's
  older `StateConversionRule` reference set is aligned for the S7 no-income and
  full-retirement-exclusion states it can represent. Raw addresses, account
  identifiers, household records, approvals, and audit state stay outside the
  public engine.
- **S9 household/survivor state** — `social_security.py` exports
  `household_social_security_benefits` for simplified two-person Social Security
  own, age-reduced spousal, and survivor benefit snapshots. `income_layering`
  accepts optional `spouseSocialSecurity`, `survivorYear`, and
  `survivorFilingStatus`, treats `survivorYear` as the first survivor-only
  modeling / filing-status year, and models survivor Social Security as the
  larger claimed benefit after that year. Inputs
  remain ages, claim ages, PIAs, filing statuses, and numeric assumptions only;
  names, household identifiers, permissions, approvals, and audit records stay
  private-stack concerns.
- **S6 Wealth Roadmap state** — `build_planning_report` now supports the
  additive `preset: "wealth_roadmap"` request shape. The focused scope includes
  snapshot, trajectory, one goals section, and the required scope / assumptions /
  disclosure section. The full scope includes snapshot, trajectory, goals,
  income, guardrails, historical blend, required scope / assumptions /
  disclosures, and priority actions. Every Roadmap section carries the same
  replay metadata (`assumptionVersion`, `cmaVersion`, `taxYear`, `seed`,
  `engineReference`, `scope`). Full-scope priority actions are candidate
  observations with `curated: false`; the public engine rejects `released` and
  caller-provided `curated` workflow state. Rendering, approval, archiving,
  client delivery, and books-and-records workflows remain private-stack
  concerns.
- **S5 risk-profile scoring state** — `risk_profile_score` scores the fixed
  PII-free questionnaire into the optimizer-compatible `riskProfile` enum,
  annual volatility band, suggested model weights, question/band metadata, and
  the canonical planning disclaimer. Advisor overrides, suitability approvals,
  and audit workflow state remain private-stack concerns.
- **S4 performance-analysis state** — `performance_analysis` computes
  time-weighted returns, money-weighted returns / XIRR, fee drag, and
  benchmark-relative return deltas from numeric series only. It stays PII-free
  and does not ingest symbols, holdings names, account identifiers, transaction
  rows, tax lots, approvals, or audit records.
- **S11 inherited IRA state** — `inherited_ira_analysis` compares lump-sum,
  equal-annual, and bracket-smoothed inherited traditional IRA distribution
  strategies under a 10-year frame. It stacks taxable inherited distributions
  on beneficiary ordinary income using the injected 2026 federal ordinary-tax
  table, ranks strategies by net after-tax receipts, and returns an
  eligible-designated-beneficiary carve-out table. The result explicitly states
  that v1 is a strategy comparison, not a separate beneficiary life-expectancy
  annual RMD compliance calculator. Inputs remain numeric and de-identified
  only; spousal rollover elections, trust/estate-specific rules, state tax, and
  books-and-records workflows stay private / future scope.
- **S12 healthcare / LTC stress state** — `project_cash_flow` and
  `monte_carlo_decumulation` accept optional `ltcShock` plus
  `healthcareInflationRate`. `ltcShock` is a de-identified event:
  `{onsetAge, annualCost, durationYears, costInflation?}` where `annualCost` is
  stated in current-year dollars and inflated into each active shock year.
  Deterministic cash-flow rows expose `baseExpenses` and `ltcShockExpense` only
  when a shock is supplied; Monte Carlo reports a same-seed with/without-shock
  impact block. S12 v1 rejects `ltcShock` + Guyton-Klinger guardrails together;
  run those as separate scenarios. Diagnosis, claims, provider names,
  insurance-policy data, client delivery, and books-and-records workflow stay
  private / future scope.
- **Planning surface now 34 tools in current source** — includes `solve_goal`,
  `analyze_goals`, `project_cash_flow`, the cash-flow bridge trio,
  `education_funding`, `education_vehicle_rules`, `income_layering`,
  `historical_blend`, `inherited_ira_analysis`, `optimize_allocation`,
  `risk_profile_score`, `performance_analysis`, `build_planning_report`, and the composite
  Roth/IRMAA trio.
- **Uniswap V3 owned-position enumeration** — `GET /api/lp/uniswap-v3/{chain}/positions?owner=`
  lists open positions before USD valuation.
- **Research-data cleanup** — FMP/FinanceToolkit path removed; supported future
  research sources are MBOUM, MarketStack, and keyless SEC EDGAR.

## Next (roadmap)

Outstanding and future work is tracked in GitHub Issues:

- **#197 public-safe planning/report analytics extraction** — decide what generic,
  PII-free analytics should move from private PWOS producer work into nexus-core
  versus staying in advisor workflow code. This now includes the Cash Flow OS /
  Planning Bridge question: the Slice 1 pure engine functions consume derived
  monthly-close values only. Wrapper exposure, if accepted, is future Slice 2.
- **#198 planning assumptions provenance** — add source/freshness metadata to
  reference planning assumptions and echo it in outputs.
- **#199 LP/indexer expansion and data-quality backlog** — Aerodrome Envio,
  Arbitrum V3 subgraph, Base data quality, subgraph health-gate, Uniswap V4,
  Solana CLMM, persisted LP PnL, and Solana USD enrichment.
- **#200 crypto-options follow-ups** — put-side skew/risk reversal, collar
  laddering, IV-rank context, and regime-overlay config.
- **#201 agent analytics backlog** — equity options IV, `score_portfolio`,
  `defi_yields`/`defi_risk`, `resolve_symbol`, and score provenance/versioning.
- **#202 governance/tooling cleanup** — EMF canonical numbering, display-only
  regime signal decision, and possible `ruff format` gate.
- **#203 equity-research vertical gates** — MBOUM live-key probe, redistribution
  rights, public-safe research provider/tools, and backtest compliance boundary.
