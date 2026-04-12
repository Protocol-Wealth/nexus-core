# Changelog

All notable changes to Nexus Core will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
