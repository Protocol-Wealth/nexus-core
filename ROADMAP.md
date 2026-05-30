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
`httpx` · `asyncpg` · `mypy --strict` · `ruff`. 580-test suite. Public,
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

### Options (educational overlays)

- **`GET /api/options/price`** — Black-Scholes pricing (`engine/pricing`).
- **`GET /api/options/overlay/{covered-call,cash-secured-put,collar}`** —
  educational overlay structures.
- **`GET /api/options/crypto/{currency}/instruments`,
  `/api/options/crypto/instrument/{instrument_name}`** — Deribit crypto
  options (`data/derivatives`).

### Onchain & DeFi

- **`GET /api/wallet/{address}`** — anonymous EVM wallet balance (DeBank).
- **`GET /api/chain/chains`, `/api/chain/balance/{chain}/{address}`,
  `/api/chain/native/{address}`** — multi-chain native balances via Tatum
  (EVM `eth_getBalance` + Solana `getBalance`).
- **`GET /api/vaults`, `/api/vaults/chains`** — DeFi vault discovery
  (vaults.fyi v2).
- **`GET /api/lp/chains`, `/api/lp/uniswap-v3/{chain}/{token_id}/analytics`** —
  Uniswap V3 position analytics: value, in-range status, **exact**
  impermanent-loss-vs-HODL, fee-APR estimate, uncollected fees (RPC
  `tokensOwed` via Tatum), and Merkl reward APR rolled into total APR. Pure
  CLMM math in `engine/lp/uniswap_v3.py` (tick math,
  `get_amounts_for_liquidity`, exact IL). USD prices are required query
  params. (The Graph + RPC + Merkl.)

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
- **`POST /mcp`** — MCP-over-HTTP transport (FastMCP) exposing the above as
  tools to any MCP client.
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

## In progress

- **#64 — snapshot Cloud Run Job** and **#65 — spoofing-resistant rate
  limiter** may still be open PRs at read time. Production already runs both,
  so the capabilities above are described as present.

## Next

Prioritized. Top item first.

1. **Position-PnL-vs-benchmark surface** — pair LP impermanent-loss with the
   hold benchmarks to answer "was LPing worth it?" The two halves (exact IL in
   `engine/lp`, base-100 holds in `engine/benchmarks`) already exist; this
   joins them into one comparison.
2. **Jupiter Solana price source** — add a Solana price feed so Solana AMM /
   LP coverage isn't gated on EVM-centric price inputs.
3. **More LP adapters** — Uniswap V4, plus Aerodrome / Balancer / Algebra,
   extending the Uniswap-V3-only analytics surface.
4. **Persisted LP-position snapshots** — track LP positions over time the way
   benchmarks are already snapshotted daily, enabling historical PnL/IL series.

---

Apache-2.0 · USPTO #64/034,229 (defensive) · OIN member. New work preserves
the public-surface contract: no auth added to read endpoints, no public write
routes, no client data, no breaking changes to existing response shapes.
