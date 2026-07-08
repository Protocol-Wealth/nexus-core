# HANDOFF — `nexus-core` (open-source repo)

Operator handoff / current-state snapshot for `nexus-core` — the public,
Apache-2.0 regime-adaptive financial-analysis + DeFi/market-data engine
(github.com/Protocol-Wealth/nexus-core). Public, read-only, no client data,
native MCP can remain a public demo surface; REST/JSON calculation paths can be
service-key gated; remote MCP may use transparent OAuth with no user login.
This file is the practical "what's live, what's next" reference for the next
session.

Stack: Python 3.12, FastAPI + FastMCP, sync `httpx`, `asyncpg`, `mypy --strict`,
`ruff`. Version `0.1.0`. CI-gated test suite.

> **For the current handoff read [NEXT-SESSION.md](NEXT-SESSION.md)** (latest
> forward state) and **[CURRENT-STATE.md](CURRENT-STATE.md)** (live snapshot).
> This file retains earlier-cycle operator detail; where it disagrees with those
> two, they win. Live status was refreshed 2026-07-01: `/health` is healthy,
> `/mcp/tools` reports contractVersion `0.1.0` with 23 planning tools, GitHub has
> no open PRs and seven open issues (#197-#203), and `ruff` + `mypy --strict`
> remain CI-enforced. Local source as of 2026-07-06 adds collar-book
> executable-fill modeling plus optional REST/JSON access gating, but it has not
> been live-smoked.

---

## What's live

Deployed at **nexusmcp.site** (Cloudflare → Google Cloud Run, region
`us-central1`). Three moving pieces:

1. **Web service** `nexus-core` — runs `nexus-core serve` (public HTTP API +
   MCP-over-HTTP). `--allow-unauthenticated`.
2. **Cloud Run Job** `nexus-snapshot-job` — runs `nexus-core snapshot`, writes
   the daily benchmark-price snapshot. This is a Job, **not** an HTTP route —
   there is no public write endpoint.
3. **Cloud Scheduler** `nexus-daily-snapshot` — triggers the Job daily at
   01:00 America/New_York via an OAuth service-account identity (no shared
   secret).

Persistence is a **private Cloud SQL** instance, `nexus-marketdata`
(`POSTGRES_16`, private-IP-only on `pwllc-prod-vpc`, backups + deletion
protection). The web service and the Job reach it via Direct VPC egress
(`--network=pwllc-prod-vpc --subnet=pwllc-prod-cloud-run-us-central1
--vpc-egress=private-ranges-only`) plus a Cloud SQL connection
(`--add-cloudsql-instances` for the service, `--set-cloudsql-instances` for
the Job) and `roles/cloudsql.client`. Runtime SA: `nexus-core-run@pwllc-prod`.

CLI (`nexus-core …`): `serve`, `mcp` (stdio, for Claude Desktop), `snapshot`.

---

## Endpoint surface (full current public surface)

All read-only GET (plus POST/OPTIONS where noted). External integrations
degrade gracefully to `None`/empty/`503` when their API key is absent.

**Core / health**

- `/health`, `/health/db` (DB connectivity probe), `/` (landing)

**Regime + scoring (EMF)**

- `/api/regime`, `/api/regime/signals` — regime classification
- `/api/score/{ticker}` — 8-check EMF scoring (SEC EDGAR fundamentals)

**Market + macro data**

- `/api/market/quote/{symbol}`, `/api/market/history/{symbol}` — composite
  (yfinance / MBOUM / MarketStack / CoinGecko)
- `/api/economic/{series_id}` — FRED economic series

**Options (educational, Black-Scholes)**

- `/api/options/price`
- `/api/options/overlay/{covered-call,cash-secured-put,collar}`
- `/api/options/overlay/collar-screen` — batch theoretical equity collar screen
- `/api/options/overlay/collar-book` — advisor research worksheet; local source
  accepts optional executable fill inputs (`executable_net_credit` or `call_bid`
  / `put_ask`) and reports fill haircut/executable yield
- `/api/options/equity/{symbol}/expirations`,
  `/api/options/equity/{symbol}/chain?expiration=` — MBOUM listed equity option
  expirations/chains
- `/api/options/crypto/currencies`,
  `/api/options/crypto/{currency}/instruments`,
  `/api/options/crypto/instrument/{instrument_name}` — Deribit crypto options on
  BTC/ETH (coin-settled inverse) + SOL/XRP/TRX/AVAX (USDC-settled linear, read
  from Deribit's `USDC` umbrella). Keyless.

**On-chain / wallets**

- `/api/wallet/{address}` — anonymous EVM wallet balance (DeBank)
- `/api/chain/chains`, `/api/chain/balance/{chain}/{address}`,
  `/api/chain/native/{address}` — multi-chain native balances (Tatum: EVM
  `eth_getBalance` + Solana `getBalance`)

**DeFi vaults + LP**

- `/api/vaults`, `/api/vaults/chains` — vault discovery (vaults.fyi v2)
- `/api/lp/chains`,
  `/api/lp/uniswap-v3/{chain}/{token_id}/analytics` — Uniswap V3 position
  analytics: value, in-range, exact impermanent-loss-vs-HODL, fee-APR
  estimate, uncollected fees (RPC `tokensOwed` via Tatum), Merkl reward APR →
  total APR. USD prices are required query params. (The Graph + RPC + Merkl.)
- `/api/lp/aerodrome/{token_id}/analytics` — Aerodrome Slipstream on **Base**,
  read directly on-chain via Tatum RPC (no subgraph; `data/onchain/slipstream.py`).
  Same pure engine. `data_mode: onchain_rpc` — value, in-range, token amounts,
  uncollected fees; IL, fee APR, AERO gauge APR null/zero (Envio = follow-on).

**Benchmarks**

- `/api/benchmarks`, `/api/benchmarks/series?days=`,
  `/api/benchmarks/history?days=` — base-100 hold-strategy returns (BTC/ETH/SOL
  + ETH-USDC 50/50, 60/40, 70/30 + ETH-BTC 50/50; USDC held at $1;
  buy-and-hold). `/series` = on-demand from CoinGecko; `/history` = from the
  persisted daily snapshots.

**Ops + MCP**

- `/api/usage` — provider usage / quota report
- `/mcp` — MCP-over-HTTP transport (FastMCP)
- `/api/planning/tools`, `POST /api/planning/tools/{tool_id}` — PII-free
  planning REST gateway
- `/mcp/tools`, `POST /mcp/tools/{tool_id}` — legacy planning REST gateway
  aliases
  with 23 tools, contractVersion `0.1.0`

---

## Module map (where things live)

- **Data clients** — `data/onchain/{debank,tatum,thegraph,merkl,vaultsfyi,defillama}.py`;
  `data/market/{coingecko,mboum,marketstack,yfinance}_provider` + cache +
  composite; `data/macro` (FRED); `data/edgar` (SEC fundamentals);
  `data/derivatives` (Deribit); `data/db.py` + `data/snapshots.py` (asyncpg
  persistence).
- **Engine** — `engine/regime` (`RegimeEngine`), `engine/scoring/emf` (8-check),
  `engine/pricing` (Black-Scholes), `engine/lp/uniswap_v3.py` (pure CLMM math:
  tick math, `get_amounts_for_liquidity`, exact IL, fee APR),
  `engine/benchmarks.py` (base-100 + buy-and-hold compositions), and
  `engine/planning` (PII-free educational planning math).
- **Jobs** — `jobs/daily_snapshot.py`.
- **CLI** — `nexus-core {serve|mcp|snapshot}`.

---

## Secrets + env vars

Secrets live only in **Google Secret Manager** — no credentials in config.
Provider keys: `nexus-{fred,mboum,marketstack,coingecko,eia,bea,debank,tatum,vaultsfyi,thegraph}-api-key`
plus `nexus-marketdata-database-url`.

Runtime env vars (each external integration degrades gracefully when its key
is absent):

- `FRED_API_KEY`, `MBOUM_API_KEY`, `MARKETSTACK_API_KEY`, `COINGECKO_API_KEY`,
  `EIA_API_KEY`, `BEA_API_KEY`
- `DEBANK_API_KEY` (`/api/wallet`)
- `TATUM_API_KEY` (`/api/chain` + LP uncollected fees)
- `VAULTSFYI_API_KEY` (`/api/vaults`)
- `THEGRAPH_API_KEY` (`/api/lp`)
- `DATABASE_URL` (persistence + `/api/benchmarks/history`; returns `503` when
  unset)
- `MCP_OAUTH_SIGNING_KEY` (optional transparent OAuth token signing for hosted
  remote MCP clients)
- `NEXUS_PUBLIC_MCP_PROFILE` (`full` default or `demo`),
  `NEXUS_ACCESS_MODE` (`public` default or `restricted`), `NEXUS_API_KEYS`,
  `NEXUS_RATE_LIMIT_PER_MIN` (default 60), `NEXUS_CORS_ORIGINS`

---

## Security posture

- Public, read-only. **No public write endpoints** — the daily snapshot is a
  Cloud Run Job, not an HTTP route.
- No account/API-key gate on REST endpoints; hosted remote MCP has transparent
  OAuth metadata/registration/authorize/token endpoints for client compatibility.
- Cloud SQL is private-IP-only; reachable only over Direct VPC egress.
- In-process rate limiter resolves client IP **spoofing-resistantly**:
  `CF-Connecting-IP`, else the rightmost `X-Forwarded-For` hop (the fix on
  branch `fix/ratelimit-xff`).
- Cloudflare methods rule blocks non-GET/POST/OPTIONS; edge rate-limit on the
  cost endpoints.
- Secrets only in Secret Manager; Scheduler → Job uses an OAuth SA identity,
  not a static token.

---

## Deploy (summary — `DEPLOY.md` owns the detail)

```bash
# Web service
gcloud run deploy nexus-core \
  --source . --region us-central1 \
  --service-account nexus-core-run@pwllc-prod.iam.gserviceaccount.com \
  --allow-unauthenticated \
  --network=pwllc-prod-vpc \
  --subnet=pwllc-prod-cloud-run-us-central1 \
  --vpc-egress=private-ranges-only \
  --add-cloudsql-instances <instance-connection-name> \
  --set-secrets <provider keys + DATABASE_URL>

# Snapshot Job (note: --set-cloudsql-instances, NOT --add-)
gcloud run jobs deploy nexus-snapshot-job \
  --source . --command nexus-core --args snapshot \
  --set-cloudsql-instances <instance-connection-name> \
  --network=pwllc-prod-vpc --subnet=... --vpc-egress=private-ranges-only \
  --set-secrets DATABASE_URL=...,COINGECKO_API_KEY=...

# Scheduler (OAuth SA, NOT a static token)
gcloud scheduler jobs create http nexus-daily-snapshot \
  --schedule "0 1 * * *" --time-zone America/New_York \
  --oauth-service-account-email nexus-core-run@pwllc-prod.iam.gserviceaccount.com \
  ...
```

---

## Build + test status

From the repo root with the `.venv` activated:

```bash
pip install -e ".[dev]"        # if not already installed
pytest                         # full test suite
ruff check src/ tests/
mypy --strict src/nexus_core/
```

All three should be green.

---

## Next up (ROADMAP)

Shipped since this handoff was first written: the position-vs-benchmark surface
(`/api/lp/.../vs-benchmark`), the Jupiter Solana price source (`/api/solana`), and
Aerodrome Slipstream on Base via on-chain RPC (`/api/lp/aerodrome/{token_id}/analytics`,
partial — value/in-range/amounts/uncollected fees). Remaining work is tracked in
GitHub:

1. **#197** — public-safe planning/report analytics extraction.
2. **#198** — planning assumptions provenance.
3. **#199** — LP/indexer expansion and data quality.
4. **#200** — crypto-options follow-ups.
5. **#201** — agent analytics capability backlog.
6. **#202** — governance/tooling cleanup.
7. **#203** — equity-research vertical gates and buildout.
