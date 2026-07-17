# Archived next-session handoff — nexus-core

> **Historical reference, not current state.** This file preserves an earlier
> operator handoff and is no longer maintained as a second status source. Read
> [CURRENT-STATE.md](CURRENT-STATE.md) for deployed truth,
> [ROADMAP.md](ROADMAP.md) plus GitHub Issues for current work, and
> [VALIDATION.md](VALIDATION.md) for executed checks. Where this archived material
> differs, those sources win.

## Current pointer (2026-07-17 ET)

- Commit `d528389` is deployed on Cloud Run revision
  `nexus-core-00068-5pf` at 100% traffic.
- Onchain accounting P0-P4 is live through restricted REST contract `0.1.0`.
  It is calculation substrate, not a client statement or tax-return workflow.
- Accounting is absent from native MCP; #259 tracks the full-profile adapter and
  keeps the hosted demo profile unchanged.
- Contract `0.2.0` source implements #260's accounting-semantics and replay
  hardening. CCO/CIO/CTO approved methodology 2.0/FIFO for operational use on
  2026-07-17; private consumer deployment and post-deployment review remain.
- Private ingestion, client linkage, statement production/review/release, and
  books-and-records retention remain outside nexus-core.

## Archived 2026-07-01/07 handoff material

The remainder is retained for historical context and must not be used for current
deployment, tool-count, PR, issue, or validation claims.

### Local source since the archived live smoke (2026-07-06)

- `collar_book` now supports conservative executable-fill modeling over
  caller-supplied pre-screened collar candidates. The engine plus REST/MCP
  parsers accept `executable_net_credit` or `call_bid`/`put_ask` and return
  stock price, shares, per-line fill haircut, executable income/yield, and
  portfolio-level executable yield only when every held line has executable
  pricing.
- The access boundary now supports `NEXUS_PUBLIC_MCP_PROFILE=demo` for a
  low-risk native MCP demo surface and `NEXUS_ACCESS_MODE=restricted` +
  `NEXUS_API_KEYS` for `/api/*`, `/api/planning/tools/*`, and legacy
  `/mcp/tools/*`. `pw-api` should call `/api/planning/tools/{tool_id}` with
  `NEXUS_SERVICE_API_KEY` when restricted mode is enabled.
- This is still an educational advisor worksheet. Do not convert it into an
  order surface, live-chain attestation, custodian execution record, or
  client-specific recommendation inside nexus-core.
- Before PR/deploy, rerun the targeted collar-book route/engine/MCP tests plus
  the full local gate if time permits; live endpoints were not re-smoked in this
  local docs pass.

## What shipped recently

The current public surface includes market/macro data, EMF scoring/regime,
educational options and crypto-options overlays, anonymous on-chain/LP/vault
analytics, benchmark snapshots, native MCP tools, transparent MCP OAuth
metadata, and 23 PII-free planning tools served through both native MCP and the
REST planning gateway.

## Open items (nothing blocking)

Operator / governance:
- **Issue #197:** decide which generic planning/report analytics are public-safe
  enough for nexus-core and keep client context, suitability, report production,
  artifact receipts, and private workflow state out.
- **Issue #202:** settle governance/tooling cleanup items: EMF numbering,
  display-only signal decision, and possible `ruff format` gate.

Engineering follow-ups (lower priority):
- **Issue #198:** planning assumptions provenance.
- **Issue #199:** LP/indexer expansion and data quality.
- **Issue #200:** crypto-options follow-ups.
- **Issue #201:** agent analytics capability backlog.
- **Issue #203:** equity-research vertical gates and buildout.

## How to deploy + verify

```bash
# from a clean main; DEPLOY.md owns the full source-build/secret mapping
gcloud run deploy nexus-core --source . --region us-central1 --project pwllc-prod

# verify (direct origin bypasses the Cloudflare cache)
BASE=https://nexus-core-XXXXXX-uc.a.run.app   # printed by the deploy
curl $BASE/health
curl $BASE/api/regime/signals    # NOTE: flat dict, not nested under "signals"
curl $BASE/api/planning/tools    # planning handshake: {contractVersion:"0.1.0", tools:[...]}
curl $BASE/llms.txt
```

Local gate before any PR: `ruff check src/ tests/` · `mypy --strict src/nexus_core/` · `pytest`.

## Gotchas worth remembering

- `/api/regime/signals` returns a **flat** dict (e.g. `gold_spx_ratio` at top level), not nested
  under a `signals` key.
- The Copilot-Autofix bot (`github-code-quality`) pushes autofix commits onto PR branches —
  `git pull` before pushing follow-ups.
- A FRED key rotation needs a **redeploy** to take effect (Cloud Run pins secret versions at deploy).
- `nexusmcp.site/.well-known/security.txt` is served by **Cloudflare** (org-wide, far-future
  Expires, correct contact) and shadows the app route at the edge; the app's own RFC-9116 version
  (rolling Expires) serves on the origin.
