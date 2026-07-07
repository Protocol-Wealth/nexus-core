# Next session — nexus-core handoff

Forward-looking handoff. For the full live snapshot read [CURRENT-STATE.md](CURRENT-STATE.md);
for change history read [CHANGELOG.md](CHANGELOG.md).

## Where things stand (2026-07-01)

- **Deployed:** [nexusmcp.site](https://nexusmcp.site) is serving version
  `0.1.0` (Cloudflare → Cloud Run `pwllc-prod`/`us-central1`).
- **Health:** `/health` returns
  `{"status":"ok","service":"nexus-core","version":"0.1.0"}`.
- **Public tool surface:** `/mcp/tools` returns contractVersion `0.1.0` with
  23 PII-free planning tools. `/openapi.json`, `/llms.txt`, OAuth metadata, and
  `/mcp-guide` are live public discovery surfaces.
- **GitHub:** no open PRs; seven open issues (#197-#203) track all current
  outstanding/future-build lanes from the roadmap.
- **Quality:** `ruff` + `mypy --strict` + `pytest` are CI-enforced
  (`.github/workflows/ci.yml`, 80% coverage floor).
- **Tooling note:** CI runs only lint/type/test + SPDX + license-scan + CodeQL — there is **no
  deploy step**; deploys are manual (see below).

## Local source since last live smoke (2026-07-06)

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
