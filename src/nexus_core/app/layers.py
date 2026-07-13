# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF durability-layer classification surface — ``/api/layer/{ticker}``.

Every asset in the EMF framework belongs to one of seven durability layers (L1
Foundation … L7 Catalyst). The layer drives two calibrated inputs the 8-check
score depends on: the λ (decay-constant) ceiling the Lambda check tests against,
and the target portfolio weight the prevailing regime assigns to the layer.

This route publishes the classification itself — including **how** it was
reached (an explicit ticker-map assignment, an asset-class route, a
sector/industry keyword rule, or a sector default) — so a reader can see why an
asset landed where it did rather than taking the layer on faith. The
classification rules are public; this makes them queryable.

The same view backs the ``classify_layer`` MCP tool (see
:mod:`nexus_core.mcp.server`), so REST and MCP always agree.

Fundamentals (sector / industry) come from SEC submissions and only matter for
assets that are neither in the explicit ticker map nor an asset-class route.
Callers who already hold a sector / industry can pass them as query params and
skip the SEC lookup entirely. Best-effort: an unreachable SEC lookup degrades
the classification to what the maps alone can decide, it never fails the
request. An asset that cannot be positively classified returns
``layer="UNCLASSIFIED"`` — never a silent default layer.

Everything here is an educational / analytical view of public data — not
investment advice, a recommendation, or a suitability determination.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Query, Response

from ..data.edgar.fundamentals import build_fundamentals
from ..disclaimers import TERSE
from ..engine.scoring.emf.layers import describe_layer, layer_catalog

#: /api/layer edge TTL — the layer maps are static and a company's sector moves
#: on a multi-year cadence, so this caches harder than /api/score.
_LAYER_TTL = 3600
_DISCLAIMER = TERSE


def _fundamentals_context(ticker: str) -> tuple[str | None, str | None]:
    """Best-effort (sector, industry) for ``ticker`` from SEC submissions."""
    fundamentals = build_fundamentals(ticker) or {}
    sector = fundamentals.get("sector")
    industry = fundamentals.get("industry")
    return (str(sector) if sector else None, str(industry) if industry else None)


def build_layer_router() -> APIRouter:
    """REST router exposing ``GET /api/layer/{ticker}`` + ``GET /api/layers``."""
    router = APIRouter(prefix="/api", tags=["scoring"])

    @router.get("/layers", summary="The published EMF 7-layer durability stack")
    def layers(response: Response) -> dict[str, Any]:
        """The seven durability layers: name, horizon, λ ceiling, regime weights."""
        response.headers["Cache-Control"] = f"public, max-age={_LAYER_TTL}"
        return {"layers": layer_catalog(), "disclaimer": _DISCLAIMER}

    @router.get("/layer/{ticker}", summary="EMF durability-layer classification (educational)")
    def layer(
        response: Response,
        ticker: str = Path(description="Stock/ETF ticker or crypto pair, e.g. NVDA, BTC-USD"),
        sector: str | None = Query(
            default=None,
            description="Override the asset's sector (skips the SEC fundamentals lookup).",
        ),
        industry: str | None = Query(
            default=None,
            description="Override the asset's industry (skips the SEC fundamentals lookup).",
        ),
    ) -> dict[str, Any]:
        """Classify a public ticker into its EMF durability layer, with provenance.

        Returns the layer code + display name, the durability horizon, the λ
        decay ceiling that applies to the layer, the layer's target weight in
        each regime, and the rule that decided the classification.
        """
        if sector is None and industry is None:
            sector, industry = _fundamentals_context(ticker)

        out = describe_layer(ticker, sector=sector, industry=industry)
        out["disclaimer"] = _DISCLAIMER
        response.headers["Cache-Control"] = f"public, max-age={_LAYER_TTL}"
        return out

    return router


__all__ = ["build_layer_router"]
