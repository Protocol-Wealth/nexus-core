# Validation — nexus-core public deployment

Records the latest validation for the `nexus_core.app` HTTP API, MCP transport,
data providers, and public documentation/status surface.

## 2026-07-16 ET — native MCP accounting adapter implementation (#259)

Current source adapts the existing accounting handler registry into native MCP
full mode. No live deployment is claimed by this entry: production remains on
Cloud Run revision `nexus-core-00069-6m7` with
`NEXUS_PUBLIC_MCP_PROFILE=demo`, so its public MCP tool list is unchanged.

| Check | Result |
|-------|--------|
| focused full/demo registration, discovery, four representative handler calls, PII rejection, and stable input-error mapping | `4 passed, 33 deselected` |
| combined planning/accounting registration plus read-only annotations | `6 passed, 31 deselected` |
| shared REST/native-MCP historian identity | `1 passed` |
| non-route accounting contract/handler tests plus historian tests | `24 passed, 23 deselected` |
| `ruff check src/ tests/` | passed |
| `mypy --strict src/nexus_core/` | passed (`181` source files) |
| `git diff --check` | clean |
| full local `pytest -q` | could not complete: no output before the explicit 180-second timeout (exit `124`) |

The focused MCP tests inspect `tools/list` and invoke the exact
`FunctionTool.fn` callables registered by FastMCP. This avoids a known local
WSL/AnyIO runner issue while still validating the registration boundary and
adapter envelopes. As a control, the unchanged
`test_planning_tool_call_echoes_contract_version` test timed out under the same
local `server.call_tool` runner after 45 seconds (exit `124`). Exact-head GitHub
CI remains authoritative for the complete FastMCP/pytest suite and coverage
floor.

## 2026-07-16 ET — accounting contract 0.2.0 release closeout (#260)

PR #262 merged reviewed source head
`a142da610f48a2e82b89f3c4eaa12d1eda2519a5` as commit `70bd5d5` and deployed
that byte-identical tree to Cloud Run revision `nexus-core-00069-6m7` at 100%
traffic. Contract `0.2.0` is deployed; private client-statement use remains
blocked in `pw-api#789` on consumer compatibility plus CIO/IC/CCO methodology
approval, and the engine continues to return `statement_ready=false`.

| Check | Evidence | Result |
|-------|----------|--------|
| focused accounting engine, PnL, and decoder tests | local exact head | `90 passed` |
| non-route accounting gateway tests | local exact head | `15 passed, 23 deselected` |
| ruff + strict mypy + full pytest/coverage | Actions run `29518197955` | passed |
| SPDX headers | Actions run `29518199275` | passed |
| license compliance | Actions run `29518198242` | passed |
| CodeQL | Actions runs `29518190163`, `29518190175` | passed |
| exact-head standalone Codex review | source head `a142da6` | no major issues; all inline threads resolved |
| `git diff --check` | local exact head | clean |

The local full suite and FastAPI `TestClient` route harness hit the documented
WSL/AnyIO hang, so exact-head GitHub CI is authoritative for the complete route
suite and repository coverage floor. Focused stress evidence also covered
50,000 allocation cases, 20,000 lot-conservation cases, 10,000 multiplication
cases plus dual-model validation, 200 cross-Decimal-context replay cases, and
extreme-exponent handler checks.

Cloud Run reports revision `nexus-core-00069-6m7` Ready and serving 100% traffic.
The deployed image digest is
`sha256:781fcf198e9862723dced409a81958c36cbdadcf6b3ec558c71da9a130b30555`.
The service configuration remains `NEXUS_PUBLIC_MCP_PROFILE=demo` plus
`NEXUS_ACCESS_MODE=restricted`, with VPC, Cloud SQL, scaling, resources, and
secret bindings preserved.

| Live check | Result |
|------------|--------|
| `GET https://nexusmcp.site/health` | `200` — `{"status":"ok","service":"nexus-core","version":"0.1.0"}` |
| direct Cloud Run `GET /health` | `200` — same health body |
| unauthenticated `GET https://nexusmcp.site/api/accounting/tools` | `401` — `{"error":"unauthorized","error_description":"Nexus API key required"}` |

No production service-key value was read or extracted, so an authenticated
contract `0.2.0` handshake and consumer fixture were not run during this
closeout. That compatibility check remains in `pw-api#789`. Technical issue #260
is closed; native MCP registration remains separate issue #259, and the hosted
demo profile remains unchanged.

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
