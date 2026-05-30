# Current state — nexus-core

A point-in-time snapshot of exactly what is live right now. For the architectural
overview see [README.md](README.md); for deploy mechanics see [DEPLOY.md](DEPLOY.md);
for the public-surface audit see [AUDIT.md](AUDIT.md).

- **Repo:** [github.com/Protocol-Wealth/nexus-core](https://github.com/Protocol-Wealth/nexus-core) — public, Apache-2.0
- **Live:** [nexusmcp.site](https://nexusmcp.site) (Cloudflare → Cloud Run)
- **Version:** 0.1.0
- **Stack:** Python 3.12 · FastAPI · FastMCP · sync httpx · asyncpg · mypy `--strict` · ruff
- **Tests:** ~594-test suite (`pytest`)
- **Posture:** public, read-only, no client data, no auth, no public write endpoints

## Public REST surface

Every endpoint is anonymous GET (the `/mcp` transport also accepts POST). External
integrations degrade gracefully — when a provider key is absent the dependent
endpoint returns `None` / empty / `503` rather than failing the service.

### Meta

| Endpoint | Data source | Required key |
|----------|-------------|--------------|
| `GET /` | — (landing page) | — |
| `GET /health` | — (liveness probe) | — |
| `GET /health/db` | Cloud SQL connectivity probe | `DATABASE_URL` |
| `GET /api/usage` | in-process cache + provider usage report | — |

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
| `GET /api/options/crypto/{currency}/instruments` | Deribit | — |
| `GET /api/options/crypto/instrument/{instrument_name}` | Deribit | — |

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
| `POST /mcp` | FastMCP-over-HTTP transport over the regime + scoring engines | — |

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
`nexus-thegraph-api-key`, `nexus-marketdata-database-url`.

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
- Cloudflare methods rule blocks non-`GET`/`POST`/`OPTIONS`; edge rate-limit on the
  cost endpoints.
- No client data, no PII at risk.

## Recent work (this cycle)

- Multi-chain Uniswap V3 LP analytics — base / optimism / polygon (joining ethereum)
- LP position `vs-benchmark` route — pairs IL with hold-strategy returns ("was LPing worth it?")
- Jupiter Solana SPL token USD prices — single + batch, keyless (`/api/solana/*`)

Prior cycle: Tatum multi-chain native balances (`/api/chain/*`), vaults.fyi vault
discovery (`/api/vaults`), Uniswap V3 LP analytics (exact IL + fees + Merkl reward APR),
CoinGecko hold-strategy benchmarks (on-demand + persisted), private market-data Cloud SQL
+ daily snapshot Cloud Run Job + Cloud Scheduler, spoofing-resistant rate-limiter fix.

## Next (roadmap)

- **Aerodrome Slipstream — full coverage via Envio** — the on-chain RPC path is **live**
  (`GET /api/lp/aerodrome/{token_id}/analytics`, partial: value, in-range, token amounts,
  uncollected fees; `data_mode: onchain_rpc`). No canonical Slipstream V3-schema subgraph
  exists on The Graph (name-matching ones are Revert-automation + ICHI-vault subgraphs),
  and the on-chain-only path cannot derive IL (needs deposit history), fee APR (needs pool
  volume), or AERO gauge reward APR. An **Envio** client would add those; the pure engine +
  Slipstream NFPM (`0x827922686190790b37229fd06084350E74485b72`, decode-compatible) are wired.
- **Arbitrum Uniswap V3** — needs a correct V3-schema subgraph ID (published one is incompatible).
- **Base subgraph data quality** — public Base V3 deployment has spam-token TVL
  contamination (pollutes discovery + pool-aggregate fee APR; per-position value/IL stay
  accurate) → consider self-hosting a cleaner indexer.
- **Uniswap V4** via Envio (Unichain).
- **Solana CLMM** (Raydium / Orca) — Q64.64 sibling engine; Jupiter price layer already shipped.
- Subgraph health-gate (`_meta` block-lag → degraded).
- Persisted position-PnL history.
- Enrich Tatum Solana balance with Jupiter USD prices.
