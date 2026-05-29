# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF 8-check scoring surface: context builder + ``/api/score`` route.

Ties the data layer (SEC fundamentals + market prices + the regime engine) to
the ``ScoringFramework`` so a single ticker resolves to a full 8-check EMF
durability score. The same context builder + framework back the MCP
``score_asset`` tool (see :mod:`nexus_core.mcp.server`), so REST and MCP return
identical scores.

Checks 1-3 (CROIC, F-Score, Hurst) evaluate from SEC fundamentals + price
history; 4/6/7/8 (Lambda, Regime Alignment, Sector Tailwind, ASAN) evaluate from
the regime code + sector/layer context; Perez (5) reports ``insufficient_data``
until a Perez-phase source is wired. Tier classification is always calibrated to
the full 8-check framework.

Everything here is an educational / analytical view of public data — not
investment advice, a recommendation, or a suitability determination.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Path, Response

from ..data.edgar.fundamentals import build_fundamentals
from ..data.providers import MarketDataProvider
from ..engine.regime import RegimeEngine
from ..engine.scoring import ScoringFramework, format_structured
from ..engine.scoring.checks import ScoringContext
from ..engine.scoring.emf import protocol_wealth_checks
from ..engine.scoring.emf.context_helpers import populate_context

#: /api/score edge TTL — fundamentals + regime are slow-changing.
_SCORE_TTL = 1800
#: Price-history window for the Hurst check (multi-window up to 90d).
_HISTORY_DAYS = 400
_DISCLAIMER = "Educational illustration only — not investment advice."


def build_scoring_framework() -> ScoringFramework:
    """The Protocol Wealth 8-check framework (tiers calibrated to all 8)."""
    return ScoringFramework(checks=protocol_wealth_checks(), total_checks_override=8)


def build_scoring_context(
    ticker: str,
    *,
    market: MarketDataProvider,
    regime_engine: RegimeEngine,
) -> ScoringContext:
    """Assemble a fully-populated :class:`ScoringContext` for ``ticker``.

    Fundamentals come from SEC companyfacts (``None`` for ETFs/crypto with no
    XBRL — those checks then report ``insufficient_data``); prices from the
    market provider; the regime code from the regime engine; sector / layer /
    sector-return context from :func:`populate_context`. Best-effort: a failure
    in any source degrades that input rather than raising.
    """
    fundamentals = build_fundamentals(ticker) or {}

    try:
        bars = market.get_price_history(ticker, days=_HISTORY_DAYS, interval="1d")
    except Exception:  # pragma: no cover — provider best-effort
        bars = []
    prices = [asdict(bar) for bar in bars]

    try:
        regime_code = regime_engine.classify().to_dict().get("regime")
    except Exception:  # pragma: no cover — engine best-effort
        regime_code = None

    ctx = ScoringContext(ticker=ticker.upper(), fundamentals=fundamentals, prices=prices)
    populate_context(ctx, market=market, regime_code=regime_code)
    return ctx


def build_score_router(*, market: MarketDataProvider, regime_engine: RegimeEngine) -> APIRouter:
    """REST router exposing ``GET /api/score/{ticker}``."""
    router = APIRouter(prefix="/api", tags=["scoring"])
    framework = build_scoring_framework()

    @router.get("/score/{ticker}", summary="EMF 8-check durability score (educational)")
    def score(
        response: Response,
        ticker: str = Path(description="Stock/ETF ticker, e.g. AAPL"),
    ) -> dict[str, Any]:
        """Run the 8-check EMF durability framework against a public ticker."""
        ctx = build_scoring_context(ticker, market=market, regime_engine=regime_engine)
        result = framework.score(ctx, subject=ticker.upper())
        out = format_structured(result)
        out["disclaimer"] = _DISCLAIMER
        response.headers["Cache-Control"] = f"public, max-age={_SCORE_TTL}"
        return out

    return router


__all__ = ["build_score_router", "build_scoring_context", "build_scoring_framework"]
