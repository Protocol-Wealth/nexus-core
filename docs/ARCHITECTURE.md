# Nexus Core Architecture

Nexus Core is a public, read-only, regime-adaptive financial-analysis and
DeFi/market-data engine. Python 3.12, FastAPI + FastMCP, synchronous `httpx`,
`asyncpg`. It carries no client data. Local/public-mode REST can run without a
service credential; the hosted deployment service-key gates `/api/*` and the
planning/accounting JSON gateways. Hosted native MCP remains a transparent-OAuth
public demo profile. Every surface is read-only.

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
  accounting/    historical pricing, event decoding, FIFO lots/cost basis,
                 realized-PnL aggregation over de-identified facts
  benchmarks.py  base-100 hold-strategy return series + compositions
    │
    ▼
app/             FastAPI application factory + routers
  main.py        create_app() — wires providers, engine, routers, middleware
  routes.py      regime, market, economic
  scoring.py     /api/score (shares context builder with MCP score_asset)
  layers.py      /api/layer/{ticker} + /api/layers (shares the layer view with MCP classify_layer)
  options.py     options pricing + overlays + Deribit crypto options
  accounting/    contract + restricted REST gateway + handler registry
  wallet.py chain.py vaults.py lp.py benchmarks.py snapshots.py
  access_gate.py service-key middleware for hosted REST/JSON paths
  ratelimit.py   in-process per-IP sliding-window limiter
  mcp_mount.py   mounts FastMCP at /mcp; adapts planning/accounting handlers
  mcp_oauth.py   transparent OAuth 2.1 / PKCE shim for remote MCP clients
mcp/server/      build_server() — the MCP tool surface (regime, score, market,
                 economic, DefiLlama TVL, options) plus generic deployment-tool
                 categories; core registry ships no account auth of its own
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
    ├─ SecurityHeadersMiddleware    outermost response headers
    ├─ CORS middleware              wraps preflight/error responses
    ├─ RateLimitMiddleware        per-IP sliding window; /health + /mcp exempt;
    │                             client key resolved spoofing-resistantly
    │                             (CF-Connecting-IP, else rightmost XFF, else peer)
    ├─ NexusAccessGate            hosted `/api/*` service-key boundary
    ├─ MCPAuthGate               transparent-OAuth gate for native `/mcp` only
    ▼
FastAPI router  ── REST ──▶  engine + data clients ──▶ JSON (Cache-Control set per route)
       │
       └──── /mcp ────▶  FastMCP transport ──▶ same engine + data clients
```

Where a capability is registered on both transports, REST and MCP call the
**same** engine and provider instances; `/api/score` and the MCP `score_asset`
tool share one scoring-context builder and framework, so they return identical
scores. Accounting uses the same handler registry and configured historian on
restricted REST and native MCP full mode. Demo mode returns before accounting
registration, so hosted public MCP remains closed-world. Per-route
`Cache-Control` headers are the single source of truth for cache lifetime
(regime ~15 min, quotes 5 min, history and FRED series 1 hr); Cloudflare is set
to respect origin.

## REST Endpoints

| Group | Endpoints |
|-------|-----------|
| Meta | `/health`, `/health/db` (DB connectivity probe), `/` (landing) |
| Agent/discovery | `/docs`, `/openapi.json`, `/mcp-guide`, `/llms.txt`, `/.well-known/security.txt`, `/.well-known/ai-disclosure.json` |
| OAuth metadata | `/.well-known/oauth-protected-resource[/mcp]`, `/.well-known/oauth-authorization-server`, `/register`, `/authorize`, `/token` (transparent MCP OAuth) |
| Regime | `/api/regime`, `/api/regime/signals` |
| Scoring | `/api/score/{ticker}` (8-check EMF, SEC EDGAR fundamentals), `/api/layer/{ticker}` + `/api/layers` (durability-layer classification + published layer stack) |
| Market | `/api/market/quote/{symbol}`, `/api/market/history/{symbol}` |
| Economic | `/api/economic/{series_id}` (FRED) |
| Options | `/api/options/price`, `/api/options/overlay/{covered-call,cash-secured-put,collar}`, `/api/options/crypto/currencies`, `/api/options/crypto/{currency}/instruments`, `/api/options/crypto/instrument/{instrument_name}` (BTC/ETH inverse + SOL/XRP/TRX/AVAX USDC-linear, Deribit) |
| Wallet | `/api/wallet/{address}` (DeBank EVM balance) |
| Chain | `/api/chain/chains`, `/api/chain/balance/{chain}/{address}`, `/api/chain/native/{address}` (Tatum) |
| Vaults | `/api/vaults`, `/api/vaults/chains` (vaults.fyi v2) |
| LP | `/api/lp/chains`, `/api/lp/uniswap-v3/{chain}/positions?owner=`, `/api/lp/uniswap-v3/{chain}/{token_id}/analytics`, `/api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark` (ethereum, base, optimism, polygon); `/api/lp/aerodrome/{token_id}/analytics` (Base Slipstream, on-chain RPC) |
| Solana | `/api/solana/price/{mint}`, `/api/solana/prices?mints=` (Jupiter v3 SPL token USD prices, keyless) |
| Accounting gateway | `GET /api/accounting/tools`, `POST /api/accounting/tools/{tool_id}` (deployed contract `0.2.0` on Cloud Run revision `nexus-core-00070-zhx`; the same four calculation handlers also register in native MCP full mode in the deployed image) |
| Benchmarks | `/api/benchmarks`, `/api/benchmarks/series?days=`, `/api/benchmarks/history?days=` |
| Usage | `/api/usage` (provider quota report) |
| MCP | `/mcp` (MCP-over-HTTP, FastMCP) |
| Planning gateway | `GET /api/planning/tools`, `POST /api/planning/tools/{tool_id}` (34 PII-free planning tools, contractVersion `0.1.0`); `/mcp/tools` is the legacy alias |

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

## Durability Layers

Every asset is classified into one of seven durability layers. The layer is a
structural input to scoring: it sets the λ (decay-constant) ceiling the Lambda
check tests against (`LAYER_DECAY_THRESHOLDS`) and the target portfolio weight
each regime assigns to the asset (`LAYER_WEIGHTS_BY_REGIME`).

| Code | Key | Name | Horizon | λ ceiling |
|------|-----|------|---------|-----------|
| L1 | `L1_foundation` | Foundation | 40-60 yr | 0.05 |
| L2 | `L2_backbone` | Backbone | 15-30 yr | 0.08 |
| L3 | `L3_engine` | Engine | 5-10 yr | 0.20 |
| L4 | `L4_datatoll` | Data Infrastructure | 7-12 yr | 0.15 |
| L5 | `L5_interface` | Interface | 3-5 yr | 0.30 |
| L6 | `L6_frontier` | Frontier | 1-3 yr | 0.50 |
| L7 | `L7_catalyst` | Catalyst | tactical | 0.50 |

The code key for layer 4 stays `L4_datatoll` (engines and downstream bridges key
on it); "Data Infrastructure" is its published display name.

Classification (`engine/scoring/emf/context_helpers.py::classify_layer`) applies
one priority order and reports which rule decided it: explicit ticker map →
asset-class route (crypto pairs, sector/commodity ETFs) → sector/industry keyword
rule → sector default → `UNCLASSIFIED`. An asset that matches nothing is left
`UNCLASSIFIED` rather than defaulted to a layer, so the layer-dependent checks
report insufficient data instead of guessing. Broad-market ETFs are deliberately
unmapped — a diversified index has no single durability layer.

The taxonomy (names, horizons, profiles) lives in `engine/scoring/emf/layers.py`
and is served by `GET /api/layer/{ticker}`, `GET /api/layers`, and the MCP
`classify_layer` tool.

## LP Engine

`engine/lp/uniswap_v3.py` is pure concentrated-liquidity (CLMM) math: tick math,
`get_amounts_for_liquidity`, **exact** impermanent-loss-vs-HODL, and a fee-APR
estimate. The math is protocol-agnostic, so the same engine is reused unchanged
across chains. `/api/lp/uniswap-v3/{chain}/{token_id}/analytics` combines this with
position data from The Graph, uncollected fees read on-chain (`tokensOwed` via
Tatum RPC), and Merkl reward APR to report position value, in-range status, IL,
fee APR, uncollected fees, and total APR. USD prices are required query
parameters (the engine does not assume a price oracle).

Position analytics run on **ethereum, base, optimism, and polygon**.
`/api/lp/uniswap-v3/{chain}/positions?owner=` enumerates open positions owned by
a public EVM address in token units (no USD valuation), then the by-token routes
add valuation/IL/fee analytics when prices are supplied. Arbitrum is not
supported: its published subgraph ID uses a schema incompatible with the V3 shape
this client decodes.

## Onchain Accounting Engine

`engine/accounting/` contains the public-safe P0-P4 calculation substrate:
multi-source historical price resolution, deterministic event classification,
FIFO lot/cost-basis math, and realized-PnL aggregation. The separate
`app/accounting/` contract uses opaque references, recursively rejects
identity-shaped keys, validates request shapes with pydantic, preserves unknown
price/basis values as unknown, and attaches canonical disclaimers.

The deployed transport is `GET /api/accounting/tools` plus
`POST /api/accounting/tools/{tool_id}`, protected by the hosted REST service-key
gate. Current source also adapts the same handler registry into native MCP full
mode. `create_app()` injects one configured price historian into both transports;
the adapter applies the same recursive identity scan, contract/disclaimer
envelope, and stable input-error mapping. The MCP server retains its top-level
`describe` tool and reports the four accounting calculation tools under an
`accounting` category; it does not register accounting's internal `describe`.
Demo mode registers none of these tools, so the production demo profile is
unchanged.
Deployed contract `0.2.0` adds account-scoped FIFO, explicit transfer and
fee treatment, calendar holding periods, full-history/opening-state report replay,
authoritative basis conservation, method-pinned opening snapshots, replay-safe
lineage, and structured completeness. Unit-only legacy opening lots remain
calculable but explicitly incomplete. Private custodian ingestion,
wallet-to-client mapping, statement construction, tax-return preparation,
approval, release, and retention remain outside this repo. Technical issue #260
is complete; private consumer epic `pw-api#789` blocks statement composition
until compatibility passes and the methodology is CIO/IC/CCO-reviewed. The
engine reports `statement_ready=false` while that review is pending.

## Planning Engine

`engine/planning/` holds pure, PII-free planning primitives exposed through both
native MCP and the REST planning gateway. The current handler registry has 34
tools spanning Monte Carlo and deterministic cash flow, goals and education,
income/withdrawal/tax analysis, Social Security and inherited IRA analysis,
historical/performance/risk context, allocation and rebalancing, Roth/IRMAA
analysis, and report-input assembly. The authoritative current list is in
`CURRENT-STATE.md` and the gateway discovery response.

The gateway (`app/planning/gateway.py`) rejects identity-shaped keys anywhere in
the request body and echoes `contractVersion: "0.1.0"` on success. The composite
Roth/IRMAA case object has its own `PLANNING_CONTRACT_VERSION = "1.1.0"`.

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

The core MCP registry ships no account authentication, tier enforcement, audit
logging, or PII redaction of its own. The `ResponseFilter` Protocol is the hook
surface where adopters wire those concerns in; the filter implementations are
entirely adopter-defined and adopter-operated. The hosted nexus-core deployment
runs the closed-world demo MCP profile without private scopes, while
`app/mcp_oauth.py` sits in front of `/mcp` to satisfy remote MCP OAuth handshakes
without creating user accounts. Hosted REST/JSON uses the separate service-key
gate described above.

## Access Control and Tiering (Adopter-Supplied)

The framework does not enforce access tiers. Production deployments that handle
sensitive data need to distinguish public, authenticated, and privileged callers;
adopters compose that logic on top of `ResponseFilter` (post-response scrubbing)
or upstream of the MCP server. The hosted nexus-core OAuth shim is intentionally
not an access-tier system: it issues public-scope tokens for anonymous clients so
remote MCP connectors can complete their required authorization flow.

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
- Transparent MCP OAuth is stateless and anonymous when `MCP_OAUTH_SIGNING_KEY`
  is set; it uses Dynamic Client Registration, PKCE, and HMAC-signed compact
  tokens. Omitting the key leaves `/mcp` open in local/unkeyed deployments.
- Secrets live only in Google Secret Manager (`nexus-*-api-key`,
  `nexus-marketdata-database-url`, hosted OAuth signing key); no credentials in
  config or code.
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
