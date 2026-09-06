# nexus-core — open-source regime-adaptive financial analysis engine

> Repo: `Protocol-Wealth/nexus-core` · License: Apache 2.0 · Patent Pending: USPTO #64/034,229 · OIN member.
> Open-source extraction of the [Protocol Wealth research engine](https://nexusmcp.site); nothing in this repo is client-specific or proprietary to PW.

## Where state lives

**This file answers ONE question: how does an agent operate in this repo.** It
is loaded on every turn, so it stays lean by construction. It previously
carried a 126-line dated "Current state" block plus three "Historical
snapshot" sections; those were stripped 2026-08-31 because they had gone
stale and were actively misleading — see the note under Security Posture.

**Never add a dated state block here.** Estate doctrine retired that shape
everywhere (`CURRENT-STATE.md` / `ROADMAP.md`, 2026-08-18), and PR #306
retired those files in this repo without removing the same shape from this
one.

| Question | Where |
|---|---|
| What is live in production right now | Cloud Run, and the service itself — probe it |
| What shipped, and when | [`CHANGELOG.md`](./CHANGELOG.md) |
| What is planned | GitHub Issues — `gh issue list` |
| Design record, live + planned | [pwos.app/build](https://pwos.app/build) |
| Issues, PRs, CI | **GitHub — authoritative. Re-query it.** |


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
pip install -e ".[dev,serve]"     # WHAT CI INSTALLS — the only combination that can run step 6's gate
pip install -e ".[serve]"         # Deployed surface (market + mcp extras) — what nexusmcp.site runs
pip install -e ".[dev]"           # Dev tooling ONLY (pytest, pytest-asyncio, pytest-cov, ruff, mypy, pip-licenses)
                                  #   NOT ENOUGH TO RUN THE SUITE. Without [serve] there is no fastmcp, so
                                  #   `mypy --strict` reports 38 untyped-decorator errors in mcp/server/app.py,
                                  #   and no python-multipart, so the OAuth /token form tests fail. Both look
                                  #   like real defects on a clean checkout and neither is one.
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

## Endpoint Surface (read-only; SPLIT ACCESS — open, key-gated, and OAuth)

`GET` unless noted. Cache lifetimes are set in handlers and respected by the
Cloudflare edge.

**THE ACCESS MODEL IS SPLIT — do not read it as one answer.** Three groups,
verified live 2026-09-06:

| group | example | unauthenticated |
|---|---|---|
| open | `/`, `/health`, the docs | `200` |
| service-key gated | `/api/*`, legacy `/mcp/tools*` | `401 {"error":"unauthorized"}` |
| native MCP, OAuth | `POST /mcp` | `{"error":"invalid_token"}` **plus** a `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp"` header |

`access_gate.py` protects `/api/*` and `/mcp/tools*` whenever
`NEXUS_ACCESS_MODE=restricted`, which is how production runs.

**`invalid_token` on `POST /mcp` is not evidence the surface is private.** It is
the OAuth handshake STARTING: the `WWW-Authenticate` header points at the
resource-metadata document, and a remote MCP client that completes the flow gets
in with no service key and no login. Native MCP is effectively a public demo
surface by design — the landing page says so. Citing that response as proof of
privacy misleads an agent about which endpoints actually need credentials, which
is the opposite of what this section exists to prevent.

The heading previously read "(public, read-only)". Do not restore that: the
code DEFAULT is `public`, but the deployed environment overrides it, and
reading the default as the deployed state is exactly the mistake this note
exists to stop. Check the service, not `access_mode()`.

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

- **Read-only. No write endpoints at all** — the daily snapshot is a Cloud Run
  Job, not an HTTP route. The surface is NOT public: see the Endpoint Surface
  note above. This bullet used to open "Public read-only", which was false
  against a service that has been refusing unauthenticated `/api/*` calls.
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

Tracked in GitHub Issues and the design record at [pwos.app/build](https://pwos.app/build);
shipped work is in [`CHANGELOG.md`](./CHANGELOG.md).

A roadmap list previously lived here and drifted from both. A plan in a
per-turn file is read as current by every agent that loads it, which is the
same failure as the dated state block above.
