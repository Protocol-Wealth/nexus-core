# Next session — nexus-core handoff

Forward-looking handoff. For the full live snapshot read [CURRENT-STATE.md](CURRENT-STATE.md);
for change history read [CHANGELOG.md](CHANGELOG.md).

## Where things stand (2026-05-30)

- **Deployed:** `nexus-core-00040-cld` serving 100% on [nexusmcp.site](https://nexusmcp.site)
  (Cloudflare → Cloud Run `pwllc-prod`/`us-central1`). Version `0.1.0`.
- **Health:** all upstreams green — FRED key rotated + working (regime runs on real signals);
  quotes, Deribit, DefiLlama, EDGAR all live.
- **Quality:** suite **724** tests; `ruff` + `mypy --strict` clean and **CI-enforced**
  (`.github/workflows/ci.yml`, 80% coverage floor). `main` is clean.
- **Tooling note:** CI runs only lint/type/test + SPDX + license-scan + CodeQL — there is **no
  deploy step**; deploys are manual (see below).

## What shipped recently

The "platform hardening" pass (see CHANGELOG `[Unreleased]`): native MCP planning tools +
`health`/`describe`/`get_quotes`; canonical disclaimers + `NOT APPLICABLE` score gating;
error masking + input validation + `defi_protocol` TVL fix + FRED 429-retry; data provenance
(`as_of`/`source`/`market_status`); `breadth` + `precious_metals` signals; `/llms.txt` +
`AGENTS.md` + `/.well-known/security.txt` + security headers; and the EMF coverage changes
(ASAN fail-safe + 5 buckets, Perez capex-light, crypto/ETF layer router) with
`SHARED/strategy/emf-canonical.md` updated to match.

## Open items (nothing blocking)

Operator / governance:
- **Cascade nothing further for EMF** — `emf-canonical.md` is already updated; just confirm the
  thresholds the new ASAN buckets use (technology_hardware/communication/materials/utilities/
  real_estate) match your intent (they were ratified "as-is" this session).

Engineering follow-ups (lower priority):
- Reconcile the two `SECURITY.md` files (root vs `.github/`) into one canonical file.
- Run `ruff format` (66 files would reformat; not currently CI-enforced — add it after, or leave).
- Canon vs code **check numbering** mismatch (Perez 7/ASAN 8 in canon; 5/8 in code) — content is
  aligned, numbering is cosmetic; reconcile only if it bothers a reader.
- Roadmap §5 tier-3/4 capability features remain unbuilt (real options chains + IV,
  `score_portfolio`, `defi_yields`/`defi_risk`, `resolve_symbol`, structured score provenance).
- LP roadmap (unchanged): Aerodrome Slipstream full coverage via Envio, Arbitrum V3 subgraph,
  Uniswap V4, Solana CLMM — see CURRENT-STATE "Next".

## How to deploy + verify

```bash
# from a clean main (deploy preserves all secrets incl. MCP_OAUTH_SIGNING_KEY —
# do NOT pass --set-secrets; DEPLOY.md's list is stale and omits it)
gcloud run deploy nexus-core --source . --region us-central1 --project pwllc-prod

# verify (direct origin bypasses the Cloudflare cache)
BASE=https://nexus-core-XXXXXX-uc.a.run.app   # printed by the deploy
curl $BASE/health
curl $BASE/api/regime/signals    # NOTE: flat dict, not nested under "signals"
curl $BASE/mcp/tools             # planning handshake: {contractVersion:"0.1.0", tools:[...]}
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
