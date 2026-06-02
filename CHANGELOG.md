# Changelog

All notable changes to Nexus Core will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Platform hardening — compliance, security, reliability, MCP, EMF coverage

A broad pass making the public deployment agent-reliable and audit-ready. Test
suite grew 636 → 724; `mypy --strict` + ruff are now CI-enforced (previously
neither ran in CI). Deployed at `nexus-core-00040`.

#### Added

- **Three more planning calculators (engine + REST/MCP tools), planning tools
  13 → 16.** All pure + deterministic in `engine/planning/`, with matching gateway
  tools (JSON `body`, `contractVersion` echo); no contract-version bump (additive
  tool ids, 0.1.0):
  - `fire` — FIRE / Coast-FIRE: the FIRE number (`annualSpend ÷ swr`), the coast
    number needed today (no further contributions compound to the FIRE number by
    the retirement age), projected balance at retirement, and years/age to
    financial independence with level contributions.
  - `risk_metrics` — return-series risk statistics: annualized return / volatility,
    Sharpe, Sortino, maximum drawdown, and historical VaR / CVaR (95%); pure Python,
    no numpy/empyrical dependency.
  - `rebalance` — rebalance-to-target: per-asset drift from target weights and the
    self-financing trade list (with one-way turnover), over the same blended
    portfolio the other portfolio tools use.

  10 engine tests + 6 gateway tests; the native-MCP registration test now asserts
  every planning tool id.
- **Fixed 5 pre-existing `mypy --strict` errors surfaced by the mypy bump in the
  dependency batch** (`tax.py` / `tools.py` `FilingStatus` narrowing via `cast`,
  a seed `int(...)` coercion, and a stale `type: ignore` code in `statements.py`),
  restoring a green `mypy --strict` on `main`.
- **Portfolio X-ray — regime-aware structural diagnostics (engine + REST/MCP tool),
  planning tools 12 → 13.** `engine.planning.portfolio_xray` reads a de-identified
  portfolio (blended weights + per-asset return/vol/λ + account-type mix) and
  returns portfolio metrics (weighted return, weighted-avg vol, concentration via
  Herfindahl + effective holdings, portfolio λ, growth sleeve, account mix) and a
  list of structured findings — concentration, tax-location spread, growth posture,
  and the differentiator: **regime sensitivity conditioned on the LIVE macro
  regime** (a high portfolio λ in an adverse regime is flagged). The
  `portfolio_xray` tool injects the live regime. Pure + deterministic; 5 engine
  tests + 2 gateway tests; no contract-version bump (additive tool id, 0.1.0).
- **Four new planning calculators (engine + REST/MCP tools), planning tools 8 → 12.**
  All pure + deterministic in `engine/planning/`, reusing existing tables, with
  matching gateway tools (a JSON `body`, `contractVersion` echo):
  - **`rmd`** — IRS Uniform Lifetime Table required minimum distribution (reuses
    `tax.rmd_factor`).
  - **`tax_bracket_headroom`** — marginal bracket + ordinary-income room before the
    next federal rate, or up to a target rate ("Roth-fill"); reuses
    `tax.ordinary_brackets` + `standard_deduction` (now public).
  - **`social_security_claiming`** — benefit at each claim age 62–70 from the PIA
    (SSA early-reduction / delayed-credit factors) + breakeven ages.
  - **`regime_conditioned_swr`** — a base safe withdrawal rate adjusted by an
    illustrative per-regime multiplier; the gateway tool injects the LIVE regime.
  - +25 engine tests + 8 gateway tests; `llms.txt` / MCP guide / README updated to
    12 planning tools. No contract-version bump (additive tool ids, `0.1.0`).
- **`roth_conversion` + `sequence_of_returns_stress` are now planning tools.**
  Both engine primitives are exposed as REST tools (`POST /mcp/tools/{id}`) and
  native MCP tools (`/mcp` HTTP + stdio) via the same generic handler registry —
  taking a JSON `body` and echoing `contractVersion`. The two planning-tool count
  goes 6 → 8 (`tools/list`, `/mcp/tools`, the MCP guide, and `llms.txt` updated).
  Gateway tests cover happy-path + a validation case for each.
- **Roth conversion calculator (`engine.planning.roth_conversion`).** Should you
  convert pre-tax dollars to Roth this year? Computes the conversion's *true
  incremental* federal tax by reusing the engine's progressive bracket model
  (`ordinary_tax(income + conversion) − ordinary_tax(income)`), so it captures
  bracket creep instead of assuming a flat marginal rate, then compares the
  after-tax terminal value of converting now vs. leaving the dollars pre-tax and
  taxing them at a retirement marginal rate. Reports `conversionTax`,
  `effectiveConversionRate`, `rothSeed` / `externalTaxPaidToday` (taxes paid from
  the conversion vs. outside funds), the two `*AfterTaxValue`s, `netBenefit`, and
  `breakevenRetirementRate`. Pure + deterministic; documented federal-only
  simplifications; 11 tests, 100% module coverage. Engine primitive — no
  wire-contract change (tool/contract/UI exposure is a follow-up).
- **Sequence-of-returns stress (`engine.planning.sequence_of_returns_stress`).**
  A pure, deterministic complement to the Monte Carlo: hold a fixed multiset of
  annual returns constant and replay the same withdrawal schedule worst-first /
  best-first / as-given. Since the arithmetic mean is identical across orderings,
  the terminal spread (`sequenceRiskGap`) is attributable purely to ordering —
  and with no withdrawals it is provably zero. Reports per-ordering terminal
  balance + depletion year. Within-year mechanic (withdraw at start, grow, floor
  at zero) matches `monte_carlo_decumulation`. 11 tests, 100% module coverage; no
  wire-contract change (engine primitive — tool/contract exposure is a follow-up).
- **Machine-readable AI-disclosure card** (`GET /.well-known/ai-disclosure.json`
  + an `llms.txt` pointer). Conforms to the sibling
  `@protocolwealthos/disclosure-card` open-standard schema (dogfooding pwos-core's
  flagship adoptable standard) and **mirrors Protocol Wealth's published "AI and
  Technology Disclosure"** at <https://protocolwealthllc.com/disclosures/>, which
  the card links to as the authoritative human-readable source: human adviser +
  compliance oversight before any client-facing recommendation, AI never the sole
  basis for advisory decisions / no final investment decisions / no trade
  execution, data minimization, and supervisory records of AI-assisted workflows.
  Values stay accurate to this read-only, model-less, no-client-data service
  (`model.provider: "none"`, zero retention, PII `block`). A test validates the
  card against a vendored copy of the published JSON Schema.
- **Planning tools are now native MCP tools.** The six pwplan-core planning
  tools (`monte_carlo_decumulation`, `glide_path`, `tax_aware_withdrawal`,
  `correlation_matrix`, `capital_market_assumptions`, `regime_return_generator`)
  register in `tools/list` over both the `/mcp` HTTP transport and stdio — not
  only via the REST gateway — reusing the same handlers (contractVersion `0.1.0`).
- **MCP setup guide — Claude Code + worked examples.** `/mcp-guide` now documents
  the Claude Code path (`claude mcp add --transport http` + a shareable
  `.mcp.json`), an "example prompts" section that drives the regime and planning
  tools in plain language, and a worked `monte_carlo_decumulation` request
  showing the load-bearing response fields. The native planning tools take the
  request as a JSON `body` argument (now called out in the guide). +2 guide tests.
- **`examples/planning_agent.py` — reference Claude Agent SDK agent.** A PII-free
  example that wires the Claude Agent SDK to the *hosted* nexus-core MCP server
  and lets Claude orchestrate the planning flow end to end (current regime → real
  capital-market assumptions → Monte Carlo decumulation → tax-aware withdrawal).
  Least-privilege `allowed_tools` (read-only regime + planning tools only),
  headless `permission_mode`, de-identified inputs. The SDK is a demo-only dep
  (lazy-imported), not a nexus-core dependency; the module is import-safe without it.
- **`health` and `describe` MCP tools.** `health` reports per-upstream status
  (market quotes, FRED, Deribit, DefiLlama); `describe` returns the tool catalog
  by category, the symbology rules, and the planning contract version.
- **`get_quotes` batch tool** — up to 25 quotes per call.
- **Read-only tool annotations** (`readOnlyHint`) on every MCP tool, so clients
  can auto-approve calls.
- **Data provenance** — quotes carry `as_of` (the data point's session date),
  `source` (the provider), and `market_status` (`current` / `last_close`); FRED
  responses carry `as_of` (observation date) + `source`. A Friday close pulled
  on a Saturday now reads as `last_close`, not a live price.
- **Regime breadth + precious-metals signals** — `breadth` = % of the 11 SPDR
  sector ETFs above their 200-day MA; `precious_metals_signal` = GLD vs its
  200-day MA (bullish/neutral/bearish). Free, no new API.
- **Agent + discovery files** — `/llms.txt` (llmstxt.org), `AGENTS.md`,
  `/.well-known/security.txt` (RFC 9116), and a `Connecting pwplan-core` section
  in `/mcp-guide`.
- **OpenAPI** `servers` block (hosted base URL) + per-tag descriptions.
- **CI** — `.github/workflows/ci.yml` runs `ruff` + `mypy --strict` + `pytest`
  with an 80% coverage floor on every push/PR.
- **EMF coverage** — ASAN gained five sector buckets (technology_hardware,
  communication, materials, utilities, real_estate); Perez resolves capex-light
  sectors (banks/REITs) from revenue growth; `layer_for` routes crypto
  (BTC→L1, ETH→L2) and sector/commodity ETFs to a durability layer.

#### Changed

- **Canonical disclaimers** — a single `disclaimers.py` (TERSE / MC / FULL +
  Safeguards) wired across every MCP tool, REST route, web page, and the OpenAPI
  description; the prior seven ad-hoc strings now share one auditable text that
  also covers tax / legal / AI-generated-content / as-is.
- **Score tier gating** — `score_asset` returns `NOT APPLICABLE` + a `tier_note`
  when fewer than half the checks evaluate (e.g. ETFs/crypto with no SEC
  fundamentals), instead of a verdict-shaped `BELOW THRESHOLD`.
- **ASAN fail-safe** — an unclassifiable sector is now *not evaluated*
  (`passed=None`) rather than auto-passed (which silently inflated scores, e.g.
  AAPL 6/8 HIGH → a true 5/8 MODERATE).
- `layer_assignment` is hoisted to the top level of a score result.
- `fastmcp` pinned `>=3.0.0,<4`.

#### Fixed

- **`mypy --strict` is green** — fixed 12 pre-existing errors that had drifted
  in undetected (no CI ran mypy before).
- **`defi_protocol`** now returns TVL — derived from `currentChainTvls` with an
  `excludeTotalDataChart` query param that also avoids the multi-MB-payload
  timeout that broke aave/uniswap.
- **FRED resilience** — `get_series` retries on a 429 (rate-limit burst) and
  logs an upstream 4xx (invalid key) at WARNING instead of silent "No data".
- **Option input validation** at the MCP tools — `days<0` / `spot<=0` /
  `strike<=0` / `volatility<0` are rejected (was: silent raw intrinsic), while
  the valid `days=0` / `volatility=0` Black-Scholes limits still work.
- README quick-start used non-existent APIs and linked dead `/opensource`
  `/patent` routes; stale `~594`/`~580` test counts across docs.

#### Security

- **`mask_error_details=True`** on the MCP server — an unexpected tool exception
  can no longer leak `str(e)` (upstream URL/key/path) to the client.
- **Security-headers middleware** — `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy` on every response; a CSP on HTML
  responses only.

### Added — Deribit crypto options coverage: SOL fix + XRP/TRX/AVAX

- **Crypto option underliers expanded to six** — `GET /api/options/crypto/{currency}/instruments`
  now covers **BTC, ETH, SOL, XRP, TRX, AVAX**. Deribit migrated all altcoin
  options to USDC-settled (linear) books listed under a single `USDC` umbrella,
  so `data/derivatives/deribit.py` now queries that umbrella and filters by
  `<CODE>_USDC-…` instrument-name prefix for the linear underliers, while BTC/ETH
  keep their coin-settled (inverse) books. **Fixes** SOL silently returning zero
  instruments (it had been queried as `currency=SOL`, which Deribit now answers
  with an empty book). Keyless — no new secret.
- **`GET /api/options/crypto/currencies`** — new discovery endpoint listing the
  supported underliers and each one's settlement model (`inverse` / `linear_usdc`).
- `DeribitClient.supported_currencies()` / `settlement_model()` are now the single
  source of truth for the REST routes and the `crypto_option_instruments` MCP tool
  (no more hard-coded currency triples).

### Added — Multi-chain LP, Aerodrome Slipstream, position vs-benchmark, and Solana SPL prices

- **Aerodrome Slipstream LP analytics (Base, on-chain RPC)** —
  `GET /api/lp/aerodrome/{token_id}/analytics`. Slipstream is a Uniswap-V3 CLMM
  sibling, so the pure `engine/lp/uniswap_v3.py` math drives it unchanged. No
  canonical Slipstream subgraph exists on The Graph, so position state is read
  directly on-chain via Tatum RPC (`data/onchain/slipstream.py`): NFPM
  `positions` → CLFactory `getPool` → CLPool `slot0` → token `decimals`/`symbol`.
  Reports position value, in-range status, token amounts, and uncollected fees
  (decoded `tokensOwed`). Impermanent loss (needs deposit history), fee APR
  (needs pool volume), and AERO gauge reward APR are **not** available in
  on-chain-only mode and are reported as null/zero (`data_mode: onchain_rpc`).
  Envio indexing for full coverage (IL + fee APR + gauge APR) is a documented
  follow-on.
- **Multi-chain Uniswap V3 LP analytics** — `GET /api/lp/uniswap-v3/{chain}/{token_id}/analytics`
  now spans **ethereum, base, optimism, polygon**. The CLMM math in
  `engine/lp/uniswap_v3.py` is pure and protocol-agnostic, so the same engine
  drives every chain (per-chain config in `data/onchain/thegraph.py`). USD
  prices remain required query params; returns position value, in-range flag,
  exact IL-vs-HODL, fee-APR estimate, uncollected fees (Tatum `tokensOwed`),
  and Merkl reward APR → total APR. Arbitrum is **not** supported — its
  published subgraph ID uses an incompatible schema.
- **Position vs-benchmark** — `GET /api/lp/uniswap-v3/{chain}/{token_id}/vs-benchmark`
  compares a live LP position against hold-strategy benchmark returns over a
  window, reusing `engine/benchmarks.py`. Same required USD-price params as the
  analytics endpoint.
- **Solana SPL token USD prices** — `data/onchain/jupiter.py` (Jupiter v3,
  keyless) backing `GET /api/solana/price/{mint}` and
  `GET /api/solana/prices?mints=`. No API key required; degrades gracefully when
  the upstream is unavailable.

### Added — On-chain data, LP analytics, benchmarks, and a private market-data store (2026-05-19 → 2026-05-28)

- **Multi-chain native balances** — `data/onchain/tatum.py` (Tatum) backing
  `GET /api/chain/chains`, `GET /api/chain/balance/{chain}/{address}` (EVM
  `eth_getBalance` + Solana `getBalance`), and `GET /api/chain/native/{address}`.
  Requires `TATUM_API_KEY`; degrades to empty/None when absent.
- **Anonymous EVM wallet balance** — `data/onchain/debank.py` (DeBank) backing
  `GET /api/wallet/{address}`. No client data, no auth. Requires `DEBANK_API_KEY`.
- **DeFi vault discovery** — `data/onchain/vaultsfyi.py` (vaults.fyi v2) backing
  `GET /api/vaults` and `GET /api/vaults/chains`. Response parsing reads
  `apy` / `chain` / `vaultId`. Requires `VAULTSFYI_API_KEY`.
- **Uniswap V3 LP position analytics** — `engine/lp/uniswap_v3.py` pure CLMM
  math (tick math, `get_amounts_for_liquidity`, exact impermanent-loss-vs-HODL,
  fee-APR estimate) plus `data/onchain/{thegraph,merkl}.py` backing
  `GET /api/lp/chains` and
  `GET /api/lp/uniswap-v3/{chain}/{token_id}/analytics`. Returns position
  value, in-range flag, exact IL-vs-HODL, fee-APR, uncollected fees
  (RPC `tokensOwed` via Tatum), and Merkl reward APR → total APR. USD prices
  are required query params. Sources: The Graph + RPC + Merkl;
  requires `THEGRAPH_API_KEY` (and `TATUM_API_KEY` for uncollected fees).
- **Hold-strategy benchmarks** — `engine/benchmarks.py` (base-100, buy-and-hold)
  backing `GET /api/benchmarks`, `GET /api/benchmarks/series?days=` (on-demand
  from CoinGecko), and `GET /api/benchmarks/history?days=` (from persisted daily
  snapshots). Compositions: BTC/ETH/SOL, ETH-USDC 50/50·60/40·70/30,
  ETH-BTC 50/50; USDC held at $1.
- **Private market-data persistence** — `data/db.py` + `data/snapshots.py`
  (asyncpg) against a private-IP-only Cloud SQL instance (`nexus-marketdata`,
  POSTGRES_16) reached via Direct VPC egress. `GET /health/db` probes
  connectivity. `DATABASE_URL` gates persistence and
  `/api/benchmarks/history` (503 when unset).
- **Daily snapshot Cloud Run Job** — `jobs/daily_snapshot.py`, invoked via the
  `nexus-core snapshot` CLI command, run by a Cloud Run Job
  (`nexus-snapshot-job`) on an OAuth service-account identity, triggered by
  Cloud Scheduler (`nexus-daily-snapshot`, daily 01:00 America/New_York).
  No shared secret; no public write route.
- **Educational options overlays + crypto options** — Black-Scholes overlays at
  `GET /api/options/price` and `GET /api/options/overlay/{covered-call,cash-secured-put,collar}`,
  plus Deribit crypto options at `GET /api/options/crypto/{currency}/instruments`
  and `GET /api/options/crypto/instrument/{instrument_name}` (`data/derivatives`).

### Changed — Snapshot write path moved off the public surface (2026-05-19)

- The daily snapshot is now a Cloud Run Job (`nexus-core snapshot`), not an
  HTTP route. The public write endpoint was dropped; the public surface remains
  read-only.

### Fixed — Spoofing-resistant rate limiting (2026-05-28)

- The in-process rate limiter now resolves the client IP spoofing-resistantly:
  prefers `CF-Connecting-IP`, else the rightmost `X-Forwarded-For` entry.
  Layered behind a Cloudflare methods rule (blocks non-GET/POST/OPTIONS) and an
  edge rate-limit on cost endpoints. `NEXUS_RATE_LIMIT_PER_MIN` defaults to 60.

### Added — Tier-2: score explainability + deterministic replay + cross-link doc (2026-05-27)

- **`src/nexus_core/engine/scoring/explanation.py`** — new module exposing
  `ScoreExplanation`, `CheckExplanation`, `SignalContribution`, and
  `build_score_explanation()`. The explanation is *sanitized by
  construction*: `SignalContribution` carries only `(name, status,
  supports_regime)` — NO `current_value`, NO `threshold_info`, NO numeric
  cutoff. Downstream consumers can render an explanation surface without
  leaking the operator's production threshold values.
- **`src/nexus_core/engine/scoring/framework.py`** — `ScoreResult` gained
  `as_of: date | None = None` and `explanation: ScoreExplanation | None =
  None` (both default `None` for backward compat).
  `ScoringFramework.score(ctx, *, subject=None, as_of=None)` — new
  `as_of` keyword param; the score auto-populates the `explanation` and
  echoes `as_of` onto the result. `to_dict()` serializes both new fields.
- **`src/nexus_core/engine/regime/signals.py`** — `RegimeResult` gained
  `as_of: date | None = None`; `to_dict()` emits ISO date when set.
- **`src/nexus_core/engine/regime/classifier.py`** —
  `RegimeClassifier.classify(..., as_of=None)` accepts and echoes
  `as_of`. The classifier is unchanged on the classification logic
  itself — `as_of` is metadata for reproducible replay.
- **`src/nexus_core/engine/regime/engine.py`** —
  `RegimeEngine.fetch_signals(*, force_refresh=False, as_of=None)` and
  `RegimeEngine.classify(signals=None, *, prediction_market=None,
  as_of=None)`. When `as_of` is set, `fetch_signals` bypasses the cache
  and forwards to `SignalFetcher.fetch(as_of=...)` if supported (TypeError
  fallback to plain `.fetch()` for providers without `as_of` support).
- **`tests/test_explanation.py`** — N2 tests. Includes
  `test_signal_contributions_strip_threshold_and_raw_value` which asserts
  serialized contributions have ONLY the three sanitized keys (name /
  status / supports_regime); other tests exercise the per-check
  partitioning, the dict-or-object regime input shape, the framework
  integration path, and the `to_dict()` round-trip.
- **`tests/test_replay.py`** — N3 tests. Same-`as_of` same-result identity
  asserted for the classifier + the scoring framework (including the
  `ScoreExplanation`'s `to_dict()`).
- **`examples/deterministic_replay.py`** — runnable worked example with
  synthetic signals; zero data dependencies. Asserts byte-identical JSON
  serialization across two calls with the same `as_of`.
- **`docs/CROSS-LINK-PWOS-CORE.md`** — N4 conceptual note: three join
  points between this repo's outputs and `pwos-core`'s disclosure-card
  + provenance + HITL primitives.
- **`HANDOFF.md`** — extended with Tier-2 wiring contract; cross-references
  `pwos-core/HANDOFF.md` for the authoritative wiring instructions.
- Public-surface compatibility preserved: new fields default to `None`;
  `to_dict()` shape is additive; no symbol renamed or removed; no regime
  taxonomy change; no new threshold value added or modified. Apache-2.0 +
  USPTO #64/034,229 + OIN posture unchanged.

### Changed — Cross-repo governance parity with `pwos-core` (2026-05-27)

- **No new governance files needed in this repo.** `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, and `CHANGELOG.md` already match the canonical PW open-source shape and were the source-of-truth pattern that `pwos-core`'s parallel hardening copied from. This entry records the cross-repo work for the audit trail; no file in this repo was modified except this CHANGELOG.
- **`pwos-core` side (sibling repo)** of the same iteration: CONTRIBUTING rewritten to remove fictional commands and list all 18 published packages; SECURITY scope tightened to pwos-core primitives; CODE_OF_CONDUCT project-name typo fixed; README gained a *What's Open vs Private* section mirroring this repo's, plus a rewrite of the "LLM autonomously selects and executes tools" line to surface the human-in-the-loop boundary between advisor IDE chat and client-facing writes.

### Changed — Public-repo honesty disclaimer + claim reconciliation (2026-05-14)

- **`README.md`** — added `## Status` block before `## What This Is`: this is a reference framework and starting point, not a production-ready product; adopters are responsible for adding their own PII controls, access control, input validation, authentication, and data-handling boundaries; the framework makes no AI-provider data-retention guarantees.
- **`README.md`** — Architecture diagram: replaced the unsubstantiated "Multi-tier access control" and "Transport-layer PII filtering" lines under MCP Tool Registry with an honest "Pluggable ResponseFilter hooks (adopter-supplied auth / PII / audit)" line that matches the actual code in `src/nexus_core/mcp/server/app.py`.
- **`docs/ARCHITECTURE.md`** — rewrote the "MCP Tool Pattern" section: the prior code example referenced a `check_tier(...)` function that does not exist in the codebase; replaced with the real `ResponseFilter` hook pattern. Replaced the "Tiered Access" table (PUBLIC / USER / CLIENT / ADVISOR scoring scopes claimed as built-in) with an "Access Control and Tiering (Adopter-Supplied)" section that states plainly the framework does not enforce access tiers and the scaffold treats all callers as trusted.
- No code change. Reconciles a public-repo audit finding flagging README + ARCHITECTURE EXISTS-tense capability claims for access control and PII filtering that the code did not back. Apache-2.0 + USPTO #64/034,229 defensive-licensing posture unchanged.

### Added — v0.3.0: Financials + Optimization absorption

- **`nexus_core.financials`** — new package, license-clean Apache 2.0:
  - `statements.py` — Pydantic models for `IncomeStatement`,
    `BalanceSheet`, `CashFlowStatement`, `StatisticsStatement`,
    `StatementBundle` (canonical envelope), with `Period` enum.
  - `ratios.py` — five families of ratios as pure functions:
    `liquidity`, `solvency`, `efficiency`, `profitability`,
    `valuation`. Returns typed `RatioPanel` subclasses.
  - `models.py` — DCF (perpetuity-growth), CAPM, WACC, DuPont
    (3-step + 5-step), Altman Z-Score (manufacturing variant) with
    distress-zone classification.
  - `performance.py` — Sharpe, Treynor, Information Ratio, Jensen
    alpha + beta, all annualized; `all_performance` composes.
  - `risk.py` — VaR family (historical / Gaussian / Cornish-Fisher),
    CVaR, downside volatility, max drawdown.
  - `adapter.py` — `from_finance_toolkit(toolkit)` reads a fetched
    `financetoolkit.Toolkit` instance and produces a
    `StatementBundle`. Optional `[financials]` extra unlocks the
    bridge; everything else works without it.
- **`nexus_core.engine.optimization`** expansion — twelve entry points:
  - PyPortfolioOpt-backed (existing): `optimize`, `optimize_for_regime`,
    `max_sharpe`, `min_volatility`, `target_return`, `target_risk`, `hrp`.
  - Riskfolio-Lib-backed (new): `risk_parity` (24+ risk measures),
    `hierarchical_risk_parity` (richer than PyPortfolioOpt's HRPOpt),
    `min_cvar`.
  - Black-Litterman (new): immutable `View` value object with
    `absolute_view` / `relative_view` builders, plus
    `black_litterman_posterior` to feed any optimizer's `mu` input.
  - Discrete allocation (new): `discrete_allocate` with `lp` /
    `greedy` methods, returns `DiscreteAllocationResult` with
    integer shares + leftover cash.
- **`pyproject.toml`** — new `[financials]` extra (`financetoolkit>=2.0.0`).
- **Tests:** 33 new (26 financials + 7 optimization shapes).
  `pytest tests/` reports 90 passed.
- **Attribution:** FinanceToolkit (MIT), PyPortfolioOpt (MIT),
  Riskfolio-Lib (BSD-3) added/updated in `NOTICE` and
  `docs/attribution.md`.

### Added — Phase 3a (regime + scoring engines)
- `nexus_core.engine.regime` — Multi-signal regime classification:
  - `RegimeCode` / `ClientType` / `SignalDirection` enums
  - `RegimeThresholds` / `ForcedLiquidationThresholds` (configurable)
  - `RegimeSignals` / `SignalStatus` / `RegimeResult` dataclasses
  - `HysteresisState` — generic asymmetric enter/exit state machine
  - `RegimeClassifier` — pure `signals → result` function
  - `SignalFetcher` — provider-backed signal fetching with fallbacks
  - `RegimeEngine` — orchestrator with caching and regime tracking
  - Forced-liquidation dampener: VIX spike, breadth collapse, correlation
    spike, volume spike detection + `evaluate_dampener()` aggregator
- `nexus_core.engine.scoring` — N-check scoring framework:
  - `Check` protocol, `CheckResult` dataclass, `ScoringContext`
  - `ScoringFramework` orchestrator
  - `ConfidenceTier` enum with `classify_tier()` helper
  - `CHECK_METADATA` — academic source attribution for standard 8 checks
  - Enhancements: `consistency_enhancement`, `base_rate_enhancement`,
    `adversarial_brief_enhancement`
  - Formatters: `format_public`, `format_advisor`, `format_structured`
- `nexus_core.mcp.server` — FastMCP server scaffold with regime + scoring tools
- `nexus_core.data.providers` — `MarketDataProvider` / `MacroDataProvider`
  protocols
- Third-party wrappers:
  - `nexus_core.engine.optimization.pypfopt_wrapper` — PyPortfolioOpt with
    regime-aware method selection (MIT)
  - `nexus_core.data.edgar.edgartools_wrapper` — structured SEC filing access (MIT)
  - `nexus_core.ai.sentiment.finbert_wrapper` — FinBERT sentiment with
    optional PII redaction hook (Apache 2.0)
- Tests: 57 unit tests covering thresholds, hysteresis, dampener, classifier,
  engine, and scoring (all green)
- Examples: `basic_regime.py`, `basic_scoring.py`, `mcp_server.py`

### Added — Phase 1+2 (scaffolding)
- Attribution infrastructure (NOTICE, THIRD_PARTY_LICENSES.md,
  docs/attribution.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md)
- Directory scaffolding (src/nexus_core/ with 8 modules)
- pyproject.toml with optional dependency groups:
  - optimization (PyPortfolioOpt, Riskfolio-Lib, skfolio)
  - risk (empyrical-reloaded, pyfolio-reloaded, ffn)
  - pricing (QuantLib, FinancePy)
  - edgar (edgartools, Arelle, sec-parser)
  - market (yfinance)
  - ai (FinBERT, FinRobot, FinRL — heavy)
  - backtest (zipline-reloaded, alphalens)
  - compliance (Moov Watchman client)
  - onchain (Ethereum-ETL, web3)
  - planning (Monte Carlo retirement)
- License compliance CI workflow (forbids GPL/AGPL/SSPL)

### Changed
- Expanded README to include "Built on the shoulders of giants" attribution
- License: Apache 2.0 with defensive patent grant
- `pyproject.toml` ruff config: ignore PLR (complexity) and UP042 —
  domain logic is inherently branchy and `str + Enum` supports 3.12+

## [0.0.1] - 2026-04-12

- Initial public release of docs
