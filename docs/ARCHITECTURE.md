# Nexus Core Architecture

## Signal Ensemble

| Signal | Source | Purpose |
|--------|--------|---------|
| Yield Curve | Treasury.gov, FRED | Growth vs recession |
| VIX | FRED/CBOE | Volatility regime |
| DXY | FRED DTWEXBGS | Dollar strength |
| CPI/Inflation | FRED | Inflation regime |
| Energy Prices | EIA | Hard asset regime |
| Credit Spreads | FRED | Credit conditions |
| Prediction Markets | Polymarket/Kalshi | 6th voting signal |

## Regime States

| Regime | Characteristics | Favored Assets |
|--------|----------------|----------------|
| Growth | Expanding economy, low vol | Equities, growth |
| Transition | Mixed signals, rising uncertainty | Balanced, quality |
| Hard Asset | Inflation, commodity strength | Energy, commodities |
| Deflation | Contraction, falling prices | Treasuries, cash |
| Repression | Negative real rates | Hard assets, BTC |

## 8-Check Scoring

1. Durability - persistence through regime changes
2. Regime Fit - current regime alignment
3. Momentum - technical trend
4. Fundamentals - financial health
5. Valuation - relative value
6. Entropy - implied vs realized vol
7. Hurst Exponent - multi-window persistence
8. Catalyst - near-term events

## MCP Tool Pattern

The reference scaffold lives at `src/nexus_core/mcp/server/app.py`. Tools register via `@mcp.tool()`. Responses optionally flow through adopter-supplied `ResponseFilter` callables before return:

```python
from nexus_core.mcp.server import build_server

def my_pii_filter(tool_name, response, *, auth_context=None):
    # adopter-implemented PII redaction
    return response

def my_tier_filter(tool_name, response, *, auth_context=None):
    # adopter-implemented tier-based response scrubbing
    return response

server = build_server(
    regime_engine=engine,
    filters=[my_pii_filter, my_tier_filter],
)
```

The scaffold ships no authentication, authorization, tier enforcement, audit logging, or PII redaction of its own. The `ResponseFilter` Protocol is the hook surface where adopters wire those concerns in; the filter implementations are entirely adopter-defined and adopter-operated.

## Access Control and Tiering (Adopter-Supplied)

The framework does not enforce access tiers. Production deployments typically need to distinguish public, authenticated, and privileged callers; adopters compose that logic on top of `ResponseFilter` (post-response scrubbing) or upstream of the MCP server (for example, an OAuth resource server in front of the FastAPI host doing authentication and rate limiting before the request reaches a tool). The current scaffold treats all callers as trusted and emits all tool output unfiltered.
