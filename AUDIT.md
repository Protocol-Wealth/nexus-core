# Public-surface audit — nexus-core

This document records the audit behind the nexusmcp.site rebuild: a
confirmation that the public deployment exposes **market data and analytical
signals only**, with no client data, account surfaces, or advisory workflows.

## Background

The nexusmcp.site rebuild was originally scoped as "strip the client-related
endpoints out of nexus-core." A Phase 1 audit found there was nothing to strip:
`nexus-core` is, and always has been, an Apache-2.0 open-source package
carrying no client-specific code. Its own `CLAUDE.md` states it plainly —
*"nothing in this repo is client-specific or proprietary to PW."* The rebuild
was therefore re-scoped to **build** a thin public application on top of the
existing engine, rather than gut a non-existent one.

## What the audit checked

A case-insensitive scan of `src/`, `tests/`, and `examples/` for client and
authentication surface markers:

```
client_id   advisor_id   JWT        session        risk_tolerance
risk_assessment   financial_plan    kyc    aml      signed_document
signing     portal       client_profile   login    oauth    bearer
authenticate      authorization
```

**Result: zero client-related code.** The only matches were:

- Documentation lines describing the *absence* of authentication (the scaffold
  ships none; adopters wire their own via the `ResponseFilter` hook).
- False-positive substring matches: `AML` inside the FRED economic-series codes
  `BAMLC0A4CBBB` and `BAMLH0A0HYM2` (Bank of America Merrill Lynch credit
  spread indices).

There is no auth middleware, no client endpoint, no KYC/AML surface, no
signed-document surface, and no advisor login anywhere in the repository.

## What the public deployment exposes (retained)

| Surface | Module | Notes |
|---------|--------|-------|
| Regime classification | `engine/regime/` | Macro regime + per-signal breakdown |
| Regime signals | `engine/regime/` | Raw signal readings |
| Market quotes | `data/market/` | Stocks, ETFs, indices, crypto |
| Market history | `data/market/` | OHLCV bars |
| Economic data | `data/macro/` | FRED economic series |
| MCP server | `mcp/server/` | Read-only analytical tools |

All endpoints accept anonymous requests. The data is public market and
economic data; no input is persisted.

## What is NOT in the deployment (never existed here)

Client login, advisor authentication, KYC / AML / identity verification,
risk-tolerance and risk-assessment surfaces, financial-planning and
portfolio-construction endpoints, signed-document and signing surfaces, and any
per-client data accessor. These belong to Protocol Wealth's closed systems and
are not part of this repository.

## Posture

The public deployment is read-only. The MCP server's framework posture is
read-only by default (`mcp/server/` — tools do not mutate state). Rate limiting
(per-IP) and open CORS are appropriate for a public-data-only surface with no
PII at risk.
