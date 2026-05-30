# Nexus Core Architecture

Nexus Core is a public, read-only, regime-adaptive financial-analysis and
DeFi/market-data engine. Python 3.12, FastAPI + FastMCP, synchronous `httpx`,
`asyncpg`. It carries no client data and no authentication — every endpoint is
public and read-only.

## Layering

Data flows in one direction: data clients fetch from external providers, the
engine computes over that data, and the app layer exposes the results as REST
and MCP.

```
External providers (FRED, SEC EDGAR, CoinGecko, MBOUM, MarketStack, yfinance,
                    DeBank, Tatum, The Graph, Merkl, vaults.fyi, DefiLlama,
                    Jupiter, Deribit)
    │
    ▼
data/            provider adapters (sync httpx)
  market/        coingecko, mboum, marketstack, yfinance + cache + composite
  macro/         fred, treasury, eia, bea
  edgar/         SEC fundamentals (edgartools wrapper)
  onchain/       debank, tatum, thegraph, merkl, vaultsfyi, defillama, jupiter
  derivatives/   deribit (crypto options)
  db.py          asyncpg seam to the private market-data Postgres
  snapshots.py   daily benchmark-price persistence
    │
    ▼
engine/          pure computation over provider data
  regime/        RegimeEngine — signal ensemble → regime classification
  scoring/       8-check EMF scoring (emf/ holds croic, fscore, hurst, …)
  pricing/       Black-Scholes + options overlays
  lp/            uniswap_v3 — pure CLMM math (tick math, exact IL, fee APR),
                 protocol-agnostic and reused across chains
  benchmarks.py  base-100 hold-strategy return series + compositions
    │
    ▼
app/             FastAPI application factory + routers
  main.py        create_app() — wires providers, engine, routers, middleware
  routes.py      regime, market, economic
  scoring.py     /api/score (shares context builder with MCP score_asset)
  options.py     options pricing + overlays + Deribit crypto options
  wallet.py chain.py vaults.py lp.py benchmarks.py snapshots.py
  ratelimit.py   in-process per-IP sliding-window limiter
  mcp_mount.py   mounts the FastMCP transport at /mcp
mcp/server/      build_server() — the MCP tool surface (regime, score, market,
                 economic, DefiLlama TVL, options); ships no auth of its own
```

The market provider is assembled as a cached composite: yfinance (keyless
default), then MBOUM and MarketStack (keyed, quota-tracked), then CoinGecko, all
behind a TTL cache. A keyed provider with no configured key short-circuits to a
miss without issuing a request. Every external integration degrades gracefully
to `None`/empty/`503` when its key is absent, so the same image runs unchanged
locally and in production.

REST handlers are synchronous `def` — FastAPI runs them in a threadpool, which
is correct because the underlying providers (yfinance, `httpx`) block.

## Request Flow

```
Client (browser / MCP client)
    │ HTTPS
    ▼
Cloudflare (nexusmcp.site)        methods rule (GET/POST/OPTIONS only),
    │                             edge rate-limit on cost endpoints,
    │                             respect-origin caching
    ▼
Cloud Run (nexus-core)
    │
    ├─ CORS middleware (outermost)
    ├─ RateLimitMiddleware        per-IP sliding window; /health + /mcp exempt;
    │                             client key resolved spoofing-resistantly
    │                             (CF-Connecting-IP, else rightmost XFF, else peer)
    ▼
FastAPI router  ── REST ──▶  engine + data clients ──▶ JSON (Cache-Control set per route)
       │
       └──── /mcp ────▶  FastMCP transport ──▶ same engine + data clients
```

REST and MCP call the **same** engine and provider instances; `/api/score` and
the MCP `score_asset` tool share one scoring-context builder and framework, so
they return identical scores. Per-route `Cache-Control` headers are the single
source of truth for cache lifetime (regime ~15 min, quotes 5 min, history and
FRED series 1 hr); Cloudflare is set to respect origin.

## REST Endpoints

| Group | Endpoints |
|-------|-----------|
| Meta | `/health`, `/health/db` (DB connectivity probe), `/` (landing) |
| Regime | `/api/regime`, `/api/regime/signals` |
| Scoring | `/api/score/{ticker}` (8-check EMF, SEC EDGAR fundamentals) |
| Market | `/api/market/quote/{symbol}`, `/api/market/history/{symbol}` |
| Economic | `/api/economic/{series_id}` (FRED) |
| Options | `/api/options/price`, `/api/options/overlay/{covered-call,cash-secured-put,collar}`, `/api/options/crypto/currencies`, `/api/options/crypto/{currency}/instruments`, `/api/options/crypto/instrument/{instrument_name}` (BTC/ETH inverse + SOL/XRP/TRX/AVAX USDC-linear, Deribit) |
| Wallet | `/api/wallet/{address}` (DeBank EVM balance) |
| Chain | `/api/chain/chains`, `/api/chain/balance/{chain}/{address}`, `/api/chain/native/{address}` (Tatum) |
| Vaults | `/api/vaults`, `/api/vaults/chains` (vaults.fyi v2) |
| LP | `/api/lp/chains`, `/api/lp/uniswap-v3/{chain}/{token_id}/analytics`, `/api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark` (ethereum, base, optimism, polygon); `/api/lp/aerodrome/{token_id}/analytics` (Base Slipstream, on-chain RPC) |
| Solana | `/api/solana/price/{mint}`, `/api/solana/prices?mints=` (Jupiter v3 SPL token USD prices, keyless) |
| Benchmarks | `/api/benchmarks`, `/api/benchmarks/series?days=`, `/api/benchmarks/history?days=` |
| Usage | `/api/usage` (provider quota report) |
| MCP | `/mcp` (MCP-over-HTTP, FastMCP) |

## Regime Engine

### Signal Ensemble

| Signal | Source | Purpose | Role |
|--------|--------|---------|------|
| Gold/SPX ratio (vs 200WMA) | FRED / market data | Hard-asset vs equity regime | Required |
| Real rates | FRED | Monetary regime | Required |
| DXY | FRED DTWEXBGS | Dollar strength | Required |
| VIX | FRED/CBOE | Volatility regime | Required |
| Credit spreads (BBB OAS) | FRED | Credit conditions | Required |
| Yield curve (2s10s) | Treasury.gov, FRED | Growth vs recession | Supplementary |
| Precious metals | market data | Hard-asset confirmation | Supplementary |

Required signals drive classification; supplementary signals enrich the output
without changing the decision when absent (see `RegimeSignals` in
`engine/regime/signals.py`).

### Regime States

| Regime | Characteristics | Favored Assets |
|--------|----------------|----------------|
| Growth | Expanding economy, low vol | Equities, growth |
| Transition | Mixed signals, rising uncertainty | Balanced, quality |
| Hard Asset | Inflation, commodity strength | Energy, commodities |
| Deflation | Contraction, falling prices | Treasuries, cash |
| Repression | Negative real rates | Hard assets, BTC |

## 8-Check Scoring

1. Durability — persistence through regime changes
2. Regime Fit — current regime alignment
3. Momentum — technical trend
4. Fundamentals — financial health
5. Valuation — relative value
6. Entropy — implied vs realized vol
7. Hurst Exponent — multi-window persistence
8. Catalyst — near-term events

## LP Engine

`engine/lp/uniswap_v3.py` is pure concentrated-liquidity (CLMM) math: tick math,
`get_amounts_for_liquidity`, **exact** impermanent-loss-vs-HODL, and a fee-APR
estimate. The math is protocol-agnostic, so the same engine is reused unchanged
across chains. `/api/lp/uniswap-v3/{chain}/{token_id}/analytics` combines this with
position data from The Graph, uncollected fees read on-chain (`tokensOwed` via
Tatum RPC), and Merkl reward APR to report position value, in-range status, IL,
fee APR, uncollected fees, and total APR. USD prices are required query
parameters (the engine does not assume a price oracle).

Position analytics run on **ethereum, base, optimism, and polygon**. Arbitrum is
not supported: its published subgraph ID uses a schema incompatible with the V3
shape this client decodes.

`/api/lp/aerodrome/{token_id}/analytics` brings the same engine to Aerodrome
Slipstream on Base — a Uniswap-V3 CLMM sibling. No Slipstream subgraph exists on
The Graph, so `data/onchain/slipstream.py` reads position state directly on-chain
via Tatum RPC (NFPM `positions` → CLFactory `getPool` → CLPool `slot0` → token
`decimals`/`symbol`). In this on-chain-only mode (`data_mode: onchain_rpc`) it
reports value, in-range status, token amounts, and uncollected fees; impermanent
loss, fee APR, and AERO gauge reward APR require an indexer (Envio) and are
reported null/zero.

`/api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark` extends the analytics with a
side-by-side comparison against the hold-strategy benchmark returns (from
`engine/benchmarks.py`) over a window, so a position's realized PnL can be read
against simply having held the underlying.

## Benchmarks Engine

`engine/benchmarks.py` derives base-100 hold-strategy return series and
compositions (BTC/ETH/SOL singles; ETH-USDC 50/50, 60/40, 70/30; ETH-BTC 50/50;
USDC held at $1; buy-and-hold) from raw daily USD prices. `/api/benchmarks/series`
computes on demand from CoinGecko; `/api/benchmarks/history` reads from persisted
daily snapshots. The normalization baseline is simply the earliest stored day.

## Solana Token Pricing

`data/onchain/jupiter.py` reads Solana SPL token USD prices from the Jupiter v3
price API. It is keyless — no secret, no quota tracking — so it always runs.
`/api/solana/price/{mint}` returns a single mint's USD price and
`/api/solana/prices?mints=` batches several. The same client is positioned to
enrich Tatum's Solana native-balance read with USD figures.

## Persistence

The public surface is read-only over external APIs. The one persistence seam is
`data/db.py` — async `asyncpg` access to the private **`nexus-marketdata`**
Cloud SQL instance (Postgres 16, private-IP-only on `pwllc-prod-vpc`, backups +
deletion protection). It is reachable only from inside the VPC, never from the
public internet, and is configured by `DATABASE_URL`. When that variable is
unset, `db.is_configured()` is `False` and callers no-op, so the service runs
unchanged without a database (`/api/benchmarks/history` and `/health/db` report
unconfigured rather than failing).

`data/snapshots.py` stores one `benchmark_snapshots` row per day (raw BTC/ETH/SOL/
USDC USD prices as JSONB). The table is created on demand and writes upsert on
`snapshot_date`, so re-running a day is idempotent. Return series and
compositions are derived on read by `engine/benchmarks`, keeping the persisted
shape minimal.

There is **no public write endpoint**. The only writer is the daily snapshot
job: `jobs/daily_snapshot.py`, invoked by `nexus-core snapshot`. In production
it runs as a Cloud Run Job (`nexus-snapshot-job`) triggered by Cloud Scheduler
(`nexus-daily-snapshot`, daily 01:00 America/New_York) over an OAuth
service-account (OIDC) identity — no public HTTP route and no shared secret. The
job fetches today's prices from CoinGecko and upserts one row, failing loudly
(non-zero exit) on incomplete prices or a DB error so the scheduler retries
rather than persisting a partial day.

## MCP Tool Pattern

The MCP surface is built by `build_server()` in `mcp/server/app.py`. Tools
register via `@mcp.tool()`. Responses optionally flow through adopter-supplied
`ResponseFilter` callables before return:

```python
from nexus_core.mcp.server import build_server

def my_pii_filter(tool_name, response, *, auth_context=None):
    # adopter-implemented PII redaction
    return response

def my_tier_filter(tool_name, response, *, auth_context=None):
    # adopter-implemented tier-based response scrubbing
    return response

server = build_server(
    regime_engine=engine,
    filters=[my_pii_filter, my_tier_filter],
)
```

The MCP server ships **no** authentication, authorization, tier enforcement,
audit logging, or PII redaction of its own. The `ResponseFilter` Protocol is the
hook surface where adopters wire those concerns in; the filter implementations
are entirely adopter-defined and adopter-operated. The nexus-core public
deployment runs the server unfiltered — all tool output is public by design.

## Access Control and Tiering (Adopter-Supplied)

The framework does not enforce access tiers. Production deployments that handle
sensitive data need to distinguish public, authenticated, and privileged
callers; adopters compose that logic on top of `ResponseFilter` (post-response
scrubbing) or upstream of the MCP server (for example, an OAuth resource server
in front of the FastAPI host doing authentication and rate limiting before the
request reaches a tool). The public nexus-core deployment treats all callers as
trusted and emits all tool output unfiltered, because it serves only public,
read-only data.

## Security Posture

- Public read-only; **no public write endpoints** (the daily snapshot is a Cloud
  Run Job, not an HTTP route).
- Private-only Cloud SQL: `nexus-marketdata` has no public IP and is reachable
  only from inside `pwllc-prod-vpc`.
- In-process rate limiter resolves the client key spoofing-resistantly
  (`CF-Connecting-IP`, else rightmost `X-Forwarded-For`, else transport peer).
  It is a best-effort abuse guard, not a security boundary — Cloudflare's edge
  rate-limit on cost-bearing endpoints is the primary control.
- Cloudflare methods rule blocks non-`GET`/`POST`/`OPTIONS` requests.
- Secrets live only in Google Secret Manager (`nexus-*-api-key`,
  `nexus-marketdata-database-url`); no credentials in config or code.
- The web service runs as the `nexus-core-run@pwllc-prod` service account.

## Deploy Topology

```
Cloud Scheduler (nexus-daily-snapshot, 01:00 ET)
    │ OIDC (service-account identity, no shared secret)
    ▼
Cloud Run Job (nexus-snapshot-job)  ── nexus-core snapshot ──┐
                                                             │
Cloudflare (nexusmcp.site)                                   │ Direct VPC egress
    │                                                        │ + Cloud SQL connector
    ▼                                                        ▼
Cloud Run Service (nexus-core)  ── Direct VPC egress ──▶  Cloud SQL (nexus-marketdata,
    nexus-core serve                                          private IP, pwllc-prod-vpc)
```

Both the web service and the snapshot job reach the database through Direct VPC
egress into `pwllc-prod-vpc` (subnet `pwllc-prod-cloud-run-us-central1`,
`--vpc-egress=private-ranges-only`) plus the Cloud SQL connector, with
`roles/cloudsql.client`. Provider keys and `DATABASE_URL` are injected from
Secret Manager. See `DEPLOY.md` for the exact `gcloud` invocations.

## CLI

`nexus-core` exposes three run modes:

| Command | Purpose |
|---------|---------|
| `nexus-core serve` | Public HTTP API + MCP-over-HTTP (container / Cloud Run entrypoint) |
| `nexus-core mcp` | MCP server over stdio (local clients such as Claude Desktop) |
| `nexus-core snapshot` | Daily benchmark-price snapshot job (Cloud Run Job) |
