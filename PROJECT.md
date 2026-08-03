# PROJECT.md — nexus-core

> Loads after `AGENTS.md`. AGENTS.md defines the universal PW standards; this
> file records only what is specific to this repository. Where the two conflict,
> AGENTS.md wins.

**Version:** 1.0.0 | **Created:** 2026-08-03

---

## 1. WHAT THIS REPO IS — AND WHY IT IS DIFFERENT

A regime-adaptive financial analysis engine with MCP tool orchestration,
published to PyPI as **`pw-nexus-core`**.

**This repository is PUBLIC.** Apache-2.0, patent pending, OIN member,
accepting outside contributions. That single fact governs everything else:

- Anything committed here is **world-readable, permanently**, including from
  git history after deletion.
- **No client data, no PII, no account identifiers, no firm-internal
  configuration.** Not in code, not in tests, not in fixtures, not in commit
  messages.
- Issues and PRs are public. Do not reference client situations in them.

Every other active PW repo is private. This one is the exception, and the
habits that are safe there are not safe here.

---

## 2. TECH STACK

| | |
|---|---|
| Language | Python **>=3.12** (CI matrixes 3.12) |
| API | FastAPI + Uvicorn |
| Models | Pydantic 2 |
| Database | asyncpg |
| Analysis | pandas (`>=2.2,<4.0`), numpy, scikit-learn, cvxpy, PyPortfolioOpt |
| HTTP | httpx |
| Logging | structlog |
| Tooling | ruff, mypy, pytest |

Note the pandas range admits the **3.x major line**, and CI resolves it — a dep
bump here genuinely exercises pandas 3 rather than merely permitting it.

---

## 3. DIRECTORY MAP

`CLAUDE.md` §5 scopes sub-agents by layer against this section.

| Layer | Path |
|---|---|
| Package root | `src/nexus_core/` — 181 modules |
| HTTP app | `src/nexus_core/app/` |
| Analysis engine | `src/nexus_core/engine/` |
| MCP tools | `src/nexus_core/mcp/` |
| Planning / rebalancing | `src/nexus_core/planning/`, `src/nexus_core/rebalancing/` |
| Compliance | `src/nexus_core/compliance/` |
| Data adapters | `src/nexus_core/data/` |
| Scheduled jobs | `src/nexus_core/jobs/` |
| CLI | `src/nexus_core/cli.py` |
| Tests | `tests/` — 122 test modules |

---

## 4. RELEASE

**Merging does not publish.** `publish-pypi.yml` triggers only on
`release: published` and `workflow_dispatch`, so a dependency bump landing on
`main` cannot ship to PyPI by itself.

That workflow is **not exercised by PR CI** — a green PR says nothing about
whether the release path still works. Actions in it are SHA-pinned with version
comments; a bump to those pins is unverifiable until the next real release.

---

## 5. COMPLIANCE OBLIGATIONS SPECIFIC TO THIS REPO

Because it is public and Apache-2.0:

- **Every `.py` file needs an SPDX-License-Identifier.** Enforced by a required
  check; a new file without one fails CI.
- **Dependency licences are scanned.** A dependency with an incompatible licence
  fails the build, not a review.
- Advisory output carries disclaimers (`src/nexus_core/disclaimers.py`) — that
  text is regulated, and per `CLAUDE.md` §2 it is not delegable to another agent.

---

## 6. COMMANDS

```bash
pip install -e ".[dev]"
ruff check .
mypy src
pytest
```

---

## 7. CI GATES

Required status checks on `main`:

- `ruff + mypy + pytest`
- `Scan dependency licenses`
- `Verify SPDX-License-Identifier on .py files`

Branch protection is strict. Dependabot covers **pip and github-actions**;
minor/patch auto-merges once every check passes, majors never do.

---

## 8. THINGS TO WATCH

- **Public is forever.** The single highest-consequence mistake available in
  this repo is committing something that should have been private. Treat every
  fixture and every test as published.
- **`NEXUS_API_KEYS` accepts raw keys with no length or entropy floor**
  (`access_gate.py`). Tracked in #288 — do not assume the format is validated.
- **Release-path changes are unverifiable pre-merge.** See §4. If you touch
  `publish-pypi.yml`, watch the next release.

---

*Changes to this file should be reviewed like code.*
