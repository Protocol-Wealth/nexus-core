# Validation — nexus-core public deployment

Records the latest validation for the `nexus_core.app` HTTP API, MCP transport,
data providers, and public documentation/status surface.

## Automated tests

Latest local gate, run 2026-07-01 from the repo venv:

```bash
.venv/bin/ruff check src/ tests/                 # All checks passed
.venv/bin/mypy --strict src/nexus_core/          # no issues in 151 source files
.venv/bin/python -m pytest -q                   # 1077 passed in 7.76s
git diff --check                                 # clean
```

Current test coverage includes:

- Application/documentation tests — landing page, MCP guide, `/llms.txt`,
  OpenAPI schema, OAuth/discovery surfaces, health, CORS/security headers,
  rate limiting, and MCP transport mount behavior.
- Provider tests — yfinance, MBOUM, MarketStack, CoinGecko, FRED, BEA, EIA,
  Treasury, DeBank, Tatum, The Graph, Merkl, vaults.fyi, Jupiter, and Deribit,
  with mocked transports and no live keys required.
- Engine/gateway tests — EMF regime/scoring, options/crypto-overlays, LP math,
  benchmark snapshots, and the 23-tool PII-free planning gateway/MCP handler
  set.

## Live smoke test

Live public status was checked on 2026-07-01:

| Check | Result |
|-------|--------|
| `GET https://nexusmcp.site/health` | `200` — `{"status":"ok","service":"nexus-core","version":"0.1.0"}` |
| `GET https://nexusmcp.site/mcp/tools` | `200` — contractVersion `0.1.0`, 23 planning tools |
| `GET https://nexusmcp.site/openapi.json` | `200` — public OpenAPI schema served with security headers |
| `GET https://nexusmcp.site/llms.txt` | `200` — agent site map served |
| `GET https://nexusmcp.site/.well-known/ai-disclosure.json` | `200` — generatedAt `2026-06-01T00:00:00Z` on the currently deployed artifact; local docs/source now update this to `2026-07-01T00:00:00Z` for the next deploy |
| OAuth metadata | `/.well-known/oauth-protected-resource/mcp` and `/.well-known/oauth-authorization-server` served successfully |

GitHub status after the issue-sync pass: no open PRs; seven open issues
(#197-#203) track the outstanding and future-build lanes from the roadmap.

## Client-data check

`AUDIT.md` records the public-surface scan: nexus-core exposes public market,
macro, options, anonymous on-chain/LP, benchmark, and PII-free planning math.
It has no client data, no account surfaces, no suitability logic, no report
production workflow, no advisory workflow state, and no public write endpoint.
Remote MCP may use transparent OAuth for connector compatibility, but this is
not a client login or account authorization system.
