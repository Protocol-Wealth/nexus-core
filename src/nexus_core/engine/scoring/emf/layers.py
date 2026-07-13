# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""The EMF 7-layer durability taxonomy — display names, horizons, and profiles.

The layer *codes* (``L1``..``L7``) already drive two calibrated tables:

* :data:`~nexus_core.engine.scoring.emf.lambda_decay.LAYER_DECAY_THRESHOLDS` —
  the per-layer λ (decay-constant) ceiling the Lambda check tests against.
* :data:`~nexus_core.engine.scoring.emf.regime_alignment.LAYER_WEIGHTS_BY_REGIME`
  — the target portfolio weight each regime assigns to each layer.

What was missing is the *published* half of the taxonomy: the human display name
of each layer and its expected durability horizon (how long the layer's economic
moat is expected to hold). Both are published by Protocol Wealth on
https://protocolwealthllc.com/investing but had no representation in code, so no
API or MCP consumer could return them. :data:`LAYER_NAMES` and
:data:`LAYER_HORIZONS` are that published table, transcribed verbatim.

Note the naming split, which is deliberate and load-bearing: the *code* key for
layer 4 is ``L4_datatoll`` (that is what ``LAYER_WEIGHTS_BY_REGIME`` and the
pw-api / pwos bridges key on, and it does not change), while its *display* name
is "Data Infrastructure". Surfaces render :data:`LAYER_NAMES`; engines key on
the code.

Nothing here changes a calibrated value — this module only *reads* the existing
threshold / weight tables and adds the naming + horizon metadata beside them.

Educational and research content only — not investment advice.
"""

from __future__ import annotations

from typing import Any

from .context_helpers import UNCLASSIFIED, LayerClassification, classify_layer
from .lambda_decay import DEFAULT_LAYER_THRESHOLD, LAYER_DECAY_THRESHOLDS, compute_lambda
from .regime_alignment import LAYER_WEIGHTS_BY_REGIME, normalize_layer

#: The seven durability layers, in stack order (foundation → catalyst).
LAYER_CODES: tuple[str, ...] = ("L1", "L2", "L3", "L4", "L5", "L6", "L7")

#: Human display name per layer. ``L4``'s code key is ``L4_datatoll``; its
#: published display name is "Data Infrastructure" — surfaces show this one.
LAYER_NAMES: dict[str, str] = {
    "L1": "Foundation",
    "L2": "Backbone",
    "L3": "Engine",
    "L4": "Data Infrastructure",
    "L5": "Interface",
    "L6": "Frontier",
    "L7": "Catalyst",
}

#: Expected durability horizon per layer — how long the layer's moat is expected
#: to hold. Transcribed from the published EMF layer stack. ``L7`` is held for a
#: specific catalyst with a defined exit rather than for durability, so it has no
#: year horizon ("tactical").
LAYER_HORIZONS: dict[str, str] = {
    "L1": "40-60 yr",
    "L2": "15-30 yr",
    "L3": "5-10 yr",
    "L4": "7-12 yr",
    "L5": "3-5 yr",
    "L6": "1-3 yr",
    "L7": "tactical",
}

#: Machine-readable form of :data:`LAYER_HORIZONS` — ``(min_years, max_years)``,
#: or ``None`` for the tactical layer, which is not held for a durability window.
LAYER_HORIZON_YEARS: dict[str, tuple[int, int] | None] = {
    "L1": (40, 60),
    "L2": (15, 30),
    "L3": (5, 10),
    "L4": (7, 12),
    "L5": (3, 5),
    "L6": (1, 3),
    "L7": None,
}

#: One-line description of what each classification source means, so a consumer
#: can render the provenance without knowing the classifier's internals.
LAYER_SOURCE_RULES: dict[str, str] = {
    "ticker_map": "Explicit ticker assignment in the published EMF layer map.",
    "asset_class_crypto": "Asset-class routing: a mapped crypto pair.",
    "asset_class_sector_etf": "Asset-class routing: a mapped sector / commodity ETF.",
    "sector_industry_keyword": "Sector / industry keyword rule.",
    "sector_default": "Default layer for the asset's sector (no keyword rule matched).",
    "unclassified": (
        "No positive match. The layer is left UNCLASSIFIED rather than defaulted, so the "
        "layer-dependent checks report insufficient data instead of guessing."
    ),
}


def layer_profile(layer: Any) -> dict[str, Any] | None:
    """Return the published profile of a durability layer, or ``None``.

    Accepts any spelling :func:`normalize_layer` understands (``"L3"``,
    ``"l3"``, ``"L3_engine"``). The profile carries the code key engines use,
    the display name, the horizon, the λ ceiling that applies to the layer, and
    the layer's target weight in each of the five regimes.
    """
    key = normalize_layer(layer)
    if key is None:
        return None
    code = key.split("_")[0].upper()
    return {
        "layer": code,
        "layer_key": key,
        "name": LAYER_NAMES[code],
        "horizon": LAYER_HORIZONS[code],
        "horizon_years": LAYER_HORIZON_YEARS[code],
        "decay_threshold": LAYER_DECAY_THRESHOLDS[code],
        "regime_weights": {
            regime: weights[key] for regime, weights in LAYER_WEIGHTS_BY_REGIME.items()
        },
    }


def layer_catalog() -> list[dict[str, Any]]:
    """The full seven-layer stack as profiles, in stack order."""
    return [profile for code in LAYER_CODES if (profile := layer_profile(code)) is not None]


def describe_layer(
    ticker: str | None,
    *,
    sector: str | None = None,
    industry: str | None = None,
) -> dict[str, Any]:
    """Classify ``ticker`` and describe the resulting layer, with provenance.

    The shared view behind both public surfaces (``GET /api/layer/{ticker}`` and
    the ``classify_layer`` MCP tool), so REST and MCP always agree.

    ``sector`` / ``industry`` are the asset's fundamentals when the caller has
    them (from SEC submissions, or supplied directly). They only matter when the
    ticker is not in the explicit ticker map and is not an asset-class route.

    An unclassifiable asset returns ``layer="UNCLASSIFIED"`` with ``name`` /
    ``horizon`` / ``decay_threshold`` ``None`` — never a silent default layer.
    """
    symbol = (ticker or "").strip().upper()
    fundamentals: dict[str, Any] = {"sector": sector or "", "industry": industry or ""}
    result: LayerClassification = classify_layer(symbol, fundamentals=fundamentals)

    profile = layer_profile(result.layer) or {
        "layer": UNCLASSIFIED,
        "layer_key": None,
        "name": None,
        "horizon": None,
        "horizon_years": None,
        "decay_threshold": None,
        "regime_weights": None,
    }

    return {
        "ticker": symbol,
        **profile,
        "default_decay_threshold": DEFAULT_LAYER_THRESHOLD,
        "estimated_lambda": compute_lambda(sector=sector, industry=industry, ticker=symbol),
        "classification": {
            "source": result.source,
            "matched_on": result.matched_on,
            "rule": LAYER_SOURCE_RULES[result.source],
        },
        "sector": sector or None,
        "industry": industry or None,
    }


__all__ = [
    "LAYER_CODES",
    "LAYER_HORIZONS",
    "LAYER_HORIZON_YEARS",
    "LAYER_NAMES",
    "LAYER_SOURCE_RULES",
    "describe_layer",
    "layer_catalog",
    "layer_profile",
]
