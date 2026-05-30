# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""The planning engine's capital-market asset universe.

One source of truth for the asset classes the engine knows about: each maps to a
liquid ETF/crypto **proxy ticker** (used to estimate volatility + correlations
from real market data) plus the engine's **forward house-view assumptions** —
``expected_return`` and ``lambda`` (the EMF regime-sensitivity decay). Returns and
lambda are forward estimates (a capital-market-assumptions view, not market
observables); volatility and correlations are computed from the proxy's real
price history at request time, so a returned ``asOf`` date is meaningful.

This fixed universe backs ``capital_market_assumptions`` (which publishes these
assumptions) and ``correlation_matrix`` (which uses the proxy tickers). It does
**not** constrain ``monte_carlo_decumulation``, which accepts arbitrary
client-supplied asset classes with their own per-asset params.

Educational illustrative assumptions — not investment advice or a forecast.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssetAssumption:
    """An asset class: market proxy + the engine's forward house-view assumptions.

    Attributes:
        ticker: Liquid ETF/crypto proxy for real volatility + correlation estimation.
        label: Human-readable name.
        expected_return: Forward annualized expected return (decimal).
        lambda_: EMF regime-sensitivity decay (``[0, 1]``; higher = more
            regime-sensitive), used by the ``emf_regime`` return model.
    """

    ticker: str
    label: str
    expected_return: float
    lambda_: float


#: The engine's published asset universe. Expected returns + lambdas are
#: illustrative forward assumptions; volatility/correlations come from the
#: proxy's real price history at request time.
ASSET_UNIVERSE: dict[str, AssetAssumption] = {
    "us_equity": AssetAssumption("VTI", "US Equity", 0.068, 0.35),
    "us_large_cap": AssetAssumption("SPY", "US Large Cap", 0.065, 0.34),
    "us_small_cap": AssetAssumption("IWM", "US Small Cap", 0.072, 0.42),
    "intl_equity": AssetAssumption("VXUS", "International Equity", 0.070, 0.36),
    "developed_ex_us": AssetAssumption("EFA", "Developed ex-US Equity", 0.068, 0.35),
    "em_equity": AssetAssumption("VWO", "Emerging-Market Equity", 0.085, 0.50),
    "us_bonds": AssetAssumption("AGG", "US Aggregate Bonds", 0.041, 0.11),
    "us_treasuries": AssetAssumption("GOVT", "US Treasuries", 0.038, 0.08),
    "tips": AssetAssumption("TIP", "TIPS (Inflation-Linked)", 0.039, 0.12),
    "high_yield": AssetAssumption("HYG", "High-Yield Credit", 0.058, 0.30),
    "real_estate": AssetAssumption("VNQ", "Real Estate (REITs)", 0.064, 0.40),
    "commodities": AssetAssumption("DBC", "Commodities", 0.045, 0.45),
    "gold": AssetAssumption("GLD", "Gold", 0.035, 0.25),
    "bitcoin": AssetAssumption("BTC-USD", "Bitcoin", 0.120, 0.70),
}


def proxy_tickers() -> dict[str, str]:
    """Asset-class id → proxy ticker, for return-series estimation."""
    return {asset_id: a.ticker for asset_id, a in ASSET_UNIVERSE.items()}


def universe_ids() -> list[str]:
    """All known asset-class ids, in display order."""
    return list(ASSET_UNIVERSE)


__all__ = ["ASSET_UNIVERSE", "AssetAssumption", "proxy_tickers", "universe_ids"]
