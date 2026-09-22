# AGENTS.md — nexus-core

Engineering and regulatory standards for every agent are `~/projects/AGENTS.md`.
Where this file conflicts with that one, that one wins. This file is only what
is specific to this repository. It does not describe what is live.

[`PROJECT.md`](PROJECT.md) is the operating contract for this repository.
Workflow and DCO live in [`CONTRIBUTING.md`](CONTRIBUTING.md). Public surface
and install guidance live in [`README.md`](README.md). Deploy procedure lives
in [`DEPLOY.md`](DEPLOY.md).

## What this is

nexus-core is a public, read-only, **educational** financial-analysis engine
(Apache-2.0, Python 3.12, FastAPI + FastMCP) deployed at https://nexusmcp.site.
It holds **no client data and no PII**. Nothing here is investment advice.
Operated by Protocol Wealth, LLC (SEC-registered RIA). Published to PyPI as
`pw-nexus-core`.

Sibling: [`pwos-core`](https://github.com/Protocol-Wealth/pwos-core) — TypeScript
compliance primitives. **Math + analytical engine lives here; data shapes +
audit/compliance primitives live in pwos-core.** Do not port primitives across
that boundary. Closed runtime + consumer repos (`pw-portal`, `pw-onchain`,
`pw-infrastructure`, and others listed on the security page) stay closed: do
not port code from those into here, or vice versa.

### Layout

- `src/nexus_core/app/` — public HTTP API + MCP-over-HTTP deployment. `main.py`
  is the `create_app()` factory; one `build_*_router` per module.
- `src/nexus_core/engine/` — pure analytical engines: `regime/`, `scoring/`
  (8-check EMF), `pricing/`, `lp/`, `planning/`.
- `src/nexus_core/data/` — provider clients (`market/`, `macro/`, `edgar/`,
  `derivatives/`, `onchain/`); all sync `httpx`.
- `src/nexus_core/mcp/server/` — FastMCP tool registry.
- `src/nexus_core/jobs/daily_snapshot.py` — Cloud Run Job entrypoint (benchmark
  snapshot).
- `src/nexus_core/disclaimers.py` — the single source of truth for disclaimer copy.
- `tests/` — `test_<module>.py` mirroring source; hermetic.
- `examples/` — runnable stubs; they must run without network credentials.

## Commands

```bash
pip install -e ".[dev,serve]"   # what CI installs; deployed surface + dev tooling

pytest                          # full suite; hermetic, no network/keys needed
ruff check src/ tests/          # lint (line-length 100, target py312)
mypy --strict src/nexus_core/   # types
```

All three (pytest, ruff, `mypy --strict`) must pass before opening a PR — CI
gates on them (`.github/workflows/ci.yml`), alongside the SPDX-header and
license-compliance checks.

`[dev]` is tooling only (pytest, ruff, mypy). Without `[serve]` there is no
`fastmcp`, so `mypy --strict src/nexus_core/` cannot type-check the MCP server.
Modular extras (`serve`, `mcp`, `optimization`, `risk`, `pricing`, `edgar`,
`market`, `ai`, `backtest`, `all`) are documented in README § Installation.

```bash
nexus-core serve     # public HTTP API + MCP-over-HTTP at http://127.0.0.1:8080
nexus-core mcp       # MCP server over stdio (Claude Desktop / local clients)
nexus-core snapshot  # daily benchmark snapshot (Cloud Run Job entrypoint)
nexus-core --version
```

`serve` honors `HOST`/`PORT` (Cloud Run supplies `PORT`). `snapshot` writes the
day's benchmark prices to the database and exits.

No env vars are required; every external integration degrades to `None`/empty/`503`
when its key is absent. A free `FRED_API_KEY` sharpens the macro signals.
`MCP_OAUTH_SIGNING_KEY` is optional and only enables the hosted transparent-OAuth
flow for remote MCP clients; omit it for local open `/mcp`. Access-related vars:
`NEXUS_PUBLIC_MCP_PROFILE` (`full` default or `demo`), `NEXUS_ACCESS_MODE`
(`public` default or `restricted`), `NEXUS_API_KEYS` (raw keys or `sha256:<hex>`
digests). Full optional-variable list is in README § Configuration.

### Adding a regime signal, scoring check, HTTP route, or MCP tool

- **Regime signal** → `src/nexus_core/engine/regime/` (`signals.py` +
  `signal_fetcher.py`). **Scoring check** → `src/nexus_core/engine/scoring/`
  (`checks.py` / `emf/`). Add tests under `tests/test_<name>.py`. If the change
  touches the engine contract, update [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
  in the same PR.
- **HTTP route:** add or extend a `build_*_router(...)` factory under
  `src/nexus_core/app/`, then wire it in `app/main.py`'s `create_app()`. Keep
  handlers sync, set an explicit `Cache-Control`, and degrade to 503 (not 500)
  when a required key/provider is absent. Tools compose over the engines — do
  not reimplement engine logic at the route layer.
- **MCP tool:** add to `src/nexus_core/mcp/server/` with
  `@mcp.tool(annotations=_RO_OPEN)` (or `_RO_CLOSED` for pure compute). Attach
  the disclaimer via `_ok`/`_err`. Deployment-specific tools inject via
  `build_server(..., extra_tools=...)` from `app/mcp_mount.py`. Tests use
  `create_app(enable_mcp=False, market=<fake>)` to exercise REST without
  upstreams.

## Endpoint access

Production Nexus is a split surface. **Do not read it as one answer.** Three
groups:

| group | example | unauthenticated |
|---|---|---|
| open | `/`, `/health`, the docs | `200` |
| service-key gated | `/api/*`, legacy `/mcp/tools*` | `401 {"error":"unauthorized"}` |
| native MCP, OAuth | `POST /mcp` | `{"error":"invalid_token"}` **plus** a `WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp"` header |

Hosted native `/mcp` may stay public as a low-risk demo endpoint
(`NEXUS_PUBLIC_MCP_PROFILE=demo`, transparent OAuth for remote clients). Hosted
REST/JSON calculation paths (`/api/*`, `/api/planning/tools/*`, and legacy
`/mcp/tools/*`) are service-key gated with `NEXUS_ACCESS_MODE=restricted` +
`NEXUS_API_KEYS`; `pw-api` owns the server-to-server key. Browser apps such as
PWOS/PWPortal should call their own BFF/API routes and must not embed Nexus
service credentials.

`src/nexus_core/app/access_gate.py` protects `/api/*` and `/mcp/tools*` whenever
`NEXUS_ACCESS_MODE=restricted`, which is how production runs. The code default
is `public`; the deployed environment overrides it. Check the service, not
`access_mode()`.

**`invalid_token` on `POST /mcp` is not evidence the surface is private.** It is
the OAuth handshake starting: the `WWW-Authenticate` header points at the
resource-metadata document, and a remote MCP client that completes the flow gets
in with no service key and no login. Native MCP is a public demo surface by
design. Citing that response as proof of privacy misleads an agent about which
endpoints actually need credentials.

Do not describe the whole surface as "public, read-only": the posture is
read-only, and access is split as above.

Private ingestion stays outside this repo. PWOS `/market-data` may ingest
Seeking Alpha CSV/XLSX screens, Schwab/custodian files, tracking records, and
client assignments. Nexus may receive only de-identified candidate symbols,
screened fields, and caller-supplied option-chain facts for public-safe
calculation.

Path catalog and cache notes live in [`README.md`](README.md). MCP endpoint:
`https://nexusmcp.site/mcp`; the authoritative tool list is `tools/list`. Setup:
[`/mcp-guide`](https://nexusmcp.site/mcp-guide). Agent site map:
[`/llms.txt`](https://nexusmcp.site/llms.txt).

New MCP tools: read-only, `ToolAnnotations(readOnlyHint=True)`, a rich routing
docstring, and never embed credentials or env-var names in the description.

## Boundaries

Hard NOs. Each is enforced by review + tooling where possible.

- **No PII or secrets** anywhere — code, tests, fixtures, examples, commit
  messages. Planning inputs are de-identified (age, never date of birth);
  identity fields are rejected by the gateway.
- **No public write endpoints / no HTTP-triggered state mutation.** The posture
  is read-only; the only writer is the daily snapshot job.
- **No AGPL / GPL-3.0 / SSPL dependencies** (the license-compliance Action fails
  the build otherwise).
- **No AGPL code copied.** OpenBB Platform (AGPL-3.0) and SEC EDGAR Toolkit
  (AGPL-3.0) are listed as architecture references — see [`NOTICE`](NOTICE) and
  [`docs/attribution.md`](docs/attribution.md). Patterns may be studied; bytes
  may not be copied. Clean-room re-derivation only.
- **No client-specific values.** Thresholds, decay constants, regime cutoffs,
  narrative pipeline logic — see [README § What's Open vs Private](README.md#whats-open-vs-private).
- **Disclaimers come from `disclaimers.py`** — never hand-write one. Every new
  output surface imports the appropriate variant.
- **Do not weaken the not-advice posture.** Outputs are educational signals, not
  recommendations. Confidence tiers are probabilistic labels, never buy/sell/hold;
  never emit a tier on insufficient evaluated checks.
- **EMF framework definitions are governed** (regime states, layer model,
  thresholds, 8-check set, confidence tiers). Changing them is a partner/CCO
  decision, not a routine edit — stop and ask.
- **Do not change the calibrated threshold/decay/weight values casually.** These
  are Protocol Wealth's published EMF calibration (EMF is openly published — see
  [protocolwealthllc.com/framework](https://protocolwealthllc.com/framework));
  there is no private companion. `src/nexus_core/engine/regime/thresholds.py` is
  the single source of truth.
- **Do not add a new regime state.** The 5-state model (Growth / Transition /
  Hard Asset / Deflation / Repression) is patent-anchored; expanding it requires
  architecture-level review, not a contributor PR.
- **Do not compute scoring across regime states inside a signal module.** Regime
  classification is one stage; scoring composes on top. Keep the stages separate.
- **No bypassing patent posture.** USPTO #64/034,229 is filed defensively under
  Apache 2.0. Do not remove the patent-pending notice from `README.md`,
  `src/nexus_core/__init__.py`, or shields/badges. Do not author claims of a
  different IP posture in this repo.
- **No `--no-verify` on commits.** No skipped hooks. No `--no-gpg-sign`. If a
  hook fails, fix the root cause.
- **No backwards-compat shims for hypothetical adopters.** This is a scaffold
  framework — adopters take it at the version they fork. Don't add deprecation
  paths or compat layers that aren't load-bearing for current production use.
- **Do not add routes or tools that mutate state** (DB writes from HTTP, external
  API POSTs) without architecture-level review — writes happen only in the Cloud
  Run Job.
- **Do not embed credentials, endpoints, or environment-variable names** in
  tool/route descriptions.

### Conventions (non-negotiable)

- **SPDX header on every new `.py`** (CI-enforced):
  ```python
  # SPDX-License-Identifier: Apache-2.0
  # Copyright 2026 Protocol Wealth, LLC and contributors.
  ```
- **DCO sign-off on every commit:** `git commit -s`. Conventional-commit prefixes.
  *Verifying this on a pull request:* read the PR head, not the checkout —
  `gh api repos/$REPO/pulls/$N/commits --jq '.[].commit.message'`. A CI checkout
  of a PR lands on `refs/pull/N/merge`, an ephemeral merge commit GitHub
  synthesizes, so `git show -s --format='%(trailers)' HEAD` returns empty for
  every PR regardless of what the author signed. That has produced four false
  "missing DCO sign-off" findings here (#296, #297, #302, #303).
- **Sync handlers + sync `httpx`.** REST handlers are sync `def` (FastAPI
  threadpools them). Only `asyncpg` DB code is `async`.
- **pydantic v2 for boundary validation** (`BaseModel`, `ConfigDict`, `Field`).
- **Heavy/optional deps are lazy-imported** inside functions and gated behind a
  `pyproject.toml` extra. Keep them off the core import path. No `scikit-learn`.
- **New dep ⇒ a license-name comment** in `pyproject.toml`.
- **One concept per file.** `snake_case.py` modules.
- **Tests under `tests/test_<module>.py`** matching source file names. Hermetic —
  no network calls, no live data, no API keys, no real adopter credentials.

## Deploy and CI

- **CI** (`.github/workflows/ci.yml`): `pip install -e ".[dev,serve]"`, then
  `ruff check src/ tests/`, `mypy --strict src/nexus_core/`, and pytest with an
  80% coverage floor. SPDX headers: `.github/workflows/spdx-headers.yml`.
  License scan: `.github/workflows/license-compliance.yml`.
- **Release and watch-outs:** [`PROJECT.md`](PROJECT.md) §4 and §8.
- **Deploy:** [`DEPLOY.md`](DEPLOY.md) owns the Cloud Run web service, snapshot
  Job, and Scheduler procedure. The snapshot is a Cloud Run Job (`nexus-core
  snapshot`), not an HTTP route. Secrets live in Secret Manager — no credentials
  in config or code.
- **Rate limit:** in-process limiter in `src/nexus_core/app/ratelimit.py`;
  `/health` and `/mcp` are exempt.
- **Transparent MCP OAuth:** `src/nexus_core/app/mcp_oauth.py` is stateless and
  anonymous when `MCP_OAUTH_SIGNING_KEY` is set.

Report vulnerabilities privately to **security@protocolwealthllc.com** — see
[`SECURITY.md`](SECURITY.md). Do not open public issues for security reports.

## Things that have bitten

- **DCO on GitHub's merge ref.** A CI checkout of a PR is `refs/pull/N/merge`.
  Checking trailers on `HEAD` there is empty for every PR. Read the PR commits
  via the GitHub API (see Conventions above). False findings: #296, #297, #302,
  #303.
- **`pip install -e ".[dev]"` is not the gate.** CI and a clean type-check need
  `pip install -e ".[dev,serve]"` so `fastmcp` is present.
- **`invalid_token` on `POST /mcp` is the OAuth handshake starting**, not proof
  the MCP surface is private. See Endpoint access.
- **Code default `NEXUS_ACCESS_MODE=public` is not the hosted posture.**
  Production runs `restricted`. Check the service.
- Further watch-outs, including `NEXUS_API_KEYS` format, are in
  [`PROJECT.md`](PROJECT.md) §8.
