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

```python
@mcp.tool()
def score_ticker(ticker: str, auth_key: str = "") -> str:
    denied = check_tier("user", auth_key=auth_key)
    if denied:
        return denied
    # scoring logic
    return json.dumps(result)
```

## Tiered Access

| Tier | Access |
|------|--------|
| PUBLIC | No auth - market news, basic regime |
| USER | API key - scoring, technicals |
| CLIENT | Client key - portfolio, filtered |
| ADVISOR | Full access including PII data |
