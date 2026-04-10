# Nexus Core

> Open source regime-adaptive financial analysis engine with MCP tool orchestration.

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Patent Pending](https://img.shields.io/badge/Patent-Pending-orange.svg)](https://patentcenter.uspto.gov/applications/64034229)
[![OIN Member](https://img.shields.io/badge/OIN-Member-green.svg)](https://openinventionnetwork.com)

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
├── MCP Tool Registry
│   ├── @mcp.tool() decorator pattern
│   ├── Multi-tier access control
│   └── Transport-layer PII filtering
├── Compliance Gate
│   ├── pending_review → approved workflow
│   └── Immutable audit trail
└── Data Layer (PostgreSQL + Redis)
```

## Key Innovations

**Regime Detection** — Signal ensemble maps macroeconomic conditions to regime states, informing asset-specific analysis.

**Scoring Framework** — Multi-dimensional assessment combining fundamentals, technicals, momentum, and regime alignment.

**Layered Durability Model** — Assets classified by decay characteristics. Lower decay = higher durability under stress.

**MCP Orchestration** — Tools auto-adjust analysis based on detected regime. Any LLM accesses regime-aware insights without domain logic.

## What's Open vs Private

**Open (Apache 2.0):** Framework architecture, scoring structure, layer model, tool pattern, compliance gate, caching patterns.

**Private:** Specific thresholds, decay constants, production tools, API keys, client data, narrative pipeline.

## Tech Stack

Python 3.12 · FastAPI · FastMCP · PostgreSQL · Redis · pandas · numpy · scipy · PyWavelets

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

## Related

- **[PWOS Core](https://github.com/Protocol-Wealth/pwos-core)** — Compliance-first AI operating system ([pwos.app](https://pwos.app))
- **[pw-redact](https://github.com/Protocol-Wealth/pw-redact)** — PII redaction engine

## Links

- **Live App:** [nexusmcp.site](https://nexusmcp.site)
- [Open Source Manifesto](https://nexusmcp.site/opensource)
- [Patent Documentation](https://nexusmcp.site/patent)
- [Protocol Wealth](https://protocolwealthllc.com)

---

*Built by [Protocol Wealth LLC](https://protocolwealthllc.com) — SEC-Registered Investment Adviser (CRD #335298)*
