# Validation — nexus-core public deployment

Records the latest validation for the `nexus_core.app` HTTP API, MCP transport,
data providers, and public documentation/status surface.

## Automated tests

Focused local gate for the 2026-07-06 collar-book executable-fill update:

```bash
.venv/bin/ruff check \
  src/nexus_core/engine/pricing/collar_book.py \
  src/nexus_core/app/options.py \
  src/nexus_core/app/llms_txt.py \
  src/nexus_core/mcp/server/app.py \
  tests/test_pricing_collar_book.py \
  tests/test_options_routes.py \
  tests/test_mcp_server_tools.py
# All checks passed

.venv/bin/mypy --strict \
  src/nexus_core/engine/pricing/collar_book.py \
  src/nexus_core/app/options.py \
  src/nexus_core/app/llms_txt.py \
  src/nexus_core/mcp/server/app.py
# Success: no issues found in 4 source files

.venv/bin/python -m pytest \
  tests/test_pricing_collar_book.py::test_bid_ask_executable_credit_reports_fill_haircut \
  tests/test_pricing_collar_book.py::test_explicit_executable_net_credit_wins_over_bid_ask -q
# 2 passed in 0.71s

.venv/bin/python -c "... assemble_collar_book executable-fill assertions ..."
# engine executable collar_book ok

.venv/bin/python -c "... _collar_book_positions executable-input assertions ..."
# rest collar_book parser executable inputs ok

.venv/bin/python -c "... _parse_collar_book_positions executable-input assertions ..."
# mcp collar_book parser executable inputs ok

git diff --check
# clean
```

Known local caveat from this pass: pytest invocations that instantiate the
FastAPI route test or FastMCP server test harness hung before producing a result
and were interrupted. Direct parser checks for the edited REST/MCP input path
passed.

Focused local gate for the 2026-07-06 REST/JSON access-boundary update:

```bash
.venv/bin/ruff check \
  src/nexus_core/app/access_gate.py \
  src/nexus_core/app/main.py \
  src/nexus_core/app/mcp_mount.py \
  src/nexus_core/app/planning/gateway.py \
  src/nexus_core/app/llms_txt.py \
  src/nexus_core/app/landing.py \
  src/nexus_core/app/mcp_guide.py \
  src/nexus_core/mcp/server/app.py \
  tests/test_access_gate.py \
  tests/test_planning_gateway.py
# All checks passed

.venv/bin/mypy --strict \
  src/nexus_core/app/access_gate.py \
  src/nexus_core/app/main.py \
  src/nexus_core/app/mcp_mount.py \
  src/nexus_core/app/planning/gateway.py \
  src/nexus_core/app/llms_txt.py \
  src/nexus_core/app/landing.py \
  src/nexus_core/app/mcp_guide.py \
  src/nexus_core/mcp/server/app.py
# Success: no issues found in 8 source files

.venv/bin/python -c "... access_gate helper assertions ..."
# access gate helpers ok

.venv/bin/python -c "... create_app route-table assertions ..."
# planning REST aliases registered ok

.venv/bin/python -c "... build_server(tool_profile='demo') ..."
# demo MCP server build ok
```

Additional 2026-07-06 deploy-prep checks after the Terraform-managed Nexus key
secret was populated:

```bash
/tmp/nexus-core-venv/bin/ruff check \
  src/nexus_core/app/access_gate.py \
  src/nexus_core/app/main.py \
  src/nexus_core/app/mcp_mount.py \
  src/nexus_core/app/planning/gateway.py \
  src/nexus_core/app/options.py \
  src/nexus_core/engine/planning/tax.py \
  src/nexus_core/app/planning/tools.py \
  src/nexus_core/engine/pricing/collar_book.py \
  src/nexus_core/mcp/server/app.py \
  tests/test_access_gate.py \
  tests/test_planning_gateway.py \
  tests/test_mcp_server_tools.py \
  tests/test_options_routes.py \
  tests/test_pricing_collar_book.py
# All checks passed

/tmp/nexus-core-venv/bin/mypy --strict \
  src/nexus_core/app/access_gate.py \
  src/nexus_core/app/main.py \
  src/nexus_core/app/mcp_mount.py \
  src/nexus_core/app/planning/gateway.py \
  src/nexus_core/app/options.py \
  src/nexus_core/app/planning/tools.py \
  src/nexus_core/engine/planning/tax.py \
  src/nexus_core/engine/pricing/collar_book.py \
  src/nexus_core/mcp/server/app.py
# Success: no issues found in 9 source files

timeout 60s /tmp/nexus-core-venv/bin/python -m pytest tests/test_pricing_collar_book.py -q
# 23 passed in 0.76s

/tmp/nexus-core-lock-venv/bin/python -c "... NexusAccessGate ASGI checks ..."
# {"access_gate": "ok"}

/tmp/nexus-core-lock-venv/bin/python -c "... build_planning_router route aliases ..."
# /api/planning/tools + /api/planning/tools/{tool_id} registered; legacy /mcp/tools aliases retained

/tmp/nexus-core-lock-venv/bin/python -c "... NEXUS_PUBLIC_MCP_PROFILE=demo list_tools ..."
# demo tools: ["collar_book", "describe", "health", "option_price"]

git diff --check
# clean
```

Known local caveat from the deploy-prep pass: in this WSL/sandbox Python
environment, `anyio.to_thread.run_sync()` hangs after the worker returns, so
FastAPI sync-handler dispatch and FastAPI/Starlette `TestClient` route suites
hang locally even for a trivial app. Live `https://nexusmcp.site/health` serves
today from the Cloud Run image, and the Cloud Run Dockerfile uses the
hash-pinned `requirements-serve.lock` runtime instead of the unbounded local
resolver. Do not treat the local TestClient timeout as a route assertion
failure; rerun the committed pytest suites in CI or a non-sandboxed Python
environment for full route-harness coverage.

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
