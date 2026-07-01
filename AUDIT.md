# Public-Surface Audit — nexus-core

This document records the current public-deployment boundary for
[nexusmcp.site](https://nexusmcp.site). The public surface is read-only and
educational: it exposes market/macro/options/DeFi analytics and PII-free planning
math, with no client data, account surfaces, suitability logic, or advisory
workflow state.

## Current Boundary

`nexus-core` is an Apache-2.0 analytical engine. It is not the Protocol Wealth
client/advisor application layer. Public planning tools in this repo accept
de-identified inputs only (age, balances, asset classes, filing status, generic
goal ids). Identity-shaped keys such as name, email, address, SSN, and date of
birth are rejected by the planning gateway.

The public deployment has:

| Surface | Module | Notes |
|---------|--------|-------|
| Regime classification/signals | `engine/regime/`, `app/routes.py` | Public macro signals and regime labels |
| EMF scoring | `engine/scoring/`, `app/scoring.py` | SEC EDGAR fundamentals + public market data |
| Market/economic data | `data/market/`, `data/macro/` | Quotes, history, FRED/BEA/EIA/Treasury-style macro adapters |
| Options | `engine/pricing/`, `app/options.py` | Black-Scholes overlays + Deribit crypto options; educational only |
| On-chain/DeFi | `data/onchain/`, `app/{wallet,chain,vaults,lp,solana}.py` | Public wallet/chain/vault/LP/Solana data |
| Benchmarks/history | `engine/benchmarks.py`, `data/snapshots.py` | Daily benchmark snapshots via private Cloud SQL |
| Planning math | `engine/planning/`, `app/planning/` | 23 PII-free tools via MCP and `/mcp/tools` |
| MCP transport | `mcp/server/`, `app/mcp_mount.py` | Read-only tool registry, same engines as REST |
| Transparent MCP OAuth | `app/mcp_oauth.py` | Anonymous OAuth 2.1 / PKCE compatibility flow for remote MCP clients |
| Disclosure/security metadata | `app/{disclosure,well_known,llms_txt}.py` | AI disclosure card, security.txt, llms.txt |

## What Is Not Here

The public deployment does not contain client login, advisor authentication,
KYC/AML identity verification, account onboarding, signed-document workflows,
custody/trading actions, suitability determinations, client-specific planning
records, report-production workflows, artifact receipts, or private PWOS workflow
state. Those belong in closed Protocol Wealth systems or consumer repos.

## Auth And OAuth

No account or API key is required to use the public REST surface. The hosted MCP
transport may require a bearer token when `MCP_OAUTH_SIGNING_KEY` is configured,
because some remote MCP clients expect OAuth 2.1 + PKCE + Dynamic Client
Registration. That flow is transparent and anonymous: any valid client can
register and obtain a public-scope token, with no login and no privilege
escalation beyond the public read-only tool surface. Local/unkeyed deployments
can omit the signing key and leave `/mcp` open.

## Persistence

There are no public write endpoints. The only writer is the Cloud Run snapshot
job (`nexus-core snapshot`), which writes daily benchmark prices to private Cloud
SQL for `/api/benchmarks/history`. Public requests do not persist inputs.

## Posture

The public deployment is read-only, non-custodial, and not advice. It holds no
client data and no PII. Disclaimers are sourced from `src/nexus_core/disclaimers.py`
and attached to public-facing analytical surfaces.
