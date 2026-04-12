# Nexus Core

> Open source regime-adaptive financial analysis engine with MCP tool orchestration.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Patent Pending](https://img.shields.io/badge/Patent-Pending-orange.svg)](https://patentcenter.uspto.gov/applications/64034229)
[![OIN Member](https://img.shields.io/badge/OIN-Member-green.svg)](https://openinventionnetwork.com)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)

**Live:** [nexusmcp.site](https://nexusmcp.site) | **Open Source:** [nexusmcp.site/opensource](https://nexusmcp.site/opensource) | **Patent:** [nexusmcp.site/patent](https://nexusmcp.site/patent)

## What This Is

Nexus Core is the open source foundation of the [Protocol Wealth research engine](https://nexusmcp.site) — a regime-aware financial analysis system that exposes analytical capabilities as MCP (Model Context Protocol) tools. Any MCP-compatible AI client (Claude, GPT, Gemini) can access regime-aware financial analysis without implementing financial domain logic.

Built and tested in production by an SEC-registered RIA (Protocol Wealth LLC, CRD #335298).

## Architecture

```
MCP Client (Claude, GPT, Gemini)
    │ JSON-RPC over HTTP
    ▼
Nexus Core (FastAPI + FastMCP)
├── Regime Detection Engine
│   ├── Signal ensemble (yield curve, VIX, DXY, CPI, energy)
│   ├── 5 regime states (Growth, Transition, Hard Asset, Deflation, Repression)
│   ├── Langevin decay constants (λ) per asset class
│   └── 6 voting signals with cross-validation
├── Scoring Framework
│   ├── Multi-dimensional durability scoring
│   ├── Confidence tiers
│   ├── Layered durability model
│   └── Kill rules for automatic disqualification
├── Portfolio Optimization (PyPortfolioOpt + Riskfolio-Lib)
│   ├── MVO, Black-Litterman, HRP, discrete allocation
│   ├── 24 convex risk measures, factor models
│   └── Walk-forward cross-validation (skfolio)
├── Risk Analytics (empyrical-reloaded + pyfolio-reloaded)
│   ├── Sharpe, Sortino, alpha, beta, VaR, max drawdown
│   └── Professional tear sheets
├── Derivatives Pricing (QuantLib + FinancePy)
│   ├── Yield curves, bond analytics, swaps
│   └── Equity options, FX, credit instruments
├── SEC EDGAR Integration (edgartools + Arelle)
│   ├── Filings as Python objects with native XBRL
│   └── SEC-certified XBRL validation
├── AI/ML Finance (FinGPT + FinRobot + FinBERT)
│   ├── Multi-agent equity research from 10-Ks
│   └── Financial sentiment classification
├── Compliance (Moov Watchman)
│   └── OFAC sanctions screening via HTTP API
├── MCP Tool Registry
│   ├── @mcp.tool() decorator pattern
│   ├── Multi-tier access control
│   └── Transport-layer PII filtering
└── Data Layer (PostgreSQL + Redis)
```

## Key Innovations

**Regime Detection** — Signal ensemble maps macroeconomic conditions to regime states, informing asset-specific analysis.

**Scoring Framework** — Multi-dimensional assessment combining fundamentals, technicals, momentum, and regime alignment.

**Layered Durability Model** — Assets classified by decay characteristics. Lower decay = higher durability under stress.

**MCP Orchestration** — Tools auto-adjust analysis based on detected regime. Any LLM accesses regime-aware insights without domain logic.

## Built on the Shoulders of Giants

Nexus Core stands on a foundation of exceptional open-source projects. We bundle or extend these libraries with full attribution — see [NOTICE](NOTICE) and [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) for complete legal notices.

### Portfolio Optimization & Risk Analytics
- **[PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt)** (MIT) — Mean-variance, Black-Litterman, HRP
- **[Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib)** (BSD-3) — 24 convex risk measures, factor models
- **[empyrical-reloaded](https://github.com/stefan-jansen/empyrical-reloaded)** (Apache 2.0) — Performance metrics (Sharpe, Sortino, VaR)
- **[pyfolio-reloaded](https://github.com/stefan-jansen/pyfolio-reloaded)** (Apache 2.0) — Professional tear sheets
- **[skfolio](https://github.com/skfolio/skfolio)** (BSD-3) — scikit-learn portfolio optimization
- **[ffn](https://github.com/pmorissette/ffn)** (MIT) — Pandas financial functions

### Derivatives Pricing & Fixed Income
- **[QuantLib](https://github.com/lballabio/QuantLib)** (Modified BSD) — Derivative pricing, yield curves
- **[FinancePy](https://github.com/domokane/FinancePy)** (MIT) — Numba JIT pricing for bonds/swaps/options

### SEC EDGAR & Financial Data
- **[edgartools](https://github.com/dgunning/edgartools)** (MIT) — SEC filings as Python objects + built-in MCP server
- **[Arelle](https://github.com/Arelle/Arelle)** (Apache 2.0) — SEC-certified XBRL validation
- **[sec-parser](https://github.com/alphanome-ai/sec-parser)** (MIT) — Semantic parsing for LLM pipelines
- **[sec-edgar-downloader](https://github.com/jadchaar/sec-edgar-downloader)** (MIT) — Bulk filing downloads
- **[edgar-crawler](https://github.com/lefterisloukas/edgar-crawler)** (MIT) — Filing section extraction
- **[yfinance](https://github.com/ranaroussi/yfinance)** (Apache 2.0) — Market data

### Backtesting & Factor Analysis
- **[zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded)** (Apache 2.0) — Event-driven backtesting
- **[alphalens](https://github.com/quantopian/alphalens)** (Apache 2.0) — Factor performance analysis

### AI & ML for Finance
- **[FinGPT](https://github.com/AI4Finance-Foundation/FinGPT)** (MIT) — Financial LLM framework with RAG
- **[FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)** (Apache 2.0) — Multi-agent equity research
- **[FinRL](https://github.com/AI4Finance-Foundation/FinRL)** (MIT) — Reinforcement learning for portfolios
- **[FinBERT](https://github.com/ProsusAI/finBERT)** (Apache 2.0) — Financial sentiment classification

### Compliance & Blockchain
- **[Moov Watchman](https://github.com/moov-io/watchman)** (Apache 2.0) — OFAC sanctions screening
- **[Ethereum-ETL](https://github.com/blockchain-etl/ethereum-etl)** (MIT) — Blockchain data pipeline

### Reference Architecture (patterns only — AGPL code NOT copied)
- **[OpenBB Platform](https://github.com/OpenBB-finance/OpenBB)** (AGPL-3.0) — Data aggregation architecture
- **[SEC EDGAR Toolkit](https://github.com/stefanoamorelli/sec-edgar-toolkit)** (AGPL-3.0) — TS+Python monorepo pattern

**Huge thanks to every maintainer and contributor of these projects.** Financial software has historically been locked behind proprietary walls — Nexus Core would not exist without the open-source financial ecosystem.

## What's Open vs Private

**Open (Apache 2.0):** Framework architecture, scoring structure, layer model, tool pattern, compliance gate, caching patterns. All third-party integrations listed above.

**Private:** Specific thresholds, decay constants, production tools, API keys, client data, narrative pipeline.

## Installation

### Full install (all capabilities)

```bash
pip install nexus-core[all]
```

### Modular installs (reduce dep footprint)

```bash
pip install nexus-core                    # Core only (regime, scoring)
pip install nexus-core[optimization]      # + PyPortfolioOpt, Riskfolio, skfolio
pip install nexus-core[risk]              # + empyrical, pyfolio
pip install nexus-core[pricing]           # + QuantLib, FinancePy
pip install nexus-core[edgar]             # + edgartools, Arelle, sec-parser
pip install nexus-core[ai]                # + FinGPT, FinBERT, FinRobot (heavy)
pip install nexus-core[backtest]          # + zipline-reloaded, alphalens
pip install nexus-core[compliance]        # + Moov Watchman client
pip install nexus-core[onchain]           # + Ethereum-ETL, DefiLlama integration
```

### From source

```bash
git clone https://github.com/Protocol-Wealth/nexus-core.git
cd nexus-core
pip install -e ".[all]"
```

## Quick Start

```python
from nexus_core import RegimeEngine, ScoringEngine

engine = RegimeEngine()
regime = engine.detect_current_regime()
print(f"Current regime: {regime.name} (confidence: {regime.confidence:.1%})")

scoring = ScoringEngine(regime=regime)
score = scoring.score_ticker("AAPL")
print(f"AAPL: {score.tier} ({score.total}/8)")
```

### As an MCP server

```bash
# Run as an MCP server (any MCP-compatible AI client can connect)
nexus-core mcp serve --port 3333
```

## Tech Stack

Python 3.12 · FastAPI · FastMCP · PostgreSQL · Redis · pandas · numpy · scipy · PyWavelets

## Documentation

- [Architecture](docs/architecture.md)
- [MCP Tools Reference](docs/mcp-tools.md)
- [Attribution](docs/attribution.md) — detailed provenance per capability
- [Contributing](CONTRIBUTING.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [Security](SECURITY.md)

## Patent & IP

**Patent Pending** — USPTO Application #64/034,229
"Compliance-First Quantitative Research Engine with Multi-Signal Regime Detection, Systematic Asset Scoring, and AI Tool Orchestration via Model Context Protocol for SEC/FINRA-Regulated Financial Advisory Services"

- [USPTO Patent Center](https://patentcenter.uspto.gov/applications/64034229)
- Applicant: Protocol Wealth, LLC
- Inventor: Nicholas Rygiel
- Filed: April 9, 2026
- Status: Patent Pending

This patent was filed **defensively** under Apache 2.0. The intent is to establish formal prior art and prevent third parties from patenting these concepts and restricting their use by independent financial advisors. Under Apache 2.0, you receive an automatic, perpetual, royalty-free patent grant. If you sue Protocol Wealth for patent infringement related to this software, your license terminates automatically.

**Open Invention Network (OIN) Member** — Protocol Wealth is a member of the OIN 2.0 community, the world's largest patent non-aggression network with 4,100+ members including Google, IBM, Toyota, Meta, Microsoft, and Amazon. [Learn more](https://openinventionnetwork.com/about-us/member-benefits/)

See [PATENTS](PATENTS) for full non-assertion pledge.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

Apache 2.0 includes an explicit patent retaliation clause that MIT lacks. If someone sues you for patent infringement related to Nexus, their right to use the software terminates automatically.

**Third-party components retain their original licenses.** See [NOTICE](NOTICE) and [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

## Contributing

We welcome contributions. All commits must include a `Signed-off-by:` line certifying agreement with the [Developer Certificate of Origin](https://developercertificate.org/):

```bash
git commit -s -m "feat: your change"
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines.

## Related

- **[PWOS Core](https://github.com/Protocol-Wealth/pwos-core)** — Compliance-first AI operating system ([pwos.app](https://pwos.app))

## Links

- **Live App:** [nexusmcp.site](https://nexusmcp.site)
- [Open Source Manifesto](https://nexusmcp.site/opensource)
- [Patent Documentation](https://nexusmcp.site/patent)
- [Protocol Wealth](https://protocolwealthllc.com)

---

*Built by [Protocol Wealth LLC](https://protocolwealthllc.com) — SEC-Registered Investment Adviser (CRD #335298)*
