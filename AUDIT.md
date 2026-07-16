# Public-Surface Audit — nexus-core

This document records the current public-deployment boundary for
[nexusmcp.site](https://nexusmcp.site). The deployment is read-only and
educational: it exposes a public demo MCP profile plus service-key-gated
market/macro/options/DeFi, planning, and de-identified onchain-accounting REST
analytics, with no client data, account surfaces, suitability logic, or advisory
workflow state.

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
| Onchain accounting | `engine/accounting/`, `app/accounting/` | Contract `0.1.0`; price history, de-identified event decoding, FIFO cost basis, and realized PnL through restricted REST only |
| Benchmarks/history | `engine/benchmarks.py`, `data/snapshots.py` | Daily benchmark snapshots via private Cloud SQL |
| Planning math | `engine/planning/`, `app/planning/` | 34 PII-free tools via native MCP and the primary `/api/planning/tools` REST gateway; `/mcp/tools` is a legacy alias |
| MCP transport | `mcp/server/`, `app/mcp_mount.py` | Read-only full/demo profiles; accounting is not registered yet (#259) |
| Transparent MCP OAuth | `app/mcp_oauth.py` | Anonymous OAuth 2.1 / PKCE compatibility flow for remote MCP clients |
| Disclosure/security metadata | `app/{disclosure,well_known,llms_txt}.py` | AI disclosure card, security.txt, llms.txt |

## What Is Not Here

The public deployment does not contain client login, advisor authentication,
KYC/AML identity verification, account onboarding, signed-document workflows,
custody/trading actions, suitability determinations, client-specific planning
records, custodian/client transaction ingestion, wallet-to-client mappings,
statement/report-production workflows, tax-return preparation, artifact receipts,
or private PWOS workflow state. Those belong in closed Protocol Wealth systems
or consumer repos. The public-safe accounting math does not change that boundary;
#260 blocks statement wiring until its account/transfer/fee, period-replay, and
lineage semantics are hardened and methodology-reviewed.

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
scope, with no login or privilege escalation. The accounting handlers are absent
from native MCP today; #259 will add them to the full profile only, not the hosted
demo profile.

## Persistence

There are no public write endpoints. The only writer is the Cloud Run snapshot
job (`nexus-core snapshot`), which writes daily benchmark prices to private Cloud
SQL for `/api/benchmarks/history`. Public requests do not persist inputs.

## Posture

The public deployment is read-only, non-custodial, and not advice. It holds no
client data and no PII. Disclaimers are sourced from `src/nexus_core/disclaimers.py`
and attached to public-facing analytical surfaces.
