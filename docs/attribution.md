# Attribution & Provenance

This document provides detailed provenance for every capability in Nexus Core. When an idea, algorithm, or code pattern came from a third-party project, we credit it here.

---

## Capability Provenance Map

### Regime Detection Engine

**Our original work.** The multi-signal regime detection with Langevin decay constants per asset class and 6-signal voting ensemble is Protocol Wealth original research. See [USPTO Application #64/034,229](https://patentcenter.uspto.gov/applications/64034229).

**Related inspiration:**
- Yield curve and credit spread signals — widely documented in academic literature (Estrella/Mishkin, Bauer/Mertens)
- VIX regime classification — adapted from CBOE methodology
- DXY signal — FRED DTWEXBGS (Trade Weighted U.S. Dollar Index)

### Scoring Framework

**Our original work.** The 8-check durability scoring with confidence tiers, layered model, and kill rules is Protocol Wealth original research.

**Related inspiration:**
- F-Score methodology — Joseph Piotroski, "Value Investing: The Use of Historical Financial Statement Information" (2000)
- Quality factor scoring — Asness, Frazzini, Pedersen, "Quality Minus Junk" (2019)
- Moat analysis — adapted from Pat Dorsey, "The Little Book That Builds Wealth"

### Portfolio Optimization Module

**Fully attributed to:**
- **[PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt)** by Robert Andrew Martin (MIT)
  - Mean-variance optimization
  - Black-Litterman allocation
  - Hierarchical Risk Parity
  - Ledoit-Wolf shrinkage
  - Discrete allocation

- **[Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib)** by Dany Cajas (BSD-3)
  - 24 convex risk measures
  - Factor models
  - Turnover and tracking error constraints
  - Kelly Criterion
  - Multiple Black-Litterman variants

- **[skfolio](https://github.com/skfolio/skfolio)** (BSD-3)
  - sklearn-compatible API
  - Walk-forward cross-validation
  - Pipeline integration

**Our original work:** The MCP tool wrappers, regime-aware parameter selection, and integration with our scoring framework.

### Risk Analytics Module

**Fully attributed to:**
- **[empyrical-reloaded](https://github.com/stefan-jansen/empyrical-reloaded)** by Stefan Jansen (Apache 2.0)
  - Sharpe, Sortino, information ratio
  - Alpha, beta, rolling calculations
  - Max drawdown, VaR, CVaR
  - Capture ratios

- **[pyfolio-reloaded](https://github.com/stefan-jansen/pyfolio-reloaded)** by Stefan Jansen (Apache 2.0)
  - Professional tear sheets
  - Bayesian performance analysis
  - Transaction cost attribution

**Our original work:** Regime-conditional performance metrics, client-facing reporting templates.

### Derivatives Pricing Module

**Fully attributed to:**
- **[QuantLib](https://github.com/lballabio/QuantLib)** (Modified BSD)
  - Yield curve construction
  - Bond analytics
  - Swap pricing
  - Derivative pricing

- **[FinancePy](https://github.com/domokane/FinancePy)** by Dominic O'Kane (MIT)
  - Numba JIT-compiled pricing
  - Equity options, FX, credit instruments

**Our original work:** Integration layer, MCP tool exposure.

### SEC EDGAR Integration

**Fully attributed to:**
- **[edgartools](https://github.com/dgunning/edgartools)** by Dwight Gunning (MIT)
  - Filings as Python objects
  - Native XBRL parsing
  - Built-in MCP server
  - Accepted into Anthropic's Claude for Open Source program

- **[Arelle](https://github.com/Arelle/Arelle)** by Mark V Systems (Apache 2.0)
  - XBRL International-certified validator
  - PostgreSQL xbrlDB plugin

- **[sec-parser](https://github.com/alphanome-ai/sec-parser)** by Alphanome AI (MIT)
  - Semantic parsing of EDGAR HTML

**Reference architecture (no code copied):**
- **[OpenBB Platform](https://github.com/OpenBB-finance/OpenBB)** (AGPL-3.0) — data aggregation patterns

**Our original work:** Workflow integration with scoring engine, tax-aware SEC data pipeline.

### AI/ML Finance Module

**Fully attributed to AI4Finance Foundation:**
- **[FinGPT](https://github.com/AI4Finance-Foundation/FinGPT)** (MIT) — Financial LLM framework
- **[FinRobot](https://github.com/AI4Finance-Foundation/FinRobot)** (Apache 2.0) — Multi-agent research
- **[FinRL](https://github.com/AI4Finance-Foundation/FinRL)** (MIT) — RL for portfolios

**Fully attributed to Prosus AI:**
- **[FinBERT](https://github.com/ProsusAI/finBERT)** (Apache 2.0) — Financial sentiment

**Our original work:** Privacy-preserving wrappers, PII-redacted prompt flows, compliance-gated outputs.

### Compliance Module

**Fully attributed to Moov Financial:**
- **[Moov Watchman](https://github.com/moov-io/watchman)** (Apache 2.0) — OFAC SDN + sanctions screening HTTP API

**Our original work:** Integration with client onboarding workflow, audit trail emission.

### Backtesting & Factor Analysis

**Fully attributed to Stefan Jansen / Quantopian:**
- **[zipline-reloaded](https://github.com/stefan-jansen/zipline-reloaded)** (Apache 2.0)
- **[alphalens](https://github.com/quantopian/alphalens)** (Apache 2.0)

**Our original work:** Regime-conditional backtest framework, bucket analysis for scoring validation.

### Planning & Retirement Simulation

**Fully attributed to:**
- **[WenFire](https://github.com/basnijholt/wenfire)** by Bas Nijholt (MIT) — FastAPI FIRE calculator template

**Reference architecture (patterns only):**
- **[Ignidash](https://github.com/schelskedevco/ignidash)** — Monte Carlo + AI chat UX patterns
- **[cFIREsim-open](https://github.com/boknows/cFIREsim-open)** — Exhaustive historical backtesting algorithm

**Our original work:** Tax-aware scenario optimization, regime-conditional withdrawal strategies.

### Blockchain & Onchain

**Fully attributed to:**
- **[Ethereum-ETL](https://github.com/blockchain-etl/ethereum-etl)** by Evgeny Medvedev (MIT)
  - Blockchain data extraction and loading
  - PostgreSQL/BigQuery/Kafka sinks

**Reference architecture (AGPL code NOT copied):**
- **[DefiLlama Adapters](https://github.com/DefiLlama/DefiLlama-Adapters)** (GPL-3.0)
  - Protocol TVL calculation reference
  - We link/call their public API; do not redistribute their code

- **[Rotki](https://github.com/rotki/rotki)** (AGPL-3.0)
  - Self-hosted portfolio tracking architecture

**Our original work:** Multi-chain aggregation, DeFi position cost basis, tax-lot tracking.

---

## How to Add New Attributions

When integrating new third-party code or ideas:

1. **Determine license compatibility** — run `pip-licenses --format=markdown` or check the project's LICENSE file
   - ✅ Safe to bundle: MIT, Apache 2.0, BSD (2/3-clause), MPL 2.0, ISC
   - ⚠️ Dynamic link only: LGPL
   - ❌ Reference architecture only: GPL-3.0, AGPL-3.0, SSPL

2. **Update NOTICE** — add copyright and license notice

3. **Update THIRD_PARTY_LICENSES.md** — add full license text (unless already present for that license type)

4. **Update README.md "Built on" section** — add human-readable attribution

5. **Update this file (docs/attribution.md)** — add detailed provenance

6. **Update pyproject.toml** — pin the dependency with `^` or `~` constraint

---

## Attribution Audit

We run an automated license compliance check in CI on every PR:

```yaml
# .github/workflows/license-compliance.yml
- run: pip install pip-licenses
- run: pip-licenses --format=json --output-file=licenses.json
- run: python scripts/check_licenses.py licenses.json
```

The script fails the build if any dependency has a GPL/AGPL/SSPL license not present in our approved reference-only list.

---

## Questions?

If you believe we've missed an attribution or misidentified a license, please open an issue. We take attribution seriously.
