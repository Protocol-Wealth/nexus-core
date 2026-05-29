# nexus-core — open-source regime-adaptive financial analysis engine

> Repo: `Protocol-Wealth/nexus-core` · License: Apache 2.0 · Patent Pending: USPTO #64/034,229 · OIN member.
> Open-source extraction of the [Protocol Wealth research engine](https://nexusmcp.site); nothing in this repo is client-specific or proprietary to PW.

## What This Is

Python 3.12 package — regime-adaptive financial analysis engine that exposes capabilities as MCP (Model Context Protocol) tools. Any MCP-compatible AI client (Claude, GPT, Gemini) can call regime-aware analysis without re-implementing financial domain logic.

Built and tested in production by Protocol Wealth LLC (SEC-registered RIA, CRD #335298). The public deployment at [nexusmcp.site](https://nexusmcp.site) runs the `nexus_core.app` surface from **this** repository — a read-only HTTP API + MCP-over-HTTP server; see [`DEPLOY.md`](DEPLOY.md). The README's *Status* section is the source of truth on maturity — this is a scaffold / alpha framework, not a production-ready product.

Sibling: [`pwos-core`](https://github.com/Protocol-Wealth/pwos-core) — TypeScript compliance primitives. **Math + analytical engine lives here; data shapes + audit/compliance primitives live in pwos-core.** Do not port primitives across that boundary.

## Repo Structure

```
nexus-core/
├── src/nexus_core/
│   ├── engine/
│   │   ├── regime/        # Signal ensemble, classifier, hysteresis, thresholds, dampener
│   │   ├── scoring/       # N-check durability scoring + enhancements (consistency, base rate, adversarial)
│   │   ├── optimization/  # PyPortfolioOpt + Riskfolio-Lib wrappers
│   │   ├── risk/          # empyrical-reloaded + pyfolio-reloaded wrappers
│   │   └── pricing/       # QuantLib + FinancePy wrappers
│   ├── financials/        # FinanceToolkit adapter — statements, ratios, performance, models, risk
│   ├── ai/
│   │   ├── llm/           # FinGPT RAG integration
│   │   ├── research/      # FinRobot multi-agent equity research
│   │   └── sentiment/     # FinBERT sentiment classification
│   ├── data/
│   │   ├── edgar/         # edgartools + Arelle + sec-parser SEC integration
│   │   ├── market/        # yfinance market data
│   │   └── onchain/       # Ethereum-ETL blockchain pipeline
│   ├── compliance/
│   │   ├── ofac/          # Moov Watchman client (HTTP)
│   │   └── xbrl/          # Arelle XBRL validation
│   ├── planning/
│   │   ├── monte_carlo/   # Retirement simulation
│   │   └── backtest/      # zipline-reloaded wrapper
│   ├── rebalancing/
│   │   └── tlh/           # Wash-sale-aware tax-loss harvesting
│   ├── mcp/
│   │   └── server/        # FastMCP server entrypoint + @mcp.tool() registry
│   ├── app/               # Public HTTP API + MCP-over-HTTP deployment (nexusmcp.site)
│   └── cli.py             # nexus-core CLI — serve (HTTP) / mcp (stdio)
├── tests/                 # pytest suites — match source files (test_<module>.py)
├── examples/              # Runnable examples: basic_regime, basic_scoring, mcp_server
├── docs/
│   ├── ARCHITECTURE.md    # Signal ensemble, regime states, scoring checks
│   ├── PATENT.md          # USPTO #64/034,229 detail + defensive posture
│   └── attribution.md     # Per-capability provenance + license posture
└── .github/
    ├── workflows/         # license-compliance.yml
    └── dependabot.yml     # pip + github-actions, weekly Monday bumps
```

Many subpackages are currently scaffold (`__init__.py` docstring only) pending implementation. Check the actual module contents before assuming an API exists.

## Tech Stack

| Layer | Choice |
|-------|--------|
| Language | Python 3.12+ (`requires-python = ">=3.12"`) |
| Test runner | pytest 8.x |
| Lint / type | ruff + mypy |
| Validation | pydantic v2 (boundary validation only) |
| Build | setuptools + wheel via `pyproject.toml` |
| MCP transport | FastMCP (`@mcp.tool()` decorator) |
| Web framework | FastAPI + uvicorn (for MCP-over-HTTP) |
| Data layer | PostgreSQL + Redis (declared; wiring per-adopter) |
| CI | GitHub Actions — license-compliance scan; CodeQL (auto-config) |
| License | Apache 2.0 + USPTO #64/034,229 defensive patent + OIN member |

## Development

```bash
pip install -e ".[all]"           # All optional extras (heavy: torch, transformers, QuantLib)
pip install -e ".[dev]"           # Dev tooling only (pytest, pytest-asyncio, pytest-cov, ruff, mypy)
pip install -e "."                # Core only (regime + scoring scaffolding)

pytest                            # Full suite
pytest tests/test_regime_engine.py
ruff check src/ tests/
mypy src/nexus_core/
```

Use modular installs in CI — `[all]` pulls heavy AI deps. Modular install patterns are documented in [README § Installation](README.md#installation).

## Conventions

- **SPDX header on every `.py` file.** Canonical 2-line block, prepended above any module docstring or import:
  ```python
  # SPDX-License-Identifier: Apache-2.0
  # Copyright 2026 Protocol Wealth, LLC and contributors.
  ```
- **DCO sign-off on every commit.** `git commit -s -m "feat: ..."`. See [CONTRIBUTING § Developer Certificate of Origin](CONTRIBUTING.md#developer-certificate-of-origin).
- **Conventional commits** for type prefixes (`feat:`, `fix:`, `chore:`, `docs:`, `deps:`, `ci:`).
- **One concept per file.** `snake_case.py` modules. Modules ≤ ~300 LOC where possible; long modules signal a missing split.
- **pydantic v2 for boundary validation** (`BaseModel`, `ConfigDict`, `Field`). Don't introduce dataclasses where pydantic models would also enforce runtime types.
- **Tests under `tests/test_<module>.py`** matching source file names. Hermetic — no network calls, no live data, no API keys, no real adopter credentials.
- **Stubs in `examples/`.** Example scripts must run without network credentials — use the stub data providers patterns in `basic_regime.py` / `basic_scoring.py`.
- **License-name comment on every new dep** in `pyproject.toml` (e.g. `"yfinance>=0.2.48",  # Apache 2.0`). The license-compliance workflow will fail the build if a forbidden license sneaks in.

## Adding a Regime Signal or Scoring Check

1. Identify the layer:
   - **Regime signal** → `src/nexus_core/engine/regime/` — new voting signal in the ensemble.
   - **Scoring check** → `src/nexus_core/engine/scoring/` — new check function returning a tier or score component.
2. Add the module: `src/nexus_core/engine/<regime|scoring>/<name>.py`. Prepend the SPDX block.
3. Add tests under `tests/test_<name>.py` covering happy path + the regime-state edge cases (Growth / Transition / Hard Asset / Deflation / Repression).
4. Re-export from the subpackage's `__init__.py` if it's part of the public API surface.
5. If the change touches the engine's contract (new signal output type, new regime state, new score component) update [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) in the same PR.
6. Run `pytest && ruff check src/ tests/ && mypy src/nexus_core/` — all three must pass before opening the PR.

**Do NOT:**
- Change the calibrated threshold/decay/weight values casually. These ARE Protocol Wealth's published EMF calibration (EMF is an openly-published framework — see [protocolwealthllc.com/framework](https://protocolwealthllc.com/framework)); there is no private companion. Update them only to track the published framework, with the backtest rationale, and keep `regime/thresholds.py` the single source of truth.
- Add a new regime state. The 5-state model (Growth / Transition / Hard Asset / Deflation / Repression) is patent-anchored; expanding it requires architecture-level review, not a contributor PR.
- Compute scoring across regime states inside a signal module. Regime classification is one stage; scoring composes on top. Keep the stages separate.

## Adding an MCP Tool

1. Tool module: `src/nexus_core/mcp/server/<area>.py` — or extend an existing area file. Prepend the SPDX block.
2. Decorator: `@mcp.tool()` from FastMCP. Tools compose over the regime + scoring engines — do not reimplement engine logic at the tool layer.
3. **ResponseFilter hook pattern** for adopter-supplied auth / PII redaction / audit-row generation. The tool must accept the filter as a parameter (or pull from request context), never assume an in-process filter is installed.
4. Write the tool description string for the LLM consumer. Name: inputs, outputs, side effects (none expected — tools are read-only by default), regime-state sensitivity if any.
5. Add tests under `tests/test_mcp_<area>.py` exercising the tool through a FastMCP test client.
6. Update `examples/mcp_server.py` if the new tool changes the public registry shape.

**Do NOT:**
- Add tools that mutate adopter state (database writes, external API POSTs) without an architecture-level review — the framework's posture is read-only by default.
- Embed adopter-specific credentials, endpoints, or environment-variable names in tool descriptions.
- Bypass the ResponseFilter hook. If a tool can't be filtered, it doesn't belong here.

## Boundaries

Hard NOs. Each is enforced by review + tooling where possible:

- **No client-specific values.** Thresholds, decay constants, regime cutoffs, production tool wiring, narrative pipeline logic — see [README § What's Open vs Private](README.md#whats-open-vs-private).
- **No PII / secrets / vendor API keys** in tests, fixtures, examples, commit messages, or issue templates.
- **No AGPL code copied.** OpenBB Platform (AGPL-3.0) and SEC EDGAR Toolkit (AGPL-3.0) are listed as architecture references — see [README § Reference Architecture](README.md#reference-architecture-patterns-only--agpl-code-not-copied) and [`docs/attribution.md`](docs/attribution.md). Patterns may be studied; bytes may not be copied. Clean-room re-derivation only.
- **No bypassing patent posture.** USPTO #64/034,229 is filed defensively under Apache 2.0. Do not remove the patent-pending notice from `README.md`, `src/nexus_core/__init__.py`, or shields/badges. Do not author claims of a different IP posture in this repo.
- **No `--no-verify` on commits.** No skipped hooks. No `--no-gpg-sign`. If a hook fails, fix the root cause.
- **No commits without SPDX header** on new `.py` files. The `examples/` + `src/` + `tests/` trees are fully covered as of PR #4 (May 2026); maintain coverage on additions.
- **No silent license-class additions to `pyproject.toml`.** New deps come with the license-name comment. The license-compliance GitHub Action fails the build if a forbidden license (GPL-3.0 / AGPL / SSPL) is detected at install time.
- **No backwards-compat shims for hypothetical adopters.** This is a scaffold framework — adopters take it at the version they fork. Don't add deprecation paths or compat layers that aren't load-bearing for current production use.

## Cross-Repo Notes

- **[`pwos-core`](https://github.com/Protocol-Wealth/pwos-core) (sibling, TypeScript)** — compliance primitives published to npm under `@protocolwealthos/*`. Per the v0.5.0 boundary: math lives in nexus-core; data shapes + audit/compliance hooks live in pwos-core. When extracting a primitive across the boundary, generalize the API — drop framework coupling, drop PW-specific identifiers, expose hooks for caller-specific behavior.
- **Reference-consumer apps** are separate repos:
  - [`pw-os-v2`](https://github.com/Protocol-Wealth/pw-os-v2) — TypeScript consumer of pwos-core; deployed at [pwos.app](https://pwos.app).
  - The [nexusmcp.site](https://nexusmcp.site) deployment runs the `nexus_core.app` surface from **this** repository — see [`DEPLOY.md`](DEPLOY.md).
- **`pw-portal-v2` / `pw-api` / `pw-infrastructure` / `pw-onchain`** — closed runtime + consumer repos listed on the security page. Not relevant from within this repo. Do not port code from those into here, and vice versa.
