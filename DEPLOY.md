# Deploying nexus-core

This document describes how the public nexus-core surface — [nexusmcp.site](https://nexusmcp.site) —
is built and deployed. The deployable application lives in
[`src/nexus_core/app/`](src/nexus_core/app/); it exposes the regime engine,
market/onchain data, options, DeFi analytics, and PII-free planning math as a
read-only HTTP API plus an MCP-over-HTTP transport. The native MCP transport can
remain a public demo surface while REST/JSON calculation endpoints are
optionally service-key gated. Traffic flows Cloudflare → Cloud Run.

Three deployable units make up the production system:

1. **The web service** (`nexus-core serve`) — the public HTTP API + MCP transport.
2. **The snapshot job** (`nexus-core snapshot`) — a Cloud Run Job that writes the
   daily benchmark-price snapshot. It is **not** an HTTP route.
3. **The scheduler** — a Cloud Scheduler job that triggers the snapshot job once a
   day using an OAuth service-account identity (no shared secret).

## What gets deployed

`nexus-core serve` (the container `CMD`) starts a [uvicorn](https://www.uvicorn.org/)
server hosting the FastAPI application from `nexus_core.app:create_app`:

| Path | Description |
|------|-------------|
| `GET /` | Landing page |
| `GET /health` | Liveness probe (rate-limit exempt) |
| `GET /health/db` | Database connectivity probe |
| `GET /docs` | Interactive OpenAPI / Swagger UI |
| `GET /openapi.json` | OpenAPI schema |
| `GET /mcp-guide` | MCP setup guide |
| `GET /llms.txt` | Agent site map |
| `GET /.well-known/security.txt` | RFC 9116 security contact |
| `GET /.well-known/ai-disclosure.json` | Machine-readable AI disclosure card |
| `GET /.well-known/oauth-protected-resource[/mcp]` | MCP OAuth protected-resource metadata |
| `GET /.well-known/oauth-authorization-server` | MCP OAuth authorization-server metadata |
| `POST /register`, `GET /authorize`, `POST /token` | Transparent OAuth 2.1 / PKCE flow for remote MCP clients |
| `GET /api/regime` | Current macro regime classification |
| `GET /api/regime/signals` | Raw regime signal readings |
| `GET /api/score/{ticker}` | 8-check EMF scoring (SEC EDGAR fundamentals) |
| `GET /api/market/quote/{symbol}` | Latest quote (stocks, ETFs, indices, crypto) |
| `GET /api/market/history/{symbol}` | OHLCV price history |
| `GET /api/economic/{series_id}` | FRED economic series |
| `GET /api/options/price` | Black-Scholes option pricing + Greeks |
| `GET /api/options/overlay/{strategy}` | Educational covered-call / cash-secured-put / collar overlays |
| `POST /api/options/overlay/collar-screen` | Batch equity collar screen (≤25 positions; dividend-aware theoretical pricing) |
| `POST /api/options/overlay/collar-book` | Multi-name collar book assembly (≤50 candidates; whole contracts, position/sector caps) — advisor research worksheet, no orders |
| `GET /api/options/equity/{symbol}/expirations` | Listed equity option expirations (weekly/monthly; MBOUM-backed) |
| `GET /api/options/equity/{symbol}/chain?expiration=` | Single-expiration equity option chain (bid/ask, OI, IV, delta) |
| `GET /api/options/crypto/currencies` | Deribit-supported crypto option underliers |
| `GET /api/options/crypto/{currency}/instruments` | Deribit crypto option instruments |
| `GET /api/options/crypto/instrument/{instrument_name}` | Deribit crypto option detail |
| `GET/POST /api/options/crypto/{currency}/...` | Settlement-aware crypto overwrite/hedge suite |
| `GET /api/wallet/{address}` | Anonymous EVM wallet balance (DeBank) |
| `GET /api/chain/chains` | Supported chains for native-balance lookups |
| `GET /api/chain/balance/{chain}/{address}` | Multi-chain native balance (Tatum) |
| `GET /api/chain/native/{address}` | Native balance helper |
| `GET /api/vaults` | DeFi vault discovery (vaults.fyi v2) |
| `GET /api/vaults/chains` | Vault-discovery supported chains |
| `GET /api/solana/price/{mint}` | Solana SPL token USD price (Jupiter v3) |
| `GET /api/solana/prices?mints=` | Batch Solana SPL token USD prices |
| `GET /api/lp/chains` | LP-analytics supported chains |
| `GET /api/lp/uniswap-v3/{chain}/positions?owner=` | Open Uniswap V3 positions owned by a public address |
| `GET /api/lp/uniswap-v3/{chain}/{token_id}/analytics` | Uniswap V3 position analytics (exact IL, fee APR, Merkl rewards) |
| `GET /api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark` | LP position analytics vs hold-strategy benchmarks |
| `GET /api/lp/aerodrome/{token_id}/analytics` | Aerodrome Slipstream position analytics on Base |
| `GET /api/benchmarks` | Base-100 hold-strategy benchmark definitions |
| `GET /api/benchmarks/series?days=` | On-demand benchmark returns (CoinGecko) |
| `GET /api/benchmarks/history?days=` | Benchmark returns from persisted daily snapshots |
| `GET /api/usage` | Provider usage / quota report |
| `POST /mcp` | Model Context Protocol endpoint; full profile includes planning plus four accounting calculation tools, while hosted demo excludes both groups |
| `GET /api/planning/tools`, `POST /api/planning/tools/{tool_id}` | PII-free planning REST gateway (34 current-source tools, contractVersion `0.1.0`) |
| `GET /api/accounting/tools` | De-identified accounting tool discovery and contract-version handshake |
| `POST /api/accounting/tools/{tool_id}` | Deployed accounting contract `0.2.0`: pricing, decoding, account-scoped FIFO/replay, and PnL tools |
| `GET /mcp/tools`, `POST /mcp/tools/{tool_id}` | Legacy planning REST gateway aliases |

There is **no client data** and **no public write endpoint** — the daily snapshot
runs as a Cloud Run Job, not an HTTP route. The hosted `/mcp` transport can use
transparent OAuth for remote MCP client compatibility; it does not add user login
or privileged scopes. In restricted mode, `/api/*`, `/api/planning/tools/*`,
`/api/accounting/tools/*`, and legacy `/mcp/tools/*` require a Nexus API key
supplied by trusted service callers such as `pw-api`. See [`AUDIT.md`](AUDIT.md).

## Configuration

All configuration is environment-driven. Every provider key is optional; the app
runs without any of them, degrading each integration gracefully to
`None` / empty / `503` when its key is absent.

| Variable | Effect | Secret |
|----------|--------|--------|
| `FRED_API_KEY` | Enables `/api/economic/*` and macro precision for `/api/regime` | yes |
| `MBOUM_API_KEY` | Adds MBOUM as a market-data fallback | yes |
| `MARKETSTACK_API_KEY` | Adds MarketStack as a market-data fallback | yes |
| `COINGECKO_API_KEY` | Raises CoinGecko limits; powers benchmarks (works keyless too) | yes |
| `EIA_API_KEY` | EIA energy data for regime inputs | yes |
| `BEA_API_KEY` | BEA economic data | yes |
| `DEBANK_API_KEY` | Enables `/api/wallet/{address}` | yes |
| `TATUM_API_KEY` | Enables `/api/chain/*` and LP uncollected-fees RPC reads | yes |
| `VAULTSFYI_API_KEY` | Enables `/api/vaults*` discovery | yes |
| `THEGRAPH_API_KEY` | Enables `/api/lp/*` Uniswap V3 analytics | yes |
| `DATABASE_URL` | Cloud SQL persistence; powers `/api/benchmarks/history` and `/health/db` (`503` when unset) | yes |
| `MCP_OAUTH_SIGNING_KEY` | Enables stateless transparent OAuth for remote `/mcp`; omit locally to keep `/mcp` open | yes in hosted deploy |
| `NEXUS_PUBLIC_MCP_PROFILE` | `full` (default) or `demo`; full includes the de-identified planning and accounting adapters, while demo registers only closed-world native MCP tools | no |
| `NEXUS_ACCESS_MODE` | `public` (default) or `restricted`; restricted gates `/api/*` and planning JSON gateway paths | no |
| `NEXUS_API_KEYS` | Comma-separated raw service keys or `sha256:<hex>` digests accepted in restricted mode | yes when restricted |
| `NEXUS_MCP_CLIENT_SECRETS` | Comma-separated raw secrets or `sha256:<hex>` digests that may mint an `/mcp` access token via the OAuth `client_credentials` grant — the non-interactive path for CLIs, coding agents and cron. Unset disables the grant entirely (it is not advertised and not accepted). **Separate from `NEXUS_API_KEYS` on purpose**: those gate the REST surfaces, and one variable for both would mean neither could be revoked without the other | no |
| `NEXUS_RATE_LIMIT_PER_MIN` | Per-IP request budget (default `60`) | no |
| `NEXUS_CORS_ORIGINS` | Comma-separated CORS allow-list (default `*`) | no |
| `PORT` | Listen port (Cloud Run injects this; default `8080`) | no |

yfinance (keyless) and CoinGecko (keyless) work with zero configuration, so a
no-secrets deployment still serves live market data and regime classification.

## Local run

```bash
pip install -e ".[serve]"
nexus-core serve                 # http://127.0.0.1:8080
nexus-core serve --port 9000     # override the port
nexus-core mcp                   # MCP server over stdio (for Claude Desktop)
nexus-core snapshot              # run the daily benchmark snapshot job once
```

## Container build

```bash
docker build -t nexus-core .
docker run --rm -p 8080:8080 nexus-core
curl http://127.0.0.1:8080/health
```

The same image serves all three deployable units; only the `--command` / `--args`
differ between the web service and the snapshot job.

## Cloud Run deploy (canonical)

Protocol Wealth infrastructure runs on Google Cloud (project `pwllc-prod`).
nexus-core deploys to Cloud Run from source — Cloud Build builds the `Dockerfile`
automatically.

**Prerequisites** (one-time, per project): `gcloud` CLI authenticated; the Cloud
Run, Cloud Build, Artifact Registry, Cloud SQL Admin, Secret Manager, and Cloud
Scheduler APIs enabled. The runtime service account is
`nexus-core-run@pwllc-prod.iam.gserviceaccount.com`, granted `roles/cloudsql.client`
and `roles/secretmanager.secretAccessor`.

### 1. Secrets (Google Secret Manager)

All provider keys and the database URL live in Secret Manager. The runtime SA
reads them via `--set-secrets`. Create each once:

```bash
printf '%s' "YOUR_FRED_KEY"        | gcloud secrets create nexus-fred-api-key --data-file=-
printf '%s' "YOUR_MBOUM_KEY"       | gcloud secrets create nexus-mboum-api-key --data-file=-
printf '%s' "YOUR_MARKETSTACK_KEY" | gcloud secrets create nexus-marketstack-api-key --data-file=-
printf '%s' "YOUR_COINGECKO_KEY"   | gcloud secrets create nexus-coingecko-api-key --data-file=-
printf '%s' "YOUR_EIA_KEY"         | gcloud secrets create nexus-eia-api-key --data-file=-
printf '%s' "YOUR_BEA_KEY"         | gcloud secrets create nexus-bea-api-key --data-file=-
printf '%s' "YOUR_DEBANK_KEY"      | gcloud secrets create nexus-debank-api-key --data-file=-
printf '%s' "YOUR_TATUM_KEY"       | gcloud secrets create nexus-tatum-api-key --data-file=-
printf '%s' "YOUR_VAULTSFYI_KEY"   | gcloud secrets create nexus-vaultsfyi-api-key --data-file=-
printf '%s' "YOUR_THEGRAPH_KEY"    | gcloud secrets create nexus-thegraph-api-key --data-file=-
printf '%s' "YOUR_DATABASE_URL"    | gcloud secrets create nexus-marketdata-database-url --data-file=-
printf '%s' "YOUR_RANDOM_SIGNING_KEY" | gcloud secrets create nexus-mcp-oauth-signing-key --data-file=-
```

Restricted REST/JSON mode uses the Terraform-managed
`pwllc-nexus-api-key-digests` secret from `pw-infrastructure`. It contains the
accepted `sha256:<hex>` digest list for `NEXUS_API_KEYS`. Do not mount the raw
service key on Nexus; the raw bearer key is held by `pw-api` as
`NEXUS_SERVICE_API_KEY`.

### 2. Private database

Persistence is a private Cloud SQL instance, `nexus-marketdata`
(`POSTGRES_16`, private-IP-only on the `pwllc-prod-vpc` VPC, with automated
backups and deletion protection enabled). It has **no public IP**. The web
service reaches it via Direct VPC egress; the `DATABASE_URL` secret points at the
private address.

### 3. Deploy the web service

```bash
gcloud run deploy nexus-core \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --min-instances 1 \
  --service-account nexus-core-run@pwllc-prod.iam.gserviceaccount.com \
  --network pwllc-prod-vpc \
  --subnet pwllc-prod-cloud-run-us-central1 \
  --vpc-egress private-ranges-only \
  --add-cloudsql-instances pwllc-prod:us-central1:nexus-marketdata \
  --set-env-vars "NEXUS_PUBLIC_MCP_PROFILE=demo,NEXUS_ACCESS_MODE=restricted" \
  --set-secrets "FRED_API_KEY=nexus-fred-api-key:latest,\
MBOUM_API_KEY=nexus-mboum-api-key:latest,\
MARKETSTACK_API_KEY=nexus-marketstack-api-key:latest,\
COINGECKO_API_KEY=nexus-coingecko-api-key:latest,\
EIA_API_KEY=nexus-eia-api-key:latest,\
BEA_API_KEY=nexus-bea-api-key:latest,\
DEBANK_API_KEY=nexus-debank-api-key:latest,\
TATUM_API_KEY=nexus-tatum-api-key:latest,\
VAULTSFYI_API_KEY=nexus-vaultsfyi-api-key:latest,\
THEGRAPH_API_KEY=nexus-thegraph-api-key:latest,\
DATABASE_URL=nexus-marketdata-database-url:latest,\
MCP_OAUTH_SIGNING_KEY=nexus-mcp-oauth-signing-key:latest,\
NEXUS_API_KEYS=pwllc-nexus-api-key-digests:latest"
```

`--min-instances 1` keeps one instance always warm — it eliminates Cloud Run cold
starts (the regime endpoint dropped from ~8.6s cold to ~0.1s warm). Cost is the
idle instance running 24/7: ~$10–13/month at 1 vCPU + 1 GiB on the default
(CPU-throttled) billing. **Keep this flag on every deploy** — `gcloud run deploy`
preserves an existing min-instances when the flag is omitted, but include it so a
clean redeploy never silently drops back to scale-to-zero. Set to `0` to disable.

Direct VPC egress (`--network` / `--subnet` / `--vpc-egress`) plus
`--add-cloudsql-instances` is how the service reaches the private-only Cloud SQL
instance. The command prints the service URL; confirm it is reachable before
mapping DNS:

```bash
curl https://nexus-core-XXXXXX-uc.a.run.app/health
curl https://nexus-core-XXXXXX-uc.a.run.app/health/db
# Hosted native `/mcp` uses transparent OAuth when `MCP_OAUTH_SIGNING_KEY` is
# mounted. With `NEXUS_PUBLIC_MCP_PROFILE=demo`, an OAuth MCP `tools/list` should
# return only option_price, collar_book, classify_layer, health, and describe.

# Restricted REST/planning paths should 401 without the pw-api service key.
curl -i https://nexus-core-XXXXXX-uc.a.run.app/api/planning/tools
curl -H "Authorization: Bearer ${NEXUS_SERVICE_API_KEY}" \
  https://nexus-core-XXXXXX-uc.a.run.app/api/planning/tools
```

For an existing service where the source image is already current, the narrow
runtime-only update is:

```bash
gcloud run services update nexus-core \
  --region us-central1 \
  --update-env-vars "NEXUS_PUBLIC_MCP_PROFILE=demo,NEXUS_ACCESS_MODE=restricted" \
  --update-secrets "NEXUS_API_KEYS=pwllc-nexus-api-key-digests:latest"
```

Keep `MCP_OAUTH_SIGNING_KEY` mounted on the hosted public service unless the
explicit goal is to make `/mcp` unauthenticated. OAuth is compatible with the
demo profile and prevents the hosted transport from becoming a raw anonymous
HTTP tool endpoint.

### 4. Deploy the snapshot job (Cloud Run Job)

The daily benchmark snapshot runs as a Cloud Run **Job** built from the same
source, invoking `nexus-core snapshot`. Jobs use `--set-cloudsql-instances`
(note: **not** `--add-cloudsql-instances`, which is the service-only form) and
only need the database URL plus CoinGecko:

```bash
gcloud run jobs deploy nexus-snapshot-job \
  --source . \
  --region us-central1 \
  --command nexus-core \
  --args snapshot \
  --service-account nexus-core-run@pwllc-prod.iam.gserviceaccount.com \
  --network pwllc-prod-vpc \
  --subnet pwllc-prod-cloud-run-us-central1 \
  --vpc-egress private-ranges-only \
  --set-cloudsql-instances pwllc-prod:us-central1:nexus-marketdata \
  --set-secrets "DATABASE_URL=nexus-marketdata-database-url:latest,\
COINGECKO_API_KEY=nexus-coingecko-api-key:latest,\
FRED_API_KEY=nexus-fred-api-key:latest,\
MBOUM_API_KEY=nexus-mboum-api-key:latest,\
MARKETSTACK_API_KEY=nexus-marketstack-api-key:latest"
```

> **`FRED_API_KEY` is REQUIRED on the job, not optional.** The job runs two legs: the
> benchmark snapshot (CoinGecko) and the **regime snapshot**. The regime leg reads real
> rates, DXY and credit spreads from FRED. `SignalFetcher` resolves each macro signal as
> `_fetch_x() or default_x`, so a missing key does **not** raise — it silently substitutes
> neutral priors (`real_rates=1.5`, `dxy=100.0`, `vix=20.0`, `credit_spreads=150.0`).
> That is fine on the serving path and **not** fine here: the row is written as an
> observation, fed back as the next day's `prior_regime` through the anchor hysteresis, and
> becomes the permanent record every accuracy and calibration measure is derived from.
> `run_regime_snapshot` therefore refuses to write when the macro provider is unconfigured
> and exits non-zero so the scheduler retries. MBOUM/MARKETSTACK are the market-data
> fallbacks behind the keyless yfinance primary (gold/SPX, VIX).

Run it manually to verify:

```bash
gcloud run jobs execute nexus-snapshot-job --region us-central1
```

### 5. Schedule the snapshot (Cloud Scheduler)

A Cloud Scheduler job triggers the snapshot job daily at **01:00
America/New_York** using an OAuth service-account identity — **no static token**.
The scheduler SA needs `roles/run.invoker` on the job:

```bash
gcloud scheduler jobs create http nexus-daily-snapshot \
  --location us-central1 \
  --schedule "0 1 * * *" \
  --time-zone "America/New_York" \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/pwllc-prod/jobs/nexus-snapshot-job:run" \
  --http-method POST \
  --oauth-service-account-email nexus-core-run@pwllc-prod.iam.gserviceaccount.com
```

### 6. Map the custom domain

DNS is operator-controlled — run this once the service URL is confirmed healthy:

```bash
gcloud run domain-mappings create --service nexus-core --domain nexusmcp.site --region us-central1
```

`gcloud` prints the DNS records to add at the `nexusmcp.site` registrar. In
production, Cloudflare fronts the service: a methods rule blocks non-`GET`/`POST`/
`OPTIONS` requests and an edge rate-limit guards the cost endpoints, with the
origin behind a Cloud Run managed TLS certificate.

### Redeploy

Re-run the `gcloud run deploy nexus-core` command from step 3 (and
`gcloud run jobs deploy nexus-snapshot-job` from step 4 if job code changed) — each
builds and rolls out a new revision with zero-downtime traffic migration. The
Cloud Scheduler job persists across redeploys.

## Notes

- `/api/regime` performs a live multi-symbol fetch on a cold cache (~10-30s
  first call); results are cached for 15 minutes thereafter.
- Rate limiting is in-process and therefore per-instance — see
  [`src/nexus_core/app/ratelimit.py`](src/nexus_core/app/ratelimit.py). The
  limiter resolves the client IP spoofing-resistantly (`CF-Connecting-IP`, then
  the rightmost `X-Forwarded-For` entry).
- The database is private-only; persistence and `/api/benchmarks/history` return
  `503` when `DATABASE_URL` is unset. There are no credentials in config — all
  secrets live in Secret Manager.
- A GitHub Actions deploy workflow can be added once Workload Identity Federation
  is configured for the repository; until then deploys are run manually via the
  commands above.
