# Validation — nexus-core public deployment

Records the validation performed on the nexusmcp.site rebuild (the
`nexus_core.app` HTTP API + MCP transport and the `nexus_core.data` providers).

## Automated tests

Full hermetic suite — **137 passed**, no network calls, no API keys:

```bash
pip install -e ".[dev,market,mcp]"
pytest -q          # 137 passed
ruff check src/ tests/
mypy src/nexus_core/
```

`ruff` and `mypy` are clean on all files added by the rebuild (`data/http.py`,
`data/market/*`, `data/macro/*`, `app/*`, `cli.py`). Pre-existing `ruff` /
`mypy` findings in unrelated modules are unchanged — out of scope for this work.

Coverage added:

- 33 data-provider tests — yfinance (injected ticker factory), MBOUM /
  MarketStack / CoinGecko / FRED (`httpx.MockTransport`), composite fallback.
- 14 application tests — landing page, health, OpenAPI schema, quote / history
  / economic / regime endpoints, 404 / 503 paths, CORS headers, per-IP rate
  limiting, and the MCP transport mount.

## Live smoke test

`nexus-core serve` run locally; endpoints exercised against live providers:

| Check | Result |
|-------|--------|
| `GET /health` | `200` — `{"status":"ok",...}` |
| `GET /` | `200` — landing page (`text/html`) |
| `GET /docs` | `200` — Swagger UI |
| `GET /openapi.json` | `200` — all six REST paths present, title `Nexus Core 0.1.0` |
| `GET /api/market/quote/AAPL` | `200` — live yfinance quote |
| `GET /api/market/quote/bitcoin` | `200` — live CoinGecko quote (composite fell through yfinance → CoinGecko) |
| `GET /api/regime` | `200` — live classification (regime + confidence + 6 signal statuses) |
| `GET /api/economic/DGS10` | `503` — correct graceful response when `FRED_API_KEY` is unset |
| `POST /mcp` | mounted — `307` redirect to the MCP transport sub-app |

The composite provider's ordered fallback was observed working end-to-end: a
`bitcoin` lookup missed on yfinance/MBOUM/MarketStack and was served by
CoinGecko, with no error surfaced to the caller.

## Keyless vs keyed

- **Keyless** (no environment configuration): yfinance market data and
  CoinGecko crypto data are live; regime classification runs with neutral
  macro fallbacks. Validated above.
- **Keyed**: FRED, MBOUM, and MarketStack require API keys. Their adapters are
  covered by hermetic tests but have **not** been exercised against the live
  APIs. Recommended post-deploy spot-check once secrets are configured:
  - `GET /api/economic/DGS10` returns a numeric value (FRED).
  - `GET /api/market/quote/AAPL` still succeeds with MBOUM / MarketStack keys set.
  - **MBOUM field mapping** — the quote/history extractors are inferred from
    MBOUM's documented Yahoo-proxy envelope. Confirm `regularMarketPrice` (or
    a fallback field) resolves on a live key; the extractor is permissive but
    the exact field name is unverified against a live response.

## Client-data check

`AUDIT.md` records the scan confirming the deployment exposes market and
economic data only — no client data, no authentication, no advisory surfaces.
The served responses (`/api/*`) contain only market/economic data and
analytical signals; no `client_id` / `advisor_id` / auth fields appear in any
response shape.
