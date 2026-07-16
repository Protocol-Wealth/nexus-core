# Validation — nexus-core public deployment

Records the latest validation for the `nexus_core.app` HTTP API, MCP transport,
data providers, and public documentation/status surface.

## 2026-07-15 ET — onchain accounting P0-P4 closeout

Commit `d528389` (PR #258, completing the P0-P4 source sequence from PRs
#254-#258) passed the repository's GitHub gates:

| Check | Evidence | Result |
|-------|----------|--------|
| ruff + mypy strict + pytest/coverage | Actions run `29451408938` | passed |
| SPDX headers | Actions run `29451408943` | passed |
| license compliance | Actions run `29451408891` | passed |
| CodeQL | Actions runs `29451408323`, `29451407938` | passed |

Cloud Run service generation 68 reports revision `nexus-core-00068-5pf` Ready
and serving 100% traffic. The deployed image digest is
`sha256:4f8e580ca543d884a674cbfbf8bac6d3db5d9e35617001854d0048d35b0e647e`.
The service configuration remains `NEXUS_PUBLIC_MCP_PROFILE=demo` plus
`NEXUS_ACCESS_MODE=restricted`.

| Live check | Result |
|------------|--------|
| `GET https://nexusmcp.site/health` | `200` — `{"status":"ok","service":"nexus-core","version":"0.1.0"}` |
| unauthenticated `GET https://nexusmcp.site/api/accounting/tools` | `401` — `{"error":"unauthorized","error_description":"Nexus API key required"}` |
| service-key `GET https://nexusmcp.site/api/accounting/tools` | `200` — contract `0.1.0`; `describe`, `price_history`, `decode_onchain_events`, `compute_cost_basis`, and `onchain_pnl_report` discovered |
| service-key `POST .../api/accounting/tools/onchain_pnl_report` | `200` — de-identified fixture returned realized gain `20`, the expected short-term/tax-year rollup, and the canonical disclaimer |

The unauthenticated check confirms the service-key boundary; the authenticated
catalogue and P4 fixture confirm deployed route behavior without exposing the
key. Accounting tools are not registered in native MCP yet; #259 owns that
adapter, and the hosted demo profile is expected to remain unchanged. No
end-to-end private ingestion or client statement workflow was validated by this
deployment. Issue #260 explicitly blocks statement wiring until the known
accounting-semantics and replay gaps are closed and methodology-reviewed.

## Automated tests

Docs/state closeout gate for the 2026-07-07 private-consumer-boundary update:

```bash
git diff --check
# clean

.venv/bin/ruff check src/nexus_core/app/landing.py tests/test_access_gate.py tests/test_app.py
# All checks passed!

.venv/bin/mypy --strict src/nexus_core/app/landing.py src/nexus_core/app/access_gate.py
# Success: no issues found in 2 source files

.venv/bin/python -c "... render_landing restricted-REST quickstart assertions ..."
# landing quickstart ok

.venv/bin/python -c "... access_gate sha256 digest assertion ..."
# digest auth ok
```

Live smoke refreshed during the same closeout:

| Check | Result |
|-------|--------|
| `GET https://nexusmcp.site/health` | `200` — `{"status":"ok","service":"nexus-core","version":"0.1.0"}` |
| unauthenticated `GET https://nexusmcp.site/api/planning/tools` | `401` — `{"error":"unauthorized","error_description":"Nexus API key required"}` |

GitHub state at closeout: local `main` was even with `origin/main` before this
docs update; nexus-core had only Dependabot PRs open (#205-#212) and roadmap
issues #197-#203 open. The first pushed closeout run failed in the
pytest/coverage step because two existing tests were stale for the restricted
REST boundary: the SHA-256 fixture did not hash `secret`, and the landing test
expected the legacy `/mcp/tools/glide_path` quickstart. The follow-up fix updates
those tests and the landing-page quickstart.

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

Live public status was checked after deploying commit `d3d0b2f` on
2026-07-06 ET / 2026-07-07 UTC. Cloud Run revision `nexus-core-00061-xhs` was
serving 100% traffic.

| Check | Result |
|-------|--------|
| `GET https://nexusmcp.site/health` | `200` — `{"status":"ok","service":"nexus-core","version":"0.1.0"}` |
| unauthenticated `GET https://nexusmcp.site/api/planning/tools` | `401` — `{"error":"unauthorized","error_description":"Nexus API key required"}` |
| authenticated `GET https://nexusmcp.site/api/planning/tools` | `200` — contractVersion `0.1.0`, 27 planning tools |
| unauthenticated `POST https://nexusmcp.site/mcp` | `401` — transparent OAuth bearer token required |
| transparent OAuth `/register` → `/authorize` → `/token` | `201` → `302` → `200`; token exchange succeeded with public `mcp` scope |
| OAuth MCP initialize → initialized → `tools/list` | `200` → `202` → `200`; tool list was `option_price`, `collar_book`, `health`, `describe`; provider-backed/full tools absent |
| Cloud Run service config | `NEXUS_PUBLIC_MCP_PROFILE=demo`, `NEXUS_ACCESS_MODE=restricted`, `NEXUS_API_KEYS` mounted from `pwllc-nexus-api-key-digests`; `MCP_OAUTH_SIGNING_KEY` remains mounted for hosted MCP compatibility |

GitHub status after the issue-sync pass: no open PRs; seven open issues
(#197-#203) track the outstanding and future-build lanes from the roadmap.

## Client-data check

`AUDIT.md` records the public-surface scan: nexus-core exposes public market,
macro, options, anonymous on-chain/LP, benchmark, and PII-free planning math.
It has no client data, no account surfaces, no suitability logic, no report
production workflow, no advisory workflow state, and no public write endpoint.
Remote MCP may use transparent OAuth for connector compatibility, but this is
not a client login or account authorization system.
