# AGENTS.md

Instructions for AI coding agents (and human contributors) working in this repo.
This is a quick pointer; the authoritative detail lives in
[`CLAUDE.md`](CLAUDE.md) (architecture, conventions, boundaries),
[`CONTRIBUTING.md`](CONTRIBUTING.md) (workflow, DCO), and [`README.md`](README.md).
Read `CLAUDE.md` before any non-trivial change.

## What this is

nexus-core is a public, read-only, **educational** financial-analysis engine
(Apache-2.0, Python 3.12, FastAPI + FastMCP) deployed at https://nexusmcp.site.
It holds **no client data and no PII**. Nothing here is investment advice.
Operated by Protocol Wealth, LLC (SEC-registered RIA).

## Hosted access model

Production Nexus is a split surface. Hosted native `/mcp` may stay public as a
low-risk demo endpoint (`NEXUS_PUBLIC_MCP_PROFILE=demo`, transparent OAuth for
remote clients). Hosted REST/JSON calculation paths (`/api/*`,
`/api/planning/tools/*`, and legacy `/mcp/tools/*`) are service-key gated with
`NEXUS_ACCESS_MODE=restricted` + `NEXUS_API_KEYS`; `pw-api` owns the
server-to-server key. Browser apps such as PWOS/PWPortal should call their own
BFF/API routes and must not embed Nexus service credentials.

Private ingestion stays outside this repo. PWOS `/market-data` may ingest
Seeking Alpha CSV/XLSX screens, Schwab/custodian files, tracking records, and
client assignments. Nexus may receive only de-identified candidate symbols,
screened fields, and caller-supplied option-chain facts for public-safe
calculation.

## Setup, build, test, lint

```bash
pip install -e ".[dev,serve]"   # deployed surface (market + mcp) + dev tooling

pytest                          # full suite; hermetic, no network/keys needed
ruff check src/ tests/          # lint (line-length 100, target py312)
mypy --strict src/nexus_core/   # types
```

All three (pytest, ruff, `mypy --strict`) must pass before opening a PR — CI now
gates on them (`.github/workflows/ci.yml`), alongside the SPDX-header and
license-compliance checks.

## Run the server

```bash
nexus-core serve     # public HTTP API + MCP-over-HTTP at http://127.0.0.1:8080
nexus-core mcp       # MCP server over stdio (Claude Desktop / local clients)
nexus-core snapshot  # daily benchmark snapshot (Cloud Run Job entrypoint)
```

No env vars are required; every external integration degrades to `None`/empty/`503`
when its key is absent. A free `FRED_API_KEY` sharpens the macro signals.
`MCP_OAUTH_SIGNING_KEY` is optional and only enables the hosted transparent-OAuth
flow for remote MCP clients; omit it for local open `/mcp`.

## Project layout

- `src/nexus_core/app/` — public HTTP API + MCP-over-HTTP deployment. `main.py`
  is the `create_app()` factory; one `build_*_router` per module.
- `src/nexus_core/engine/` — pure analytical engines: `regime/`, `scoring/`
  (8-check EMF), `pricing/`, `lp/`, `planning/`.
- `src/nexus_core/data/` — provider clients (`market/`, `macro/`, `edgar/`,
  `derivatives/`, `onchain/`); all sync `httpx`.
- `src/nexus_core/mcp/server/` — FastMCP tool registry.
- `src/nexus_core/disclaimers.py` — the single source of truth for disclaimer copy.
- `tests/` — `test_<module>.py` mirroring source; hermetic.

## Conventions (non-negotiable)

- **SPDX header on every new `.py`** (CI-enforced):
  ```python
  # SPDX-License-Identifier: Apache-2.0
  # Copyright 2026 Protocol Wealth, LLC and contributors.
  ```
- **DCO sign-off on every commit:** `git commit -s`. Conventional-commit prefixes.
- **Sync handlers + sync `httpx`.** REST handlers are sync `def` (FastAPI
  threadpools them). Only `asyncpg` DB code is `async`.
- **Heavy/optional deps are lazy-imported** inside functions and gated behind a
  `pyproject.toml` extra. Keep them off the core import path. No `scikit-learn`.
- **New dep ⇒ a license-name comment** in `pyproject.toml`.

## Hard NOs

- **No PII or secrets** anywhere — code, tests, fixtures, examples, commit
  messages. Planning inputs are de-identified (age, never date of birth);
  identity fields are rejected by the gateway.
- **No public write endpoints / no HTTP-triggered state mutation.** The posture
  is read-only; the only writer is the daily snapshot job.
- **No AGPL / GPL-3.0 / SSPL dependencies** (the license-compliance Action fails
  the build otherwise).
- **Disclaimers come from `disclaimers.py`** — never hand-write one. Every new
  output surface imports the appropriate variant.
- **Do not weaken the not-advice posture.** Outputs are educational signals, not
  recommendations. Confidence tiers are probabilistic labels, never buy/sell/hold;
  never emit a tier on insufficient evaluated checks.
- **EMF framework definitions are governed** (regime states, layer model,
  thresholds, 8-check set, confidence tiers). Changing them is a partner/CCO
  decision, not a routine edit — stop and ask.

## MCP / agent affordances

- MCP endpoint: `https://nexusmcp.site/mcp`; the authoritative tool list is
  `tools/list`. Setup: [`/mcp-guide`](https://nexusmcp.site/mcp-guide). Agent
  site map: [`/llms.txt`](https://nexusmcp.site/llms.txt).
- New MCP tools: read-only, `ToolAnnotations(readOnlyHint=True)`, a rich routing
  docstring, and never embed credentials or env-var names in the description.

## Security

Report vulnerabilities privately to **security@protocolwealthllc.com** — see
[`SECURITY.md`](SECURITY.md) / `/.well-known/security.txt`. Do not open public
issues for security reports.
