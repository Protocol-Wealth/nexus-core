# Nexus Core

> Open source regime-adaptive financial analysis engine with MCP tool orchestration.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

## What This Is

Nexus Core is the open source foundation of the Protocol Wealth research engine — a regime-aware financial analysis system that exposes analytical capabilities as MCP (Model Context Protocol) tools. Any MCP-compatible AI client (Claude, GPT, Gemini) can access regime-aware financial analysis without implementing financial domain logic.

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
├── 8-Check Scoring Framework
│   ├── Durability scoring across 8 dimensions
│   ├── Confidence tiers (High/Moderate/Low/Below Threshold)
│   ├── 7-layer durability model (L1 Foundation → L7 Catalyst)
│   └── Kill rules for automatic disqualification
├── MCP Tool Registry
│   ├── @mcp.tool() decorator pattern
│   ├── 4-tier access (PUBLIC/USER/CLIENT/ADVISOR)
│   └── Transport-layer PII filtering
├── Compliance Gate
│   ├── pending_review → approved workflow
│   └── Immutable audit trail
└── Data Layer (PostgreSQL + Redis)
```

## Key Innovations

**Regime Detection** — Signal ensemble → 5 macroeconomic regimes → asset-specific decay constants (λ) from Langevin dynamics.

**8-Check Scoring** — 8 dimensions: durability, regime fit, momentum, fundamentals, valuation, entropy, Hurst exponent, catalyst.

**7-Layer Model** — L1 Foundation (lowest decay) through L7 Catalyst (highest decay). Lower λ = higher durability.

**MCP Orchestration** — Tools auto-adjust weighting based on detected regime. Any LLM accesses regime-aware analysis without domain logic.

## What's Open vs Private

**Open (Apache 2.0):** Framework, architecture, scoring structure, layer model, tool pattern, compliance gate, caching.

**Private:** Specific thresholds, decay constants, 200+ production tools, API keys, client data, narrative pipeline.

## Tech Stack

Python 3.12 · FastAPI · FastMCP · PostgreSQL · Redis · pandas · numpy · scipy · PyWavelets

## Related

- [pwos-core](https://github.com/Protocol-Wealth/pwos-core) — Compliance-first AI operating system
- [pw-redact](https://github.com/Protocol-Wealth/pw-redact) — PII redaction engine

## License

Apache 2.0 with defensive patent grant. See [LICENSE](LICENSE).

*Built by [Protocol Wealth LLC](https://protocolwealthllc.com) — SEC RIA (CRD #335298)*
