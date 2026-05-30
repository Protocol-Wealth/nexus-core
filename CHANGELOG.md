# Changelog

All notable changes to Nexus Core will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
