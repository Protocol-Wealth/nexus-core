# Deploying nexus-core

This document describes how the public nexus-core surface — [nexusmcp.site](https://nexusmcp.site) —
is built and deployed. The deployable application lives in
[`src/nexus_core/app/`](src/nexus_core/app/); it exposes the regime engine and
market data as a public, read-only HTTP API plus an MCP-over-HTTP transport.

## What gets deployed

`nexus-core serve` (the container `CMD`) starts a [uvicorn](https://www.uvicorn.org/)
server hosting the FastAPI application from `nexus_core.app:create_app`:

| Path | Description |
|------|-------------|
| `GET /` | Landing page |
| `GET /health` | Liveness probe (rate-limit exempt) |
| `GET /docs` | Interactive OpenAPI / Swagger UI |
| `GET /openapi.json` | OpenAPI schema |
| `GET /api/regime` | Current macro regime classification |
| `GET /api/regime/signals` | Raw regime signal readings |
| `GET /api/market/quote/{symbol}` | Latest quote (stocks, ETFs, indices, crypto) |
| `GET /api/market/history/{symbol}` | OHLCV price history |
| `GET /api/economic/{series_id}` | FRED economic series |
| `POST /mcp` | Model Context Protocol endpoint |

There is **no authentication** and **no client data** — see [`AUDIT.md`](AUDIT.md).

## Configuration

All configuration is environment-driven. Every variable is optional; the app
runs without any of them (with reduced data coverage).

| Variable | Effect | Secret |
|----------|--------|--------|
| `FRED_API_KEY` | Enables `/api/economic/*` and macro precision for `/api/regime` | yes |
| `MBOUM_API_KEY` | Adds MBOUM as a market-data fallback | yes |
| `MARKETSTACK_API_KEY` | Adds MarketStack as a market-data fallback | yes |
| `COINGECKO_API_KEY` | Raises CoinGecko rate limits (works keyless too) | yes |
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
```

## Container build

```bash
docker build -t nexus-core .
docker run --rm -p 8080:8080 nexus-core
curl http://127.0.0.1:8080/health
```

## Cloud Run deploy (canonical)

Protocol Wealth infrastructure runs on Google Cloud. nexus-core deploys to
Cloud Run from source — Cloud Build builds the `Dockerfile` automatically.

**Prerequisites** (one-time, per project): `gcloud` CLI authenticated; the
Cloud Run, Cloud Build, and Artifact Registry APIs enabled.

### 1. (Optional) Create API-key secrets

```bash
printf '%s' "YOUR_FRED_KEY"        | gcloud secrets create nexus-fred-api-key --data-file=-
printf '%s' "YOUR_MBOUM_KEY"       | gcloud secrets create nexus-mboum-api-key --data-file=-
printf '%s' "YOUR_MARKETSTACK_KEY" | gcloud secrets create nexus-marketstack-api-key --data-file=-
printf '%s' "YOUR_COINGECKO_KEY"   | gcloud secrets create nexus-coingecko-api-key --data-file=-
```

### 2. Deploy

```bash
gcloud run deploy nexusmcp \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --memory 1Gi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 4 \
  --set-secrets "FRED_API_KEY=nexus-fred-api-key:latest,\
MBOUM_API_KEY=nexus-mboum-api-key:latest,\
MARKETSTACK_API_KEY=nexus-marketstack-api-key:latest,\
COINGECKO_API_KEY=nexus-coingecko-api-key:latest"
```

Omit `--set-secrets` entirely for a keyless first deploy. The command prints the
service URL (`https://nexusmcp-XXXXXX-uc.a.run.app`); confirm it is reachable
before mapping DNS:

```bash
curl https://nexusmcp-XXXXXX-uc.a.run.app/health
```

### 3. Map the custom domain

DNS is operator-controlled — run this once the service URL is confirmed healthy:

```bash
gcloud run domain-mappings create --service nexusmcp --domain nexusmcp.site --region us-central1
```

`gcloud` prints the DNS records to add at the `nexusmcp.site` registrar
(typically a `CNAME` / `A` / `AAAA` set). Cloud Run provisions a managed TLS
certificate automatically once the records resolve.

### Redeploy

Re-run the `gcloud run deploy` command from step 2 — it builds and rolls out a
new revision with zero-downtime traffic migration.

## Notes

- `/api/regime` performs a live multi-symbol fetch on a cold cache (~10-30s
  first call); results are cached for 15 minutes thereafter.
- Rate limiting is in-process and therefore per-instance — see
  [`src/nexus_core/app/ratelimit.py`](src/nexus_core/app/ratelimit.py).
- A GitHub Actions deploy workflow can be added once Workload Identity
  Federation is configured for the repository; until then deploys are run
  manually via the command above.
