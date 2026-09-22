# PROJECT.md — nexus-core

> Loads after `AGENTS.md`. `~/projects/AGENTS.md` is the universal standard.
> This file is the operating contract for this repository. Where they conflict,
> `~/projects/AGENTS.md` wins, then this repo's `AGENTS.md`.

## 1. What this repo is

A regime-adaptive financial analysis engine with MCP tool orchestration,
published to PyPI as `pw-nexus-core`.

**This repository is public.** Apache-2.0, patent pending, accepting outside
contributions. That fact governs everything else:

- Anything committed here is world-readable, including from git history after deletion.
- No client data, no PII, no account identifiers, and no firm-internal
  configuration. Not in code, tests, fixtures, or commit messages.
- Issues and pull requests are public. Do not reference client situations in them.

Every other active Protocol Wealth repository is private. Habits that are safe
there are not safe here.

## 2. Tech stack

Declared in `pyproject.toml`. Do not copy version ranges into this file.

| | |
|---|---|
| Language | Python. CI uses 3.12 (`.github/workflows/ci.yml`). |
| API | FastAPI + Uvicorn |
| Models | Pydantic 2 |
| Database | asyncpg |
| Analysis | pandas, numpy, PyPortfolioOpt. No scikit-learn. |
| HTTP | httpx |
| Logging | structlog |
| Tooling | ruff, mypy, pytest |

## 3. Directory map

`AGENTS.md` (Layout) is the agent-facing map. These paths exist:

| Layer | Path |
|---|---|
| Package root | `src/nexus_core/` |
| HTTP app | `src/nexus_core/app/` |
| Analysis engine | `src/nexus_core/engine/` (planning lives under `engine/planning/`) |
| MCP tools | `src/nexus_core/mcp/` |
| Planning / rebalancing packages | `src/nexus_core/planning/`, `src/nexus_core/rebalancing/` |
| Compliance | `src/nexus_core/compliance/` |
| Data adapters | `src/nexus_core/data/` |
| Scheduled jobs | `src/nexus_core/jobs/` |
| CLI | `src/nexus_core/cli.py` |
| Tests | `tests/` |

## 4. Release

**Merging does not publish.** `publish-pypi.yml` triggers only on
`release: published` and `workflow_dispatch`. A dependency bump on `main`
does not ship to PyPI by itself.

That workflow is not exercised by pull-request CI. A green pull request says
nothing about whether the release path still works. Actions in it are
SHA-pinned. A bump of those pins is unverifiable until the next real release.

## 5. Compliance obligations specific to this repo

Because it is public and Apache-2.0:

- Every `.py` file needs an SPDX-License-Identifier. A required check fails
  the pull request without one.
- Dependency licences are scanned. An incompatible licence fails the build.
- Advisory output carries disclaimers from `src/nexus_core/disclaimers.py`.
  Per `~/projects/AGENTS.md` §0.3, client-facing regulatory language is not
  an agent decision.

## 6. Commands

```bash
pip install -e ".[dev,serve]"
ruff check src/ tests/
mypy --strict src/nexus_core/
pytest
```

`[dev]` alone does not install `fastmcp`. CI installs `.[dev,serve]`.

## 7. CI gates

Required status checks:

```bash
gh api repos/Protocol-Wealth/nexus-core/branches/main/protection \
  --jq '.required_status_checks.contexts'
```

Dependabot opens pull requests for pip and github-actions
(`.github/dependabot.yml`). `.github/workflows/dependabot-auto-merge.yml`
auto-merges semver minor and patch updates after the other checks pass.
Major updates do not auto-merge.

## 8. Things to watch

- **Public is forever.** The highest-consequence mistake in this repo is
  committing something that should have been private. Treat every fixture
  and every test as published.
- **`NEXUS_API_KEYS` accepts raw keys with no length or entropy floor**
  (`src/nexus_core/app/access_gate.py`). Tracked in GitHub issue #288.
  Do not assume the format is validated.
- **Release-path changes are unverifiable before merge.** See §4. If you
  touch `publish-pypi.yml`, watch the next release.

*Changes to this file should be reviewed like code.*
