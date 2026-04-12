# Changelog

All notable changes to Nexus Core will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Phase 1: Attribution infrastructure (NOTICE, THIRD_PARTY_LICENSES.md,
  docs/attribution.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, SECURITY.md)
- Phase 2: Directory scaffolding (src/nexus_core/ with 8 modules:
  engine, data, ai, compliance, planning, rebalancing, mcp)
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

## [0.0.1] - 2026-04-12

- Initial public release of docs
