# Roadmap

Where Nexus Core is, what's landing now, and what's next. This is the
deployable public surface — the read-only REST API + MCP transport that runs
at [nexusmcp.site](https://nexusmcp.site) — not the full `nexus_core` library
(optimization, risk, pricing, EDGAR, AI). For the library capabilities see the
[README](README.md); for what the deployment exposes and excludes see
[AUDIT.md](AUDIT.md).

Honest by design: "Done" means it runs in production today. No dates, no
guarantees, no marketing.

## Done

The current production surface. Python 3.12 · FastAPI · FastMCP · sync
`httpx` · `asyncpg` · `mypy --strict` · `ruff`. CI-gated test suite. Public,
read-only, no auth, no client data. Every external integration degrades
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

- **`GET /api/wallet/{address}`** — anonymous EVM wallet balance (DeBank).
- **`GET /api/chain/chains`, `/api/chain/balance/{chain}/{address}`,
  `/api/chain/native/{address}`** — multi-chain native balances via Tatum
  (EVM `eth_getBalance` + Solana `getBalance`).
- **`GET /api/vaults`, `/api/vaults/chains`** — DeFi vault discovery
  (vaults.fyi v2).
- **`GET /api/lp/chains`, `/api/lp/uniswap-v3/{chain}/{token_id}/analytics`,
  `/api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark`** — Uniswap V3 position
  analytics across **ethereum, base, optimism, polygon**: value, in-range
  status, **exact** impermanent-loss-vs-HODL, fee-APR estimate, uncollected
  fees (RPC `tokensOwed` via Tatum), and Merkl reward APR rolled into total
  APR. `vs-benchmark` adds hold-strategy benchmark returns over a window —
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
  and the 16 planning tools. `GET /mcp/tools` + `POST /mcp/tools/{id}` are the
  REST planning gateway (contractVersion `0.1.0`) for the pwplan-core shell. (The
  3 composite Roth/IRMAA tools — `analyze_roth_conversion`, `sequence_conversions`,
  `irmaa_headroom`, PlanningContract v1.0.0 — are merged to main + share this path,
  but are not in the live deployment yet; see Next.)
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
- **Data provenance** — quotes/FRED carry `as_of` / `source` / `market_status`.
- **Regime signals** — `breadth` (% sectors > 200DMA) + `precious_metals_signal`.
- **Agent/discovery** — `/llms.txt`, `AGENTS.md`, `/.well-known/security.txt`,
  security-headers middleware, OpenAPI servers/tags.
- **EMF coverage** — ASAN fail-safe + 5 sector buckets; Perez capex-light path;
  crypto/ETF durability-layer router (aligned with `SHARED/strategy/emf-canonical.md`).

## Next

Prioritized. Top item first.

**Composite Roth/IRMAA planning tools — LIVE** (`analyze_roth_conversion`,
`sequence_conversions`, `irmaa_headroom`, PlanningContract v1.0.0) on `nexusmcp.site`
since rev `nexus-core-00047` (2026-06-03), verified by a production POST. v2 follow-ons
(in value order): model the **ACA premium-tax-credit cliff** (today only *flagged* in the
year notes — the common pre-65 case), **employer-plan (401k/403b) balances**, and explicit
**survivor-year filing transitions** (the documented v1 exclusions in
`engine/planning/case.py`). The ACA cliff needs case-specific inputs (marketplace
enrollment, household size/FPL, benchmark premium) — additive optional contract fields
(a v1.1.0 minor bump) or a caller-injected `aca_rule`; decide before building.

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

Crypto-options follow-ups (the overwriting suite above is shipped; these deepen it):
put-side skew / risk-reversal (downside vol vs the call wing); coin-denominated
collar laddering; IV-rank/percentile context on the term structure; and an optional
config surface for the `regime_overlay` delta multipliers (the `defensiveness` knob
is the per-request version today). The pwdemo.com browser + chat surface that drives
these tools is built/iterated in the separate **pw-demo** repo, not here.

Agent/analytics capability ideas (from the consumer-diagnostic roadmap, not yet built):
real *equity* options chains + IV (Tradier) and IV-rank to replace the theoretical σ
(crypto already uses live Deribit IV); `score_portfolio` (sleeve-level aggregate of
the 8-check); `defi_yields` / `defi_risk`; a `resolve_symbol` resolver; and structured
provenance/versioning (`framework_version`) on score outputs for Rule 17a-4 reproducibility.

---

Apache-2.0 · USPTO #64/034,229 (defensive) · OIN member. New work preserves
the public-surface contract: no auth added to read endpoints, no public write
routes, no client data, no breaking changes to existing response shapes.
