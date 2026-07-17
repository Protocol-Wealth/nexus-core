# Public-Surface Audit — nexus-core

This document records the current public-deployment boundary for
[nexusmcp.site](https://nexusmcp.site). The deployment is read-only and
educational: it exposes a public demo MCP profile plus service-key-gated
market/macro/options/DeFi, planning, and de-identified onchain-accounting REST
analytics, with no client data, account surfaces, suitability logic, or advisory
workflow state.

Last verified 2026-07-16 ET: commit `e5f4d84`, Cloud Run revision
`nexus-core-00070-zhx`, 100% traffic. Custom-domain, direct, regional, and
database health checks returned HTTP 200; anonymous accounting discovery
returned the expected service-key HTTP 401. A complete OAuth MCP flow returned
the five-tool demo catalogue with accounting absent. No production service-key
value was read, so an authenticated v2 REST handshake was not rerun.

## Current Boundary

`nexus-core` is an Apache-2.0 analytical engine. It is not the Protocol Wealth
client/advisor application layer. Planning tools accept de-identified inputs only
(age, balances, asset classes, filing status, generic goal ids). Accounting tools
accept de-identified public-chain/market facts with opaque account, transaction,
and asset references. Identity-shaped keys such as name, email, address, SSN,
date of birth, client id, or wallet address are rejected by the relevant gateway.

The public deployment has:

| Surface | Module | Notes |
|---------|--------|-------|
| Regime classification/signals | `engine/regime/`, `app/routes.py` | Public macro signals and regime labels |
| EMF scoring | `engine/scoring/`, `app/scoring.py` | SEC EDGAR fundamentals + public market data |
| Market/economic data | `data/market/`, `data/macro/` | Quotes, history, FRED/BEA/EIA/Treasury-style macro adapters |
| Options | `engine/pricing/`, `app/options.py` | Black-Scholes overlays + Deribit crypto options; educational only |
| On-chain/DeFi | `data/onchain/`, `app/{wallet,chain,vaults,lp,solana}.py` | Public wallet/chain/vault/LP/Solana data |
| Onchain accounting | `engine/accounting/`, `app/accounting/` | Deployed contract `0.2.0` on restricted REST; the deployed image reuses its four calculation handlers in native MCP full mode |
| Benchmarks/history | `engine/benchmarks.py`, `data/snapshots.py` | Daily benchmark snapshots via private Cloud SQL |
| Planning math | `engine/planning/`, `app/planning/` | 34 PII-free tools via native MCP and the primary `/api/planning/tools` REST gateway; `/mcp/tools` is a legacy alias |
| MCP transport | `mcp/server/`, `app/mcp_mount.py` | Read-only full/demo profiles; full includes four accounting calculation tools, hosted demo excludes them |
| Transparent MCP OAuth | `app/mcp_oauth.py` | Anonymous OAuth 2.1 / PKCE compatibility flow for remote MCP clients |
| Disclosure/security metadata | `app/{disclosure,well_known,llms_txt}.py` | AI disclosure card, security.txt, llms.txt |

## What Is Not Here

The public deployment does not contain client login, advisor authentication,
KYC/AML identity verification, account onboarding, signed-document workflows,
custody/trading actions, suitability determinations, client-specific planning
records, custodian/client transaction ingestion, wallet-to-client mappings,
statement/report-production workflows, tax-return preparation, artifact receipts,
or private PWOS workflow state. Those belong in closed Protocol Wealth systems
or consumer repos. The public-safe accounting math does not change that boundary.
Deployed contract `0.2.0` implements #260's account/transfer/fee, period-replay,
and lineage semantics. Technical issue #260 is complete, and the 2026-07-17
CCO/CIO/CTO decision approved methodology 2.0/FIFO for operational use.
Complete bounded calculations may report `statement_ready=true`; `pw-api#789`
owns authenticated client linkage, immutable artifacts, review, delivery, and
retention outside this public engine.

## Auth And OAuth

The hosted deployment sets `NEXUS_ACCESS_MODE=restricted` and requires a Nexus
service key on `/api/*`, the primary planning/accounting JSON gateways, and the
legacy `/mcp/tools/*` aliases. `pw-api` owns the server-to-server credential;
browser applications must not embed it. Local/public-mode installations can run
the same REST surface without that gate.

The hosted native MCP transport uses `NEXUS_PUBLIC_MCP_PROFILE=demo` and may
require a bearer token when `MCP_OAUTH_SIGNING_KEY` is configured because remote
MCP clients expect OAuth 2.1 + PKCE + Dynamic Client Registration. That flow is
transparent and anonymous: any valid client can register and obtain public demo
scope, with no login or privilege escalation. The deployed image registers the
four accounting calculation handlers in native MCP full mode only. They remain
absent from the hosted demo profile.

## Persistence

There are no public write endpoints. The only writer is the Cloud Run snapshot
job (`nexus-core snapshot`), which writes daily benchmark prices to private Cloud
SQL for `/api/benchmarks/history`. Public requests do not persist inputs.

## Posture

The public deployment is read-only, non-custodial, and not advice. It holds no
client data and no PII. Disclaimers are sourced from `src/nexus_core/disclaimers.py`
and attached to public-facing analytical surfaces.
