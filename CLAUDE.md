# nexus-core — open-source regime-adaptive financial analysis engine

> Repo: `Protocol-Wealth/nexus-core` · License: Apache 2.0 · Patent Pending: USPTO #64/034,229 · OIN member.
> Open-source extraction of the [Protocol Wealth research engine](https://nexusmcp.site); nothing in this repo is client-specific or proprietary to PW.

**Current state (2026-07-17 ET — accounting v2 operationally approved; consumer enablement in progress):**
- **Live deployment:** commit `e5f4d84` is on `origin/main`; Cloud Run revision
  `nexus-core-00070-zhx` is Ready and serves 100% traffic. Custom-domain, direct,
  and regional Cloud Run `/health` returned `200`, `/health/db` returned `200`,
  and unauthenticated `/api/accounting/tools` returned the expected service-key
  `401` under `NEXUS_ACCESS_MODE=restricted`.
- **Deployed accounting contract `0.2.0`:** P0-P4 are merged through PRs
  #254-#258 and the #260 hardening is merged through PR #262. The
  REST gateway exposes `describe`, `price_history`, `decode_onchain_events`,
  `compute_cost_basis`, and `onchain_pnl_report`. Inputs are de-identified
  public-chain/market facts with opaque references; identity-shaped keys fail
  closed, unknown price/basis stays explicit, and accounting/tax disclaimers are
  canonical. The deployed image was built from the reviewed merge tree. No
  production service-key value was read during closeout, so an authenticated v2
  version handshake was not rerun.
- **Accounting methodology `2.0.0`:** the deployed contract scopes FIFO by account,
  handles explicitly linked same-owner transfers without gain, allocates fees
  once plus any separate fee-asset disposal, uses calendar holding periods,
  conserves authoritative basis/fee totals across partial lots and transfers,
  supports full-history or method-pinned complete opening-state replay, and
  returns root-lot/event/transaction/evidence/price lineage with structured
  completeness. Confirmed external inbound receipts default to receipt-time
  fair-market-value basis with price provenance; same-owner transfers carry
  original basis, while external outbound, unknown, and ambiguous DeFi
  treatments fail closed. Calculation completeness is not a closing-valuation or deliverable
  attestation; the private composer applies section-specific gates. See
  `docs/ONCHAIN-ACCOUNTING.md`.
- **Transport boundary:** the deployed image reuses the accounting handler
  registry and configured REST historian to register `price_history`,
  `decode_onchain_events`, `compute_cost_basis`, and `onchain_pnl_report` in
  native MCP full mode. It preserves recursive identity rejection, contract and
  disclaimer envelopes, and stable `ToolError` mapping. Accounting's internal
  `describe` is omitted; the native top-level `describe` reports the accounting
  category and contract `0.2.0`. Production stays on
  `NEXUS_PUBLIC_MCP_PROFILE=demo`; live OAuth `tools/list` returned
  `classify_layer`, `collar_book`, `describe`, `health`, and `option_price`, with
  accounting absent.
- **Private boundary:** P0-P4 are calculation substrate, not private delivery controls.
  Custodian ingestion, wallet/client linkage, statement assembly/rendering,
  advisor review, release, tax-return preparation, and books-and-records retention
  remain in the private `pw-api`/PWOS plane. Issues #248, #259, and #260 are
  closed as technically complete; `pw-api#789` owns consumer compatibility and
  private delivery. CCO/CIO/CTO approved methodology 2.0/FIFO for operational
  use on 2026-07-17, so complete bounded calculations may be statement-ready;
  post-deployment partner review is evidence rather than a runtime gate.
- **Validation:** exact source-head CI run `29522873818` passed ruff, strict
  mypy, and `1563` tests at `89.78%` coverage; SPDX, license-compliance, and both
  CodeQL checks also passed. Standalone Codex accepted exact head `87afc45`, all
  inline review threads were resolved before merge, and the complete live OAuth
  MCP handshake passed after deployment.

**Historical snapshot (2026-07-10 ET — public agent-discovery + Markdown negotiation):**
- **Deployed:** Cloud Run revision `nexus-core-00064-fqx` serves 100% traffic on
  `nexusmcp.site` (behavior-verified). The agent-discovery well-known surfaces are
  live (`#232`): an SEP MCP Server Card at `/.well-known/mcp/server-card.json`, an
  RFC 9727 API catalogue at `/.well-known/api-catalog`, `robots.txt` (AI-crawler
  rules + Content-Signal + sitemap pointer), `sitemap.xml`, and an RFC 8288 `Link`
  header on the landing page. isitagentready.com scores the site **71 / Level 2
  Bot-Aware**. Source: `app/agent_discovery.py`, wired in `app/main.py`.
- **Markdown content negotiation (`#233`):** `GET /` returns a Markdown rendering
  when a client sends `Accept: text/markdown`; HTML stays the default for browsers.
  The parser honors RFC 9110 quality values (a `q=0` rejects Markdown; Markdown is
  chosen only when named more specifically than a bare `*/*`), and `Vary: Accept`
  keeps the Cloudflare edge from cross-serving. Source:
  `app/landing.py::accept_prefers_markdown` + `render_landing_markdown`.
- **Card `serverInfo.description`:** the MCP Server Card carries a stable,
  profile-agnostic engine description that does NOT overclaim MCP tool exposure
  (the demo transport exposes only `option_price`/`collar_book`/`classify_layer`/
  `health`/`describe` — all closed-world, no live vendor call);
  the exact tool set is deferred to the `instructions` field + `tools/list`.
  `policy.posture` stays the canonical `disclaimers.TERSE`. The
  `protocolwealthllc.com` mirror of this card is reconciled field-for-field
  (pw-website `#290`/`#291`).
- **N/A for this read-only, publish-not-crawl surface** (deliberate, not gaps):
  Auth.md, Web Bot Auth, Agent Skills (that modality is AskPWBot's on pw-website),
  WebMCP, agentic commerce.

**Historical snapshot (2026-07-07 ET — private consumer boundary closeout):**
- **Access model:** hosted Nexus is a split surface. Native `/mcp` remains a
  public OAuth-compatible demo endpoint with `NEXUS_PUBLIC_MCP_PROFILE=demo`.
  REST/JSON calculation paths (`/api/*`, `/api/planning/tools/*`, legacy
  `/mcp/tools/*`) are gated by `NEXUS_ACCESS_MODE=restricted` +
  `NEXUS_API_KEYS`; `pw-api` supplies `NEXUS_SERVICE_API_KEY` server-to-server.
  PWOS/PWPortal browser clients must not carry Nexus credentials.
- **Private research ingestion handoff:** PWOS `/market-data` owns CSV/XLSX
  research-screen ingestion. PR #993 in `pw-os-v2` is merged and advisor-verified
  with `Saved 380 research rows (7c30414f)`. Raw Seeking Alpha workbooks,
  Schwab/custodian files, client assignments, tracking records, and chat
  attachments stay private in PWOS/pw-api. Nexus may receive only de-identified
  candidate symbols, screened fields, and caller-supplied option-chain facts for
  public-safe calculation.

**Historical snapshot (2026-07-06 ET / 2026-07-07 UTC — restricted REST + demo MCP):**
- **Live deployed:** commit `d3d0b2f` is on `origin/main`; Cloud Run revision
  `nexus-core-00061-xhs` serves 100% traffic. Hosted Nexus keeps transparent
  OAuth active for `/mcp`, runs `NEXUS_PUBLIC_MCP_PROFILE=demo`, and gates
  `/api/*`, `/api/planning/tools/*`, and legacy `/mcp/tools/*` with
  `NEXUS_ACCESS_MODE=restricted` + `NEXUS_API_KEYS`. Anonymous
  `/api/planning/tools` returns 401; the pw-api service bearer key returns the
  27-tool planning contract; OAuth MCP `tools/list` returns only
  `option_price`, `collar_book`, `health`, and `describe` (plus `classify_layer`
  as of the durability-layer surface — pure compute over the published EMF layer
  maps, no vendor call).
- **Collar-book executable-fill update:** the multi-name collar-book worksheet
  accepts per-share executable pricing (`executable_net_credit` or `call_bid`
  minus `put_ask`) through the engine plus REST/MCP parsers and reports
  `stock_price`, `shares`, per-line `fill_haircut`, executable income/yield,
  and portfolio-level executable yield only when every held line has executable
  pricing. This is worksheet arithmetic over caller-supplied
  public-safe/pre-screened data; it is not a live-chain attestation, custodian
  execution record, client-specific recommendation, or order surface.
- **Validation run:** targeted collar-book engine, route, and MCP parser tests
  plus strict mypy/ruff on the touched source passed; full FastAPI TestClient
  route suites hit a local WSL/sandbox anyio threadpool hang, so CI or a
  non-sandboxed Python environment remains the full route-harness gate.

**Historical snapshot (2026-07-01 — docs/status audit):**
- **Live deployment verified:** `https://nexusmcp.site/health` returns `{"status":"ok","service":"nexus-core","version":"0.1.0"}` and `https://nexusmcp.site/mcp/tools` returns contractVersion `0.1.0` with **23 planning tool ids**: `monte_carlo_decumulation`, `analyze_goals`, `project_cash_flow`, `glide_path`, `tax_aware_withdrawal`, `correlation_matrix`, `capital_market_assumptions`, `regime_return_generator`, `roth_conversion`, `sequence_of_returns_stress`, `rmd`, `tax_bracket_headroom`, `social_security_claiming`, `regime_conditioned_swr`, `portfolio_xray`, `optimize_allocation`, `fire`, `risk_metrics`, `rebalance`, `build_planning_report`, `irmaa_headroom`, `analyze_roth_conversion`, and `sequence_conversions`. GitHub has **no open PRs** and seven open issues (#197-#203) tracking public-safe planning/report extraction, planning assumptions provenance, LP/indexer expansion, crypto-options follow-ups, agent analytics, governance/tooling cleanup, and equity-research gates.
- **Dependency status:** `requirements-serve.lock` pins `pandas==2.3.3`; keep `pyproject.toml` on `pandas>=2.2,<3.0` until `alphalens-reloaded` supports pandas 3.x. Dependabot's pandas 3.x bump conflicted with the documented `[all]`/`[backtest]` installability boundary.

**Historical snapshot (2026-06-24 — Guyton-Klinger dynamic withdrawals):**
- **`monte_carlo_decumulation` gained an optional `guardrails` config (Guyton-Klinger dynamic withdrawals).** When supplied, the simulation replaces the static `net_spend_by_year` draw (from the first decumulation year onward) with a path-dependent withdrawal governed by the three GK rules — the withdrawal rule (inflation raise, frozen after a down year when the rate is elevated), the capital-preservation rule (cut when the rate climbs `band` above the path's initial rate; suspended in the final `preservationFinalYears`), and the prosperity rule (raise when the rate falls `band` below). The rules run **vectorized across paths** in the existing year-loop (a `_guardrail_step` helper + a `GuardrailParams` dataclass in `engine/planning/monte_carlo.py`), so the non-guardrail path is **byte-identical** to before. The response gains `withdrawalRule` / `spendingByYear` (p10/p50/p90 realized-spend bands) / `guardrailActivity` only when `guardrails` is set. Gateway parsing + validation in `app/planning/tools.py` (`guardrails` body field). `mypy --strict` + `ruff` clean; +13 tests; full suite green. This is the engine half — the pwos chat-tool/report wiring (passing `guardrails`) is the follow-on consumer change.

**Historical snapshot (2026-06-21 — goal engine reconciliation):**
- **The prior dirty `goals.py` work is merged on main via PR #174, and PR #175 adds priority/shared-pool allocation.** `analyze_goals` is now the deterministic per-goal funding foundation plus the first shared-pool priority allocator. Future L1 Goal Graph work should extend this implementation rather than build beside it: persisted goal-analysis artifacts, solve-for, temporal waterfall behavior, and richer assumption/effective-input echoes belong on top of the existing tested goal logic. Keep client identity, advisor review, audit ledger, and intake conversion in pw-api/PWOS, not in nexus-core.

## What This Is

Python 3.12 package — a regime-adaptive financial-analysis + DeFi/market-data engine. It serves a **read-only HTTP API** (FastAPI) with an **MCP-over-HTTP transport** mounted at `/mcp`, so any MCP-compatible AI client (Claude, GPT, Gemini) can call a public demo tool surface without re-implementing financial domain logic. Production consumers should use the REST/JSON endpoints through an authenticated service boundary. The hosted MCP transport may use transparent OAuth for compatible clients, with no login.

Built and tested in production by Protocol Wealth LLC (SEC-registered RIA, CRD #335298). The public deployment at [nexusmcp.site](https://nexusmcp.site) runs the `nexus_core.app` surface from **this** repository, on **Google Cloud Run** (Cloudflare → Cloud Run); see [`DEPLOY.md`](DEPLOY.md). Version `0.1.0`; CI-gated test suite (`ruff` + `mypy --strict` + `pytest`, 80% coverage floor). The README's *Status* section is the source of truth on maturity — this is an alpha framework. Some subpackages are scaffold (`__init__.py` only); check the actual module contents before assuming an API exists.

Sibling: [`pwos-core`](https://github.com/Protocol-Wealth/pwos-core) — TypeScript compliance primitives. **Math + analytical engine lives here; data shapes + audit/compliance primitives live in pwos-core.** Do not port primitives across that boundary.

## Repo Structure

```
nexus-core/
├── src/nexus_core/
│   ├── app/                  # Public HTTP API + MCP-over-HTTP deployment (nexusmcp.site)
│   │   ├── main.py           # create_app() — wires providers, engine, routers, CORS, rate limit, /mcp
│   │   ├── routes.py         # /health, /api/regime[/signals], /api/market/*, /api/economic/*, /api/usage
│   │   ├── scoring.py        # /api/score/{ticker} router
│   │   ├── options.py        # /api/options/* router (overlays, collar worksheets, MBOUM chains, Deribit crypto options)
│   │   ├── wallet.py         # /api/wallet/{address} router (DeBank)
│   │   ├── chain.py          # /api/chain/* router (Tatum multi-chain native balances)
│   │   ├── vaults.py         # /api/vaults[/chains] router (vaults.fyi)
│   │   ├── lp.py             # /api/lp/* router (multi-chain Uniswap V3 analytics + vs-benchmark)
│   │   ├── solana.py         # /api/solana/price[s] router (Jupiter v3 SPL token USD prices)
│   │   ├── benchmarks.py     # /api/benchmarks[/series] router (on-demand CoinGecko)
│   │   ├── snapshots.py      # /api/benchmarks/history router (persisted snapshots)
│   │   ├── landing.py        # / landing page
│   │   ├── mcp_mount.py      # build_mcp_app() — FastMCP sub-app for /mcp
│   │   ├── mcp_oauth.py      # transparent OAuth 2.1 / PKCE shim for remote MCP clients
│   │   └── ratelimit.py      # in-process per-IP limiter (spoofing-resistant client IP)
│   ├── engine/
│   │   ├── regime/           # RegimeEngine: signals, signal_fetcher, classifier, hysteresis, thresholds, dampener, codes
│   │   ├── scoring/          # 8-check EMF scoring (emf/ submodule) + tiers, attribution, enhancements, formatter
│   │   ├── pricing/          # Black-Scholes + options overlays + collar-book worksheet math
│   │   ├── lp/               # uniswap_v3.py — pure CLMM math (tick math, exact IL, fee APR); protocol-agnostic, reused across chains
│   │   ├── benchmarks.py     # base-100 + buy-and-hold hold-strategy compositions
│   │   ├── optimization/     # PyPortfolioOpt + Riskfolio-Lib + Black-Litterman wrappers (extra)
│   │   └── risk/             # empyrical/pyfolio wrappers (scaffold; extra)
│   ├── data/
│   │   ├── http.py           # shared sync httpx helpers
│   │   ├── providers.py      # MarketDataProvider / MacroDataProvider protocols
│   │   ├── db.py             # asyncpg pool + is_configured()/ping() (private Cloud SQL)
│   │   ├── snapshots.py      # daily benchmark-price snapshot persistence
│   │   ├── market/           # coingecko, mboum, marketstack, yfinance providers + cache + composite + usage tracker
│   │   ├── macro/            # fred, bea, eia, treasury
│   │   ├── edgar/            # edgartools wrapper + SEC fundamentals
│   │   ├── derivatives/      # deribit (crypto options)
│   │   └── onchain/          # debank, tatum, thegraph, merkl, vaultsfyi, defillama, jupiter
│   ├── jobs/
│   │   └── daily_snapshot.py # run() — Cloud Run Job entrypoint (benchmark snapshot)
│   ├── mcp/server/           # FastMCP server: build_server() + @mcp.tool() registry
│   ├── ai/ compliance/ planning/ rebalancing/   # scaffold subpackages (FinBERT wrapper exists; rest __init__-only)
│   └── cli.py                # nexus-core CLI — serve / mcp / snapshot
├── tests/                    # pytest suites — match source files (test_<module>.py)
├── examples/                 # Runnable examples (run without network credentials)
├── docs/
│   ├── ARCHITECTURE.md       # Signal ensemble, regime states, scoring checks
│   ├── PATENT.md             # USPTO #64/034,229 detail + defensive posture
│   ├── attribution.md        # Per-capability provenance + license posture
│   └── CROSS-LINK-PWOS-CORE.md
├── DEPLOY.md                 # Cloud Run web service + snapshot Job + Scheduler procedure
└── .github/                  # workflows/license-compliance.yml + dependabot.yml (pip + actions, weekly)
```

## Tech Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12+ (`requires-python = ">=3.12"`) |
| HTTP I/O | **sync** `httpx` — handlers are sync `def`, FastAPI threadpools them (providers block) |
| Persistence | `asyncpg` → private Cloud SQL (Postgres 16); degrades to 503 when `DATABASE_URL` unset |
| Test runner | pytest 9.x (asyncio_mode = auto) — markers: `unit`, `integration`, `slow`, `live` |
| Lint / type | ruff (line-length 100) + `mypy --strict` |
| Validation | pydantic v2 (boundary validation only) |
| Build | setuptools + wheel via `pyproject.toml` |
| MCP transport | FastMCP (`@mcp.tool()`), mounted at `/mcp` |
| Web framework | FastAPI + uvicorn |
| Hosting | Google Cloud Run (Cloudflare → Cloud Run), region `us-central1` |
| CI | GitHub Actions — `ci.yml` (ruff + `mypy --strict` + pytest, 80% coverage floor); license-compliance scan; SPDX-header check; CodeQL (auto-config) |
| License | Apache 2.0 + USPTO #64/034,229 defensive patent + OIN member |

## Development

```bash
pip install -e ".[serve]"         # Deployed surface (market + mcp extras) — what nexusmcp.site runs
pip install -e ".[dev]"           # Dev tooling only (pytest, pytest-asyncio, pytest-cov, ruff, mypy, pip-licenses)
pip install -e ".[all]"           # All capability extras (heavy: torch, transformers, QuantLib, zipline)
pip install -e "."                # Core only (regime + scoring + market/macro/onchain HTTP clients)

pytest                            # Full suite (CI-gated)
pytest tests/test_regime_engine.py
ruff check src/ tests/
mypy --strict src/nexus_core/
```

Use modular installs in CI — `[all]` pulls heavy AI deps. Modular install patterns are documented in [README § Installation](README.md#installation).

### Run modes (`nexus-core` CLI)

```bash
nexus-core serve [--host 0.0.0.0 --port 8080]   # Public HTTP API + MCP-over-HTTP — container/Cloud Run entrypoint
nexus-core mcp                                   # MCP server over stdio (Claude Desktop / local clients)
nexus-core snapshot                              # Daily benchmark-price snapshot — Cloud Run Job entrypoint
nexus-core --version
```

`serve` honors `HOST`/`PORT` env (Cloud Run supplies `PORT`). `snapshot` writes the day's benchmark prices to Cloud SQL and exits.

## Endpoint Surface (public, read-only)

`GET` unless noted. Cache lifetimes are set in handlers and respected by the Cloudflare edge.

| Path | Notes |
|------|-------|
| `/`, `/health`, `/health/db` | Landing, liveness, DB connectivity probe |
| `/api/regime`, `/api/regime/signals` | EMF regime classification + raw signal readings (~15 min cache) |
| `/api/score/{ticker}` | 8-check EMF scoring (SEC EDGAR fundamentals) |
| `/api/layer/{ticker}`, `/api/layers` | EMF durability-layer classification (L1..L7) — display name, horizon, λ ceiling, per-regime target weights, and the rule that decided it (ticker map / asset-class route / sector keyword / sector default / UNCLASSIFIED). `/api/layers` publishes the whole stack. Same view as the MCP `classify_layer` tool. Taxonomy: `engine/scoring/emf/layers.py` |
| `/api/market/quote/{symbol}`, `/api/market/history/{symbol}` | Composite market data (yfinance → MBOUM → MarketStack → CoinGecko) |
| `/api/economic/{series_id}` | FRED series (503 when `FRED_API_KEY` unset) |
| `/api/options/price`, `/api/options/overlay/{covered-call,cash-secured-put,collar}` | Black-Scholes educational overlays |
| `/api/options/overlay/collar-screen`, `/api/options/overlay/collar-book`, `/api/options/equity/{symbol}/expirations`, `/api/options/equity/{symbol}/chain?expiration=` | Equity collar screen/book worksheets and MBOUM-backed listed-option expirations/chains. `collar-book` can report executable-fill haircuts from caller-supplied bid-side call / ask-side put pricing. Worksheet only: no orders, no advice |
| `/api/options/crypto/currencies`, `/api/options/crypto/{currency}/instruments`, `/api/options/crypto/instrument/{name}` | Deribit crypto options on **BTC, ETH** (coin-settled inverse) + **SOL, XRP, TRX, AVAX** (USDC-settled linear, read via Deribit's `USDC` umbrella + prefix filter). Keyless |
| `/api/options/crypto/{currency}/{covered-call,covered-call-chain,iv-term-structure,vol-skew,regime-overwrite,protective-put,collar}` (GET) + `/ladder`, `/roll`, `/book/mtm`, `/book/scenario` (POST) | Settlement-aware covered-call **overwriting + hedge suite** — coin-yield, chain ranking, IV term structure, **call-side vol skew** (IV + vega by strike), **regime-conditioned strike** (live EMF tilt + `defensiveness` knob), protective put/collar, calendar ladder, roll, book MTM + Greeks, spot/IV stress. Engine in `engine/pricing/{crypto_overlays,option_chain,overwrite,options_book,regime_overlay,skew}.py`. Illustration only; ISDA/CSA/execution/custody out of scope |
| `/api/wallet/{address}` | Anonymous EVM wallet balance (DeBank) |
| `/api/chain/chains`, `/api/chain/balance/{chain}/{address}`, `/api/chain/native/{address}` | Multi-chain native balances (Tatum: EVM `eth_getBalance` + Solana `getBalance`) |
| `/api/vaults`, `/api/vaults/chains` | DeFi vault discovery (vaults.fyi v2) |
| `/api/lp/chains`, `/api/lp/uniswap-v3/{chain}/positions?owner=`, `/api/lp/uniswap-v3/{chain}/{token_id}/analytics`, `/api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark` | Uniswap V3 on **ethereum, base, optimism, polygon**. `positions?owner=` enumerates the open positions an address owns (pool/range/in-range/token amounts/uncollected fees, **token units, no USD**); the by-`token_id` `analytics` adds value, in-range, **exact IL-vs-HODL**, fee-APR, uncollected fees (RPC `tokensOwed` via Tatum), Merkl reward APR → total APR; `vs-benchmark` adds hold-strategy benchmark returns over a window. Analytics USD prices are **required query params**. (The Graph + RPC + Merkl) — Arbitrum NOT supported (its published subgraph ID uses an incompatible schema) |
| `/api/lp/aerodrome/{token_id}/analytics` | Aerodrome Slipstream position on **Base**, read on-chain via Tatum RPC (`data/onchain/slipstream.py`: NFPM `positions` → CLFactory `getPool` → CLPool `slot0` → `decimals`/`symbol`) — value, in-range, token amounts, uncollected fees. Same pure `engine/lp/uniswap_v3.py` math. USD prices **required**. `data_mode: onchain_rpc` — IL, fee APR, AERO gauge APR null/zero (Envio = follow-on for full coverage) |
| `/api/solana/price/{mint}`, `/api/solana/prices?mints=` | Solana SPL token USD prices (Jupiter v3, keyless — no API key) |
| `/api/benchmarks`, `/api/benchmarks/series?days=`, `/api/benchmarks/history?days=` | Base-100 hold-strategy returns (BTC/ETH/SOL + ETH-USDC 50/50,60/40,70/30 + ETH-BTC 50/50; USDC held at $1; buy-and-hold). `/series` on-demand from CoinGecko; `/history` from persisted daily snapshots |
| `/api/usage` | Provider usage/quota report (non-sensitive; no keys, no client data) |
| `/mcp` | MCP-over-HTTP transport (FastMCP) — exempt from the rate limiter. Full mode registers research tools + `health`/`describe`/`get_quotes`, the current-source 33 planning tools, and equity options helpers including `collar_book`; demo mode registers closed-world demo tools only. Every tool is `readOnlyHint` + carries the disclaimer |
| `/api/planning/tools`, `POST /api/planning/tools/{id}` | Planning JSON gateway (pw-api / pwplan-core contractVersion `0.1.0`, PII-free). Legacy `/mcp/tools` aliases remain |
| `/docs`, `/openapi.json`, `/mcp-guide`, `/llms.txt`, `/.well-known/security.txt` | OpenAPI (servers + tags), MCP setup guide, agent site map, RFC 9116 disclosure |

Quote responses carry `as_of`/`source`/`market_status`; FRED carries `as_of`/`source`. All
external integrations degrade gracefully to `None`/empty/503 when their key is absent.

## Persistence & Infra

- **Cloud SQL** `nexus-marketdata` (Postgres 16, **private IP only** on `pwllc-prod-vpc`, backups + deletion protection). The web service reaches it via **Direct VPC egress** (`--network=pwllc-prod-vpc --subnet=pwllc-prod-cloud-run-us-central1 --vpc-egress=private-ranges-only`) + `--add-cloudsql-instances` + `roles/cloudsql.client`.
- **Daily benchmark snapshots** are written by a **Cloud Run Job** (`nexus-snapshot-job`, runs `nexus-core snapshot`) triggered by **Cloud Scheduler** (`nexus-daily-snapshot`, daily 01:00 America/New_York) under an **OAuth service-account identity** (no shared secret). The snapshot is NOT an HTTP route — there are no public write endpoints.
- **Secrets** live only in Google Secret Manager: `nexus-{fred,mboum,marketstack,coingecko,eia,bea,debank,tatum,vaultsfyi,thegraph}-api-key` + `nexus-marketdata-database-url`. Runtime SA `nexus-core-run@pwllc-prod`.
- `DEPLOY.md` owns the exact `gcloud run deploy` / `gcloud run jobs deploy` / `gcloud scheduler jobs create` commands. Note: the Job uses `--set-cloudsql-instances` (NOT `--add-`); the Scheduler uses `--oauth-service-account-email` (NOT a static token).

### Environment variables

`FRED_API_KEY`, `MBOUM_API_KEY`, `MARKETSTACK_API_KEY`, `COINGECKO_API_KEY`, `EIA_API_KEY`, `BEA_API_KEY`, `DEBANK_API_KEY` (`/api/wallet`), `TATUM_API_KEY` (`/api/chain` + LP uncollected fees), `VAULTSFYI_API_KEY` (`/api/vaults`), `THEGRAPH_API_KEY` (`/api/lp`), `DATABASE_URL` (persistence + `/api/benchmarks/history`; 503 when unset), `MCP_OAUTH_SIGNING_KEY` (optional stateless transparent OAuth for hosted `/mcp`; omit locally to keep `/mcp` open), `NEXUS_PUBLIC_MCP_PROFILE` (`full` default or `demo`), `NEXUS_ACCESS_MODE` (`public` default or `restricted`), `NEXUS_API_KEYS` (raw keys or `sha256:<hex>` digests), `NEXUS_RATE_LIMIT_PER_MIN` (default 60), `NEXUS_CORS_ORIGINS` (default `*`), `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` (optional response cache; unset means cache-free, never a 503).

## Security Posture

- **Public read-only. No public write endpoints** — the daily snapshot is a Cloud Run Job, not an HTTP route.
- **Private-only Cloud SQL** — no public IP, reached only over the VPC.
- **In-process rate limiter** (`app/ratelimit.py`) resolves the client IP spoofing-resistantly (`CF-Connecting-IP`, else rightmost `X-Forwarded-For`); `/health` and `/mcp` are exempt.
- **Cloudflare** methods rule blocks non-GET/POST/OPTIONS + edge rate-limit on cost endpoints.
- **Transparent MCP OAuth** (`app/mcp_oauth.py`) is stateless and anonymous when `MCP_OAUTH_SIGNING_KEY` is set: Dynamic Client Registration + PKCE + HMAC-signed access/refresh tokens satisfy remote-MCP client handshakes without user accounts or privileged scopes.
- **Secrets only in Secret Manager** — no credentials in config or code.

## Conventions

- **SPDX header on every `.py` file.** Canonical 2-line block, prepended above any module docstring or import:
  ```python
  # SPDX-License-Identifier: Apache-2.0
  # Copyright 2026 Protocol Wealth, LLC and contributors.
  ```
- **DCO sign-off on every commit.** `git commit -s -m "feat: ..."`. See [CONTRIBUTING § Developer Certificate of Origin](CONTRIBUTING.md#developer-certificate-of-origin).
- **Conventional commits** for type prefixes (`feat:`, `fix:`, `chore:`, `docs:`, `deps:`, `ci:`).
- **One concept per file.** `snake_case.py` modules. Modules ≤ ~300 LOC where possible; long modules signal a missing split.
- **Sync handlers + sync `httpx`.** REST handlers are sync `def` on purpose — providers block, so FastAPI's threadpool is the right execution model. Only DB code (`asyncpg`) is `async`.
- **pydantic v2 for boundary validation** (`BaseModel`, `ConfigDict`, `Field`). Don't introduce dataclasses where pydantic models would also enforce runtime types.
- **Heavy deps are lazy-imported** inside functions (PyPortfolioOpt, Riskfolio, torch). The extras system is the whole point — keep heavy imports out of the core import path (ruff `PLC0415` is intentionally ignored for this).
- **Tests under `tests/test_<module>.py`** matching source file names. Hermetic — no network calls, no live data, no API keys, no real adopter credentials. Tests use `create_app(enable_mcp=False, market=<fake>)` to exercise the REST API without upstreams.
- **Stubs in `examples/`.** Example scripts must run without network credentials.
- **License-name comment on every new dep** in `pyproject.toml` (e.g. `"yfinance>=1.4.0",  # Apache 2.0`). The license-compliance workflow fails the build if a forbidden license sneaks in.
- **Disclaimers come from `src/nexus_core/disclaimers.py`** (TERSE / MC_DISCLAIMER / FULL / SAFEGUARDS) — never hand-write a disclaimer string. Every output surface attaches the appropriate variant.
- **Confidence tiers are not verdicts.** They are probabilistic labels (SEC Rule 206(4)-1); never relabel as buy/sell/hold, and never emit a tier on insufficient evaluated checks (the framework returns `NOT APPLICABLE`).

## Adding a Regime Signal or Scoring Check

1. Identify the layer:
   - **Regime signal** → `src/nexus_core/engine/regime/` — new voting signal in the ensemble (`signals.py` + `signal_fetcher.py`).
   - **Scoring check** → `src/nexus_core/engine/scoring/` — new check in `checks.py` / `emf/` returning a tier or score component.
2. Add the module + prepend the SPDX block.
3. Add tests under `tests/test_<name>.py` covering happy path + the regime-state edge cases (Growth / Transition / Hard Asset / Deflation / Repression).
4. Re-export from the subpackage's `__init__.py` if it's part of the public API surface.
5. If the change touches the engine's contract (new signal output type, new regime state, new score component) update [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) in the same PR.
6. Run `pytest && ruff check src/ tests/ && mypy --strict src/nexus_core/` — all three must pass before opening the PR.

**Do NOT:**
- Change the calibrated threshold/decay/weight values casually. These ARE Protocol Wealth's published EMF calibration (EMF is openly published — see [protocolwealthllc.com/framework](https://protocolwealthllc.com/framework)); there is no private companion. `regime/thresholds.py` is the single source of truth.
- Add a new regime state. The 5-state model (Growth / Transition / Hard Asset / Deflation / Repression) is patent-anchored; expanding it requires architecture-level review, not a contributor PR.
- Compute scoring across regime states inside a signal module. Regime classification is one stage; scoring composes on top. Keep the stages separate.

## Adding an HTTP Route or MCP Tool

**HTTP route:** add or extend a `build_*_router(...)` factory under `src/nexus_core/app/`, then wire it in `app/main.py`'s `create_app()`. Keep handlers sync, set an explicit `Cache-Control`, and degrade to 503 (not 500) when a required key/provider is absent. Tools compose over the engines — do not reimplement engine logic at the route layer.

**MCP tool:** add to `src/nexus_core/mcp/server/` with `@mcp.tool(annotations=_RO_OPEN)` (or `_RO_CLOSED` for pure compute). Write the description for the LLM consumer (inputs, outputs, side effects — none expected, read-only by default; regime-state sensitivity if any). Attach the disclaimer via `_ok`/`_err`. Add tests through a FastMCP test client. Deployment-specific tools (e.g. the planning gateway) inject via `build_server(..., extra_tools=...)` from `app/mcp_mount.py` so the public scaffold stays decoupled.

**Do NOT:**
- Add routes or tools that mutate state (DB writes from HTTP, external API POSTs) without architecture-level review — the posture is read-only by default. Writes happen only in the Cloud Run Job.
- Embed credentials, endpoints, or environment-variable names in tool/route descriptions.

## Boundaries

Hard NOs. Each is enforced by review + tooling where possible:

- **No client-specific values.** Thresholds, decay constants, regime cutoffs, narrative pipeline logic — see [README § What's Open vs Private](README.md#whats-open-vs-private).
- **No PII / secrets / vendor API keys** in tests, fixtures, examples, commit messages, or issue templates. No client data lives in this repo or its database.
- **No AGPL code copied.** OpenBB Platform (AGPL-3.0) and SEC EDGAR Toolkit (AGPL-3.0) are listed as architecture references — see [`NOTICE`](NOTICE) and [`docs/attribution.md`](docs/attribution.md). Patterns may be studied; bytes may not be copied. Clean-room re-derivation only.
- **No bypassing patent posture.** USPTO #64/034,229 is filed defensively under Apache 2.0. Do not remove the patent-pending notice from `README.md`, `src/nexus_core/__init__.py`, or shields/badges. Do not author claims of a different IP posture in this repo.
- **No `--no-verify` on commits.** No skipped hooks. No `--no-gpg-sign`. If a hook fails, fix the root cause.
- **No commits without SPDX header** on new `.py` files. The `examples/` + `src/` + `tests/` trees are fully covered; maintain coverage on additions.
- **No silent license-class additions to `pyproject.toml`.** New deps come with the license-name comment. The license-compliance GitHub Action fails the build if a forbidden license (GPL-3.0 / AGPL / SSPL) is detected at install time.
- **No backwards-compat shims for hypothetical adopters.** This is a scaffold framework — adopters take it at the version they fork. Don't add deprecation paths or compat layers that aren't load-bearing for current production use.

## Cross-Repo Notes

- **[`pwos-core`](https://github.com/Protocol-Wealth/pwos-core) (sibling, TypeScript)** — compliance primitives published to npm under `@protocolwealthos/*`. Boundary: math lives in nexus-core; data shapes + audit/compliance hooks live in pwos-core. When extracting a primitive across the boundary, generalize the API — drop framework coupling, drop PW-specific identifiers, expose hooks for caller-specific behavior.
- **Reference-consumer apps** are separate repos (e.g. [`pw-os-v2`](https://github.com/Protocol-Wealth/pw-os-v2) at [pwos.app](https://pwos.app)). The [nexusmcp.site](https://nexusmcp.site) deployment runs the `nexus_core.app` surface from **this** repository — see [`DEPLOY.md`](DEPLOY.md).
- **Closed runtime + consumer repos** (`pw-portal`, `pw-onchain`, `pw-infrastructure`, etc.) are listed on the security page. Do not port code from those into here, or vice versa.

## Roadmap

Recently shipped (see `CHANGELOG.md`): multi-chain Uniswap V3 LP (base/optimism/polygon added to ethereum); position `vs-benchmark` (pair LP IL with hold benchmarks — "was LPing worth it?"); Jupiter Solana SPL prices (`/api/solana`, keyless); **Aerodrome Slipstream LP on Base via on-chain RPC** (`/api/lp/aerodrome/{token_id}/analytics`, partial — value/in-range/amounts/uncollected fees; no IL/fee-APR/gauge-APR without an indexer).

Next surfaces (see `CHANGELOG.md` and [pwos.app/build](https://pwos.app/build) for detail; tracked in #199):
- **Aerodrome Slipstream — full coverage via Envio** — the on-chain RPC path is **live** (partial: value, in-range, amounts, uncollected fees; `data_mode: onchain_rpc`). No canonical Slipstream V3-schema subgraph exists on The Graph (name-matching ones are Revert-automation + ICHI-vault subgraphs), and the on-chain-only path cannot derive IL (needs deposit history), fee APR (needs pool volume), or AERO gauge reward APR. An **Envio** client would add those; the pure engine + Slipstream NFPM (`0x827922686190790b37229fd06084350E74485b72`, decode-compatible) are already wired.
- **Arbitrum Uniswap V3** — needs a correct V3-schema subgraph ID (the published one is incompatible).
- **Base subgraph data quality** — the public Base V3 deployment has spam-token TVL contamination (pollutes discovery + pool-aggregate fee APR; per-position value/IL stays accurate) → consider self-hosting a cleaner indexer.
- **Uniswap V4 via Envio (Unichain).**
- **Solana CLMM (Raydium/Orca)** — Q64.64 sibling engine; Jupiter price layer already shipped.
- **Subgraph health-gate** (`_meta` block-lag → degraded).
- **Position-PnL persisted history.**
- **Enrich Tatum Solana balance with Jupiter USD.**
