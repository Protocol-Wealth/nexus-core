# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF Check 6 — Regime Alignment.

Macro-fit check: does the current market regime favor the durability *layer*
this asset belongs to? Every asset is mapped to one of seven layers (L1
Foundation … L7 Catalyst). Each regime assigns a target portfolio weight to
each layer. An asset passes when its layer carries at least a 15% target
weight in the prevailing regime.

This is a faithful port of the ``_check_macro_regime`` logic in pw-nexus
(``app/engine/portfolio_engine.py``) and the canonical ``LAYER_WEIGHTS_BY_REGIME``
table from ``app/engine/emf_engine.py``. The weights are percentages (0–100),
so the threshold is ``15`` (i.e. 15% of the model portfolio), not ``0.15``.

Intellectual lineage: Hamilton (1989) regime-switching + Dalio's economic
machine + Bridgewater All Weather. See ``attribution.py``.
"""

from __future__ import annotations

from typing import Any

from ..checks import CheckResult, ScoringContext

# ---------------------------------------------------------------------------
# Canonical 7-layer target weights by regime (percent of model portfolio).
# Ported verbatim from pw-nexus app/engine/emf_engine.py LAYER_WEIGHTS_BY_REGIME.
# Regime keys are the canonical single-letter codes:
#   G = Growth, T = Transition, H = Hard Asset, D = Deflation, R = Repression.
# ---------------------------------------------------------------------------
LAYER_WEIGHTS_BY_REGIME: dict[str, dict[str, int]] = {
    "G": {  # GROWTH
        "L1_foundation": 10,
        "L2_backbone": 15,
        "L3_engine": 25,
        "L4_datatoll": 20,
        "L5_interface": 15,
        "L6_frontier": 10,
        "L7_catalyst": 5,
    },
    "T": {  # TRANSITION
        "L1_foundation": 20,
        "L2_backbone": 20,
        "L3_engine": 20,
        "L4_datatoll": 15,
        "L5_interface": 10,
        "L6_frontier": 5,
        "L7_catalyst": 10,
    },
    "H": {  # HARD_ASSET
        "L1_foundation": 30,
        "L2_backbone": 30,
        "L3_engine": 15,
        "L4_datatoll": 15,
        "L5_interface": 5,
        "L6_frontier": 0,
        "L7_catalyst": 5,
    },
    "D": {  # DEFLATION
        "L1_foundation": 25,
        "L2_backbone": 30,
        "L3_engine": 15,
        "L4_datatoll": 15,
        "L5_interface": 10,
        "L6_frontier": 0,
        "L7_catalyst": 5,
    },
    "R": {  # REPRESSION
        "L1_foundation": 30,
        "L2_backbone": 30,
        "L3_engine": 15,
        "L4_datatoll": 10,
        "L5_interface": 5,
        "L6_frontier": 5,
        "L7_catalyst": 5,
    },
}

# Map a variety of regime spellings to the canonical single-letter code.
_REGIME_ALIASES: dict[str, str] = {
    "G": "G",
    "GROWTH": "G",
    "T": "T",
    "TRANSITION": "T",
    "H": "H",
    "HARD_ASSET": "H",
    "HARD ASSET": "H",
    "HARDASSET": "H",
    "D": "D",
    "DEFLATION": "D",
    "R": "R",
    "REPRESSION": "R",
}

# Map a variety of layer spellings to the canonical weight-table key.
_LAYER_KEYS: tuple[str, ...] = (
    "L1_foundation",
    "L2_backbone",
    "L3_engine",
    "L4_datatoll",
    "L5_interface",
    "L6_frontier",
    "L7_catalyst",
)
_LAYER_SHORT: dict[str, str] = {key.split("_")[0].upper(): key for key in _LAYER_KEYS}


def normalize_regime(value: Any) -> str | None:
    """Resolve a regime label/code to its canonical single-letter code.

    Accepts the canonical codes ("G".."R"), full names ("GROWTH",
    "HARD_ASSET", "Hard Asset"), or substrings thereof. Returns ``None`` when
    no regime can be determined.
    """
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text in _REGIME_ALIASES:
        return _REGIME_ALIASES[text]
    # Substring fallback, mirroring pw-nexus's "GROWTH"/"HARD"/... matching.
    if "GROWTH" in text:
        return "G"
    if "HARD" in text:
        return "H"
    if "DEFLATION" in text:
        return "D"
    if "REPRESSION" in text:
        return "R"
    if "TRANSITION" in text:
        return "T"
    return None


def normalize_layer(value: Any) -> str | None:
    """Resolve a layer label to its canonical weight-table key.

    Accepts full keys ("L3_engine"), short codes ("L3"/"l3"), or names with a
    leading layer code. Returns ``None`` when no layer can be determined.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {k.lower() for k in _LAYER_KEYS}:
        return next(k for k in _LAYER_KEYS if k.lower() == lowered)
    short = text.split("_")[0].upper()
    return _LAYER_SHORT.get(short)


def regime_layer_weight(regime: Any, layer: Any) -> int | None:
    """Look up the target weight (percent) for ``layer`` in ``regime``.

    Returns ``None`` if either the regime or the layer cannot be resolved.
    Returns ``0`` when the layer resolves but carries no weight in that regime
    (a real "unfavored" answer, distinct from missing data).
    """
    code = normalize_regime(regime)
    key = normalize_layer(layer)
    if code is None or key is None:
        return None
    weights = LAYER_WEIGHTS_BY_REGIME.get(code)
    if weights is None:
        return None
    return weights.get(key, 0)


def _extract_regime(ctx: ScoringContext) -> Any:
    """Pull the regime code from the context, checking common locations."""
    for source in (ctx.regime, ctx.extra):
        for field_name in ("code", "regime", "regime_code", "current_regime"):
            if field_name in source and source[field_name] not in (None, ""):
                return source[field_name]
    return None


def _extract_layer(ctx: ScoringContext) -> Any:
    """Pull the asset's durability layer from the context."""
    for source in (ctx.fundamentals, ctx.extra):
        for field_name in ("layer", "layer_assignment", "emf_layer"):
            if field_name in source and source[field_name] not in (None, ""):
                return source[field_name]
    return None


class RegimeAlignmentCheck:
    """EMF Check 6 — passes when the asset's layer carries >= 15% regime weight.

    Reads the prevailing regime from ``ctx.regime`` (or ``ctx.extra``) and the
    asset's durability layer from ``ctx.fundamentals`` (or ``ctx.extra``). When
    either is absent or unrecognized, the check degrades to ``passed=None`` with
    ``signal="insufficient_data"`` rather than guessing.
    """

    def __init__(self, threshold: float = 15.0) -> None:
        self.threshold = threshold

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        regime_raw = _extract_regime(ctx)
        layer_raw = _extract_layer(ctx)
        code = normalize_regime(regime_raw)
        key = normalize_layer(layer_raw)

        if code is None or key is None:
            return CheckResult(
                check_number=6,
                name="Regime Alignment",
                value=None,
                threshold=self.threshold,
                passed=None,
                signal="insufficient_data",
                interpretation=(
                    "Regime Alignment requires both a current regime and an "
                    "asset layer assignment; one or both were unavailable."
                ),
                details={
                    "current_regime": code,
                    "layer": key,
                    "regime_raw": regime_raw,
                    "layer_raw": layer_raw,
                },
            )

        weights = LAYER_WEIGHTS_BY_REGIME[code]
        layer_weight = weights.get(key, 0)
        passed = layer_weight >= self.threshold

        if layer_weight >= 20:
            signal = "GREEN"
            interp = f"{key} favored in {code} regime ({layer_weight}% weight)"
        elif layer_weight >= 15:
            signal = "GREEN"
            interp = f"{key} aligned with {code} regime ({layer_weight}% weight)"
        elif layer_weight >= 10:
            signal = "YELLOW"
            interp = f"{key} marginal in {code} regime ({layer_weight}% weight)"
        else:
            signal = "RED"
            interp = f"{key} unfavored in {code} regime ({layer_weight}% weight)"

        return CheckResult(
            check_number=6,
            name="Regime Alignment",
            value=float(layer_weight),
            threshold=self.threshold,
            passed=passed,
            signal=signal,
            interpretation=interp,
            details={
                "current_regime": code,
                "layer": key,
                "all_weights": dict(weights),
            },
        )


__all__ = [
    "LAYER_WEIGHTS_BY_REGIME",
    "RegimeAlignmentCheck",
    "normalize_layer",
    "normalize_regime",
    "regime_layer_weight",
]
