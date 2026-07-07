# Nexus Core

> Open source regime-adaptive financial analysis engine with MCP tool orchestration.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Patent Pending](https://img.shields.io/badge/Patent-Pending-orange.svg)](https://patentcenter.uspto.gov/applications/64034229)
[![OIN Member](https://img.shields.io/badge/OIN-Member-green.svg)](https://openinventionnetwork.com)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![GitHub stars](https://img.shields.io/github/stars/Protocol-Wealth/nexus-core?style=social)](https://github.com/Protocol-Wealth/nexus-core/stargazers)

**Live:** [nexusmcp.site](https://nexusmcp.site) | **Source:** [GitHub](https://github.com/Protocol-Wealth/nexus-core) | **Patent:** [USPTO #64/034,229](https://patentcenter.uspto.gov/applications/64034229)

## Status

This is a reference framework and a starting point, not a production-ready product. It is a work in progress under active, iterative development.

Adopters are responsible for adding their own PII controls, access control, input validation, authentication, and data-handling boundaries appropriate to their own regulatory and security context before any real or sensitive data touches it. Adopters are also responsible for their own AI-provider data-handling posture; the framework makes no data-retention guarantees.

Provided as-is under Apache-2.0. Educational use only — nothing here is investment advice.

Current live status is tracked in [CURRENT-STATE.md](CURRENT-STATE.md). Future
work is issue-linked in [ROADMAP.md](ROADMAP.md) and GitHub Issues.

As of the 2026-07-07 closeout, the hosted production posture is a public demo
MCP surface plus authenticated REST/JSON calculation endpoints. Anonymous MCP
clients can use the low-risk demo tool set; `/api/*` and planning JSON paths are
service-key gated in production and should be called server-to-server by
`pw-api`, not directly from browser apps. PWOS/PWPortal browser code should call
their own BFF/API layer, which keeps Nexus keys out of clients.

The current options substrate includes the MBOUM equity option expiration/chain
provider, batch collar screens, and a collar-book realistic-fill layer. The
engine plus REST/MCP parsers can accept midpoint `net_credit` and either
explicit `executable_net_credit` or executable leg prices (`call_bid` /
`put_ask`), then report stock price, shares, fill haircut, executable income,
and executable annualized yield. This remains an advisor research worksheet, not
an order surface or advice engine.

## What This Is

Nexus Core is the open source foundation of the [Protocol Wealth research engine](https://nexusmcp.site) — a regime-aware financial-analysis and DeFi/market-data engine that exposes its capabilities as a read-only REST API and as MCP (Model Context Protocol) tools. Any MCP-compatible AI client (Claude, GPT, Gemini) can access the public demo tool surface without implementing financial domain logic. Production consumers should use the REST/JSON endpoints through an authenticated service boundary. It is built on FastAPI + FastMCP (Python 3.12, sync `httpx`, `asyncpg`), runs `mypy --strict` + `ruff`, and is deployed on Google Cloud Run behind Cloudflare at [nexusmcp.site](https://nexusmcp.site).

Built and tested in production by an SEC-registered RIA (Protocol Wealth LLC, CRD #335298).

## Public API

The deployed surface is read-only and carries no client data. The native `/mcp`
transport can run as a public open-source demo endpoint; in production,
`NEXUS_PUBLIC_MCP_PROFILE=demo` keeps that surface limited to closed-world
calculation/demo tools. The REST/JSON calculation surfaces (`/api/*` and the
planning JSON gateway) can be gated with `NEXUS_ACCESS_MODE=restricted` and
`NEXUS_API_KEYS`, with `pw-api` sending a service bearer key. Remote MCP clients
may complete a transparent OAuth handshake with no login. Every external
integration degrades gracefully — to `None`, an empty result, or `503` — when
its provider key is absent.

For the PW Cash Flow OS + PW Planning Lab + PW Retirement Income Lab direction,
Nexus Core is the public-safe calculation plane. It can accept de-identified
planning inputs, optional taxable / traditional / Roth planning buckets, derived
monthly-close numbers, pre-screened stock symbols, and caller-supplied
option-chain facts. It must not ingest Monarch CSV exports, Seeking Alpha
workbooks, Schwab order/status files, raw transaction rows, merchant/payee
strings, account nicknames, household records, advisor/client notes, approval
state, release state, or books-and-records audit trails. Those production
workflows belong in private PWOS / pw-api / PWPortal; Nexus should receive only
de-identified calculation inputs after private ingestion.

### Meta

| Endpoint | Description |
|----------|-------------|
| `GET /` | Landing page |
| `GET /health` | Liveness probe (rate-limit exempt) |
| `GET /health/db` | Database connectivity probe |
| `GET /docs` | Interactive OpenAPI / Swagger UI |
| `GET /mcp-guide` · `GET /llms.txt` | MCP client setup guide · agent site map (llmstxt.org) |
| `GET /.well-known/security.txt` | RFC 9116 disclosure pointer |
| `GET /api/usage` | Provider usage / quota report |
| `POST /mcp` | Model Context Protocol over HTTP (FastMCP, also stdio). In full mode, `tools/list` = research tools + `health`/`describe`/`get_quotes` + 33 planning tools; in demo mode, only closed-world demo tools are registered. All tools are read-only |
| `GET /api/planning/tools` · `POST /api/planning/tools/{id}` | Planning JSON gateway (pw-api / pwplan-core contractVersion `0.1.0`, PII-free). Legacy `/mcp/tools` aliases remain for compatibility |

### Regime & Scoring

| Endpoint | Description |
|----------|-------------|
| `GET /api/regime` | EMF regime classification |
| `GET /api/regime/signals` | Raw regime signal readings |
| `GET /api/score/{ticker}` | 8-check EMF durability score (SEC EDGAR fundamentals) |

### Market & Economic Data

| Endpoint | Description |
|----------|-------------|
| `GET /api/market/quote/{symbol}` | Latest quote (yfinance/MBOUM/MarketStack/CoinGecko composite) |
| `GET /api/market/history/{symbol}` | OHLCV price history |
| `GET /api/economic/{series_id}` | FRED economic series |

### Options (educational)

| Endpoint | Description |
|----------|-------------|
| `GET /api/options/price` | Black-Scholes price + Greeks |
| `GET /api/options/overlay/covered-call` | Covered-call overlay illustration |
| `GET /api/options/overlay/cash-secured-put` | Cash-secured-put overlay illustration |
| `GET /api/options/overlay/collar` | Protective-collar overlay illustration |
| `POST /api/options/overlay/collar-screen` | Batch equity collar screen (≤25 positions; dividend-aware theoretical pricing) |
| `POST /api/options/overlay/collar-book` | Multi-name collar book assembly (≤50 pre-screened candidates; whole-contract sizing, position/sector caps; optional executable-fill haircut from bid-side call / ask-side put) — advisor research worksheet, no orders |
| `GET /api/options/equity/{symbol}/expirations` | Listed equity option expirations by bucket (weekly/monthly; MBOUM-backed, 503 without key) |
| `GET /api/options/equity/{symbol}/chain?expiration=` | Normalized single-expiration equity option chain — bid/ask, OI, IV, delta (expiration required) |
| `GET /api/options/crypto/currencies` | Crypto option underliers + settlement model (Deribit) |
| `GET /api/options/crypto/{currency}/instruments` | Deribit crypto options — BTC/ETH (inverse) + SOL/XRP/TRX/AVAX (USDC-linear) |
| `GET /api/options/crypto/instrument/{instrument_name}` | Deribit crypto option detail |
| `GET /api/options/crypto/{currency}/protective-put` | Settlement-aware protective-put floor (cost of protection) |
| `GET /api/options/crypto/{currency}/collar` | Settlement-aware protective collar (put floor + financing call) |
| `GET /api/options/crypto/{currency}/covered-call` | Settlement-aware covered-call overwrite illustration (coin yield) |
| `GET /api/options/crypto/{currency}/covered-call-chain` | Rank live OTM calls by annualized covered-call yield |
| `GET /api/options/crypto/{currency}/regime-overwrite` | Covered-call strike tilted by the LIVE EMF macro regime |
| `GET /api/options/crypto/{currency}/iv-term-structure` | Near-ATM implied-vol curve across tenors (which expiry pays richest) |
| `GET /api/options/crypto/{currency}/vol-skew` | Call-side IV + vega by strike (which strike is richest to write) |
| `POST /api/options/crypto/{currency}/ladder` | Calendar/strike covered-call ladder (coverage, blended yield) |
| `POST /api/options/crypto/{currency}/roll` | Roll a short call (up/out net-credit economics) |
| `POST /api/options/crypto/{currency}/book/mtm` | Mark an options book + aggregate Greeks |
| `POST /api/options/crypto/{currency}/book/scenario` | Spot×IV stress grid + assignment flags |

### On-Chain & DeFi

| Endpoint | Description |
|----------|-------------|
| `GET /api/wallet/{address}` | Anonymous EVM wallet balance (DeBank) |
| `GET /api/chain/chains` | Supported chains |
| `GET /api/chain/balance/{chain}/{address}` | Multi-chain native balance (Tatum) |
| `GET /api/chain/native/{address}` | Native balance lookup |
| `GET /api/vaults` | DeFi vault discovery (vaults.fyi v2) |
| `GET /api/vaults/chains` | Vault-supported chains |
| `GET /api/solana/price/{mint}` | Solana SPL token USD price (Jupiter, keyless) |
| `GET /api/solana/prices?mints=` | Batch Solana SPL token USD prices (Jupiter, keyless) |

### LP Analytics (Uniswap V3 + Aerodrome Slipstream)

| Endpoint | Description |
|----------|-------------|
| `GET /api/lp/chains` | Chains/versions with LP analytics |
| `GET /api/lp/uniswap-v3/{chain}/positions?owner=` | Open Uniswap V3 positions owned by a public EVM address (token units, no USD valuation) |
| `GET /api/lp/uniswap-v3/{chain}/{token_id}/analytics` | Position value, in-range status, exact impermanent-loss-vs-HODL, fee-APR estimate, uncollected fees, Merkl reward APR → total APR (USD prices required as query params) |
| `GET /api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark` | Position return vs. hold-strategy benchmark returns over a window (USD prices required as query params) |
| `GET /api/lp/aerodrome/{token_id}/analytics` | Aerodrome Slipstream position on **Base**, read on-chain (RPC) — value, in-range, token amounts, uncollected fees (USD prices required as query params). IL, fee APR, and AERO gauge APR are not available in on-chain-only mode (reported null/zero) |

Supported chains (Uniswap V3): **ethereum, base, optimism, polygon**. (Arbitrum's published subgraph uses an incompatible schema and is not supported.) Aerodrome Slipstream — a Uniswap-V3 CLMM sibling — is read directly on-chain on Base, so the same pure engine drives it with no subgraph dependency.

### Benchmarks

| Endpoint | Description |
|----------|-------------|
| `GET /api/benchmarks` | Base-100 buy-and-hold benchmark returns (BTC/ETH/SOL + ETH-USDC 50/50,60/40,70/30 + ETH-BTC 50/50) |
| `GET /api/benchmarks/series?days=` | On-demand series from CoinGecko |
| `GET /api/benchmarks/history?days=` | Series from persisted daily snapshots |

## Architecture

```
MCP Client (Claude, GPT, Gemini)  /  REST clients
    │ JSON-RPC over HTTP          │ HTTP
    ▼                             ▼
Nexus Core (FastAPI + FastMCP)
├── Regime Engine (engine/regime)
│   ├── Core signals: Gold/SPX vs 200WMA, real rates, DXY, VIX, credit spreads (BBB OAS)
│   ├── Supplementary: yield curve (2s10s), precious metals
│   └── 5 regime states (Growth, Transition, Hard Asset, Deflation, Repression)
├── EMF Scoring (engine/scoring/emf)
│   └── 8-check durability scoring + confidence tiers (SEC EDGAR fundamentals)
├── Options Pricing (engine/pricing)
│   └── Black-Scholes price + Greeks, covered-call/CSP/collar overlays,
│       collar-book sizing + executable-fill haircut worksheet
├── LP Analytics (engine/lp/uniswap_v3.py)
│   └── Pure CLMM math: tick math, get_amounts_for_liquidity, exact IL, fee APR
│       (protocol-agnostic — reused across ethereum/base/optimism/polygon)
├── Benchmarks (engine/benchmarks.py)
│   └── Base-100 buy-and-hold compositions
├── Planning (engine/planning)
│   └── PII-free planning math: Monte Carlo, goals, cash flow, taxable-first waterfall, Roth/IRMAA, versioned tax-table provider
├── Data Clients (data/)
│   ├── market/   yfinance, MBOUM, MarketStack, CoinGecko + cache + composite
│   ├── macro/    FRED, EIA, BEA, Treasury
│   ├── edgar/    SEC fundamentals (XBRL)
│   ├── derivatives/  Deribit
│   └── onchain/  DeBank, Tatum, The Graph, Merkl, vaults.fyi, DefiLlama, Jupiter
├── Persistence (data/db.py, data/snapshots.py)
│   └── asyncpg → private Cloud SQL (daily benchmark snapshots)
├── Jobs (jobs/daily_snapshot.py)
└── MCP Tool Registry (mcp/server)
    ├── @mcp.tool() decorator pattern
    └── Pluggable ResponseFilter hooks (adopter-supplied auth / PII / audit)
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the signal ensemble, regime-state table, 8-check definitions, and the `ResponseFilter` tiering hook.

## Key Innovations

**Regime Detection** — Signal ensemble maps macroeconomic conditions to regime states, informing asset-specific analysis.

**EMF Scoring** — Multi-dimensional 8-check durability assessment combining fundamentals, technicals, momentum, and regime alignment.

**Exact LP Analytics** — Pure constant-liquidity-market-maker math computes exact impermanent-loss-vs-HODL, fee APR, and total APR (including Merkl rewards) for Uniswap V3 positions.

**MCP Orchestration** — Tools auto-adjust analysis based on detected regime. Any LLM accesses regime-aware insights without domain logic.

## Built on the Shoulders of Giants

Nexus Core stands on a foundation of exceptional open-source projects. We bundle or extend these libraries with full attribution — see [NOTICE](NOTICE) and [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for complete legal notices.

### Portfolio Optimization & Risk Analytics
- **[PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt)** (MIT) — Mean-variance, Black-Litterman, HRP
- **[Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib)** (BSD-3) — 24 convex risk measures, factor models
- **[empyrical-reloaded](https://github.com/stefan-jansen/empyrical-reloaded)** (Apache 2.0) — Performance metrics (Sharpe, Sortino, VaR)
- **[pyfolio-reloaded](https://github.com/stefan-jansen/pyfolio-reloaded)** (Apache 2.0) — Professional tear sheets
- **[skfolio](https://github.com/skfolio/skfolio)** (BSD-3) — scikit-learn portfolio optimization
- **[ffn](https://github.com/pmorissette/ffn)** (MIT) — Pandas financial functions

### Derivatives Pricing & Fixed Income
- **[QuantLib](https://github.com/lballabio/QuantLib)** (Modified BSD) — Derivative pricing, yield curves
- **[FinancePy](https://github.com/domokane/FinancePy)** (MIT) — Numba JIT pricing for bonds/swaps/options

### SEC EDGAR & Financial Data
- **[edgartools](https://github.com/dgunning/edgartools)** (MIT) — SEC filings as Python objects + built-in MCP server
- **[Arelle](https://github.com/Arelle/Arelle)** (Apache 2.0) — SEC-certified XBRL validation
- **[sec-parser](https://github.com/alphanome-ai/sec-parser)** (MIT) — Semantic parsing for LLM pipelines
- **[sec-edgar-downloader](https://github.com/jadchaar/sec-edgar-downloader)** (MIT) — Bulk filing downloads
- **[yfinance](https://github.com/ranaroussi/yfinance)** (Apache 2.0) — Market data

### Backtesting & Factor Analysis
- **[zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded)** (Apache 2.0) — Event-driven backtesting
- **[alphalens-reloaded](https://github.com/stefan-jansen/alphalens-reloaded)** (Apache 2.0) — Factor performance analysis

### AI & ML for Finance
- **[FinRL](https://github.com/AI4Finance-Foundation/FinRL)** (MIT) — Reinforcement learning for portfolios
- **[FinBERT](https://github.com/ProsusAI/finBERT)** (Apache 2.0) — Financial sentiment classification (via Transformers)

**Huge thanks to every maintainer and contributor of these projects.** Financial software has historically been locked behind proprietary walls — Nexus Core would not exist without the open-source financial ecosystem.

## What's Open vs Private

**Open (Apache 2.0):** Framework architecture, scoring structure, layer model, tool pattern, the public REST/MCP surface, caching patterns — **and Protocol Wealth's calibrated regime thresholds + scoring values**, which PW publishes openly as part of the EMF framework ([protocolwealthllc.com/framework](https://protocolwealthllc.com/framework)). All third-party integrations listed above.

**Private:** API keys, client data, Monarch imports, Schwab/custodian files,
Seeking Alpha CSV/XLSX imports, raw transaction processing, household records,
advisor/client planning workflows, suitability logic, report production,
approvals, release workflow, books-and-records audit trail, the narrative and
research-ingestion pipeline, and any client-specific implementation.
(Calibrations are *not* private — EMF is a published framework. Adopters with
different signal sources should still re-fit.)

## Installation

> **Install from the source repository.** A Protocol Wealth–controlled
> distribution is not yet published to PyPI — the bare `nexus-core` name on PyPI
> is **not** ours — so until a controlled distribution is published, install
> directly from this repository (the git-pinned form below).

### Full install (all capabilities)

```bash
pip install "nexus-core[all] @ git+https://github.com/Protocol-Wealth/nexus-core.git"
```

### Modular installs (reduce dep footprint)

Swap `[all]` for any single extra: `serve` (the public HTTP API + MCP server,
nexusmcp.site) · `mcp` (local stdio MCP server) · `optimization` (PyPortfolioOpt,
Riskfolio, skfolio) · `risk` (empyrical, pyfolio, ffn) · `pricing` (QuantLib,
FinancePy) · `edgar` (edgartools, Arelle, sec-parser) · `market` (yfinance) ·
`ai` (FinRL, Transformers, torch — heavy) · `backtest` (zipline-reloaded,
alphalens). Omit the bracket entirely for core only (regime + scoring).

```bash
pip install "nexus-core[serve] @ git+https://github.com/Protocol-Wealth/nexus-core.git"
```

### From source

```bash
git clone https://github.com/Protocol-Wealth/nexus-core.git
cd nexus-core
pip install -e ".[all]"
```

## Quick Start

**Hosted — no install.** The server is live at `nexusmcp.site`. Public liveness
and docs routes are anonymous; production `/api/*` examples require a service
API key when the hosted deployment is in restricted mode:

```bash
curl https://nexusmcp.site/health
curl -H "Authorization: Bearer $NEXUS_SERVICE_API_KEY" \
  https://nexusmcp.site/api/regime              # current macro regime
curl -H "Authorization: Bearer $NEXUS_SERVICE_API_KEY" \
  https://nexusmcp.site/api/planning/tools      # planning contract + tool ids

# a planning tool (educational, PII-free — send age, never date of birth)
curl -X POST https://nexusmcp.site/api/planning/tools/glide_path \
  -H "Authorization: Bearer $NEXUS_SERVICE_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"currentAge": 40, "retirementAge": 65, "horizonAge": 95,
       "startEquityWeight": 0.8, "endEquityWeight": 0.4, "shape": "linear"}'
```

**In Python** — the regime engine is built over data providers:

```python
from nexus_core.app.main import build_market_provider
from nexus_core.data.macro import FredMacroData
from nexus_core.engine.regime import RegimeEngine

engine = RegimeEngine(market_data=build_market_provider(), macro_data=FredMacroData())
result = engine.classify()
print(result.to_dict())   # regime code, confidence, per-signal breakdown, rationale
```

See [`examples/`](examples) for more runnable snippets.

### Run the public API + MCP server

```bash
pip install -e ".[serve]"
nexus-core serve     # HTTP API + MCP-over-HTTP — http://127.0.0.1:8080
nexus-core mcp       # MCP server over stdio (for Claude Desktop)
nexus-core snapshot  # Write a daily benchmark snapshot to the database
```

`nexus-core serve` hosts the surface deployed at
[nexusmcp.site](https://nexusmcp.site): the read-only REST API described above,
interactive docs at `/docs`, and an MCP endpoint at `/mcp`. In hosted
production, `/mcp` may remain a public OAuth-compatible demo surface while
REST/JSON calculation paths are service-key gated. See [DEPLOY.md](DEPLOY.md)
for the Cloud Run + Cloud SQL + Cloud Scheduler deployment.

### Using with any MCP client

The hosted MCP endpoint is public and read-only, so any MCP-compatible AI client (Claude, GPT, Gemini), or an agent platform such as SmythOS, can register `https://nexusmcp.site/mcp` as a read-only demo MCP server. Some remote clients complete transparent OAuth automatically; there is no user login. Production integrations should call the REST/JSON API through `pw-api` with a service API key. For example, in a `.mcp.json` (or any client config that follows the same shape):

```json
{
  "mcpServers": {
    "nexus-core": {
      "type": "http",
      "url": "https://nexusmcp.site/mcp"
    }
  }
}
```

See the [MCP setup guide](https://nexusmcp.site/mcp-guide) for per-client steps (Claude.ai, Claude Code, Claude Desktop, and other clients) and `tools/list` output.

## Configuration

All configuration is environment-driven. Every variable is optional; the app
runs without any of them, with reduced data coverage.

| Variable | Effect |
|----------|--------|
| `FRED_API_KEY` | Enables `/api/economic/*` and macro precision for `/api/regime` |
| `MBOUM_API_KEY` | Adds MBOUM as a market-data fallback |
| `MARKETSTACK_API_KEY` | Adds MarketStack as a market-data fallback |
| `COINGECKO_API_KEY` | Raises CoinGecko rate limits (works keyless too) |
| `EIA_API_KEY` | EIA energy / commodity macro data |
| `BEA_API_KEY` | Bureau of Economic Analysis macro data |
| `DEBANK_API_KEY` | Enables `/api/wallet` (DeBank) |
| `TATUM_API_KEY` | Enables `/api/chain` and LP uncollected-fee lookups |
| `VAULTSFYI_API_KEY` | Enables `/api/vaults` (vaults.fyi) |
| `THEGRAPH_API_KEY` | Enables `/api/lp` (The Graph) |
| `DATABASE_URL` | Persistence + `/api/benchmarks/history` (`503` when unset) |
| `MCP_OAUTH_SIGNING_KEY` | Enables stateless transparent OAuth for remote MCP clients; omit locally to keep `/mcp` open |
| `NEXUS_PUBLIC_MCP_PROFILE` | `full` (default) or `demo`; `demo` keeps hosted native `/mcp` limited to closed-world demo tools |
| `NEXUS_ACCESS_MODE` | `public` (default) or `restricted`; restricted mode requires a Nexus API key on `/api/*` and planning JSON gateway paths |
| `NEXUS_API_KEYS` | Comma-separated raw service keys or `sha256:<hex>` digests accepted by restricted mode |
| `NEXUS_RATE_LIMIT_PER_MIN` | Per-IP request budget (default `60`) |
| `NEXUS_CORS_ORIGINS` | Comma-separated CORS allow-list (default `*`) |

## Tech Stack

Python 3.12 · FastAPI · FastMCP · `httpx` · `asyncpg` · PostgreSQL (Cloud SQL) · pandas · numpy · scipy · `mypy --strict` · ruff · CI-gated test + lint suite

## Documentation

- [Current state](CURRENT-STATE.md) — point-in-time live surface and status
- [Roadmap](ROADMAP.md) — done vs next
- [Validation](VALIDATION.md) — latest local gates and live smoke evidence
- [Changelog](CHANGELOG.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Deployment](DEPLOY.md) — running the public API + Cloud Run / Cloud SQL deploy
- [Public-surface audit](AUDIT.md) — what the deployment exposes (and excludes)
- [Attribution](docs/attribution.md) — detailed provenance per capability
- [Contributing](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security](SECURITY.md)

## Patent & IP

**Patent Pending** — USPTO Application #64/034,229
"Compliance-First Quantitative Research Engine with Multi-Signal Regime Detection, Systematic Asset Scoring, and AI Tool Orchestration via Model Context Protocol for SEC/FINRA-Regulated Financial Advisory Services"

- [Patent disclosure](https://nexusmcp.site/patent) · [USPTO Patent Center](https://patentcenter.uspto.gov/applications/64034229) · [Figure 1 — system drawing (PDF)](docs/PW-PROV-002-FIG1.pdf)
- Applicant: Protocol Wealth, LLC
- Inventor: Nicholas Rygiel
- Filed: April 9, 2026
- Status: Patent Pending

This patent was filed **defensively** under Apache 2.0. The intent is to establish formal prior art and prevent third parties from patenting these concepts and restricting their use by independent financial advisors. Under Apache 2.0, you receive an automatic, perpetual, royalty-free patent grant. If you sue Protocol Wealth for patent infringement related to this software, your license terminates automatically.

**Open Invention Network (OIN) Member** — Protocol Wealth LLC is a member of the Open Invention Network (OIN), the world's largest patent non-aggression network with 4,100+ members including Google, IBM, Toyota, Meta, Microsoft, and Amazon. [Learn more](https://openinventionnetwork.com/about-us/member-benefits/)

See [PATENTS](PATENTS) for full non-assertion pledge.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

Apache 2.0 includes an explicit patent retaliation clause that MIT lacks. If someone sues you for patent infringement related to Nexus, their right to use the software terminates automatically.

**Third-party components retain their original licenses.** See [NOTICE](NOTICE) and [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

## Contributing

We welcome contributions. All commits must include a `Signed-off-by:` line certifying agreement with the [Developer Certificate of Origin](https://developercertificate.org/):

```bash
git commit -s -m "feat: your change"
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

## Related

- **[PWOS Core](https://github.com/Protocol-Wealth/pwos-core)** — Compliance-first AI operating system ([pwos.app](https://pwos.app))

## Links

- **Live App:** [nexusmcp.site](https://nexusmcp.site)
- [MCP setup guide](https://nexusmcp.site/mcp-guide) · [REST docs](https://nexusmcp.site/docs) · [llms.txt](https://nexusmcp.site/llms.txt)
- [USPTO Patent Center #64/034,229](https://patentcenter.uspto.gov/applications/64034229)
- [Protocol Wealth](https://protocolwealthllc.com)

---

*Built by [Protocol Wealth LLC](https://protocolwealthllc.com) — SEC-Registered Investment Adviser (CRD #335298)*
