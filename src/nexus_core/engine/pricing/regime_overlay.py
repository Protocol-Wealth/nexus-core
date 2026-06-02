# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Regime-conditioned covered-call strike selection (the EMF differentiator).

A systematic overwriting program shouldn't write the same strike in every market.
This module tilts the *target delta* of the written call by the live EMF macro
regime, then selects the matching strike from a chain and illustrates it.

Philosophy (explicit + tunable — a planning heuristic, not a fitted signal):
in **adverse / fragile** regimes (crisis, stagflation, deflationary) the program
writes **further OTM** (lower delta) to preserve upside-recovery room and reduce
assignment in a whipsaw — capital preservation first; in a **benign / trending**
regime (expansion) it allows a **higher delta** (closer strike) to harvest more
premium. Inflationary sits roughly neutral. The per-regime multipliers below are
the single tuning point.

Pure + clock-free: the caller supplies the live generic regime (the tool injects
``to_generic_regime(regime_engine.classify().regime)``) and a chain. Yield math is
delegated to :func:`crypto_covered_call`, strike pick to :func:`select_by_delta`,
so this never disagrees with the single-name or chain views. Illustration only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nexus_core.engine.pricing.crypto_overlays import (
    DISCLAIMER,
    Settlement,
    crypto_covered_call,
)
from nexus_core.engine.pricing.option_chain import ChainQuote, select_by_delta

#: Target-delta multiplier per generic regime. <1 writes further OTM (defensive),
#: >1 writes closer to the money (more premium). The one tuning point.
_REGIME_DELTA_MULTIPLIER: dict[str, float] = {
    "expansion": 1.20,
    "inflationary": 1.00,
    "deflationary": 0.70,
    "stagflation": 0.60,
    "crisis": 0.50,
}

#: Clamp the adjusted target delta to a sane OTM band.
_DELTA_FLOOR = 0.05
_DELTA_CEIL = 0.45

_RATIONALE: dict[str, str] = {
    "expansion": "Benign/trending regime — write closer to the money to harvest more premium.",
    "inflationary": "Inflationary regime — neutral target; harvest premium without chasing.",
    "deflationary": "Deflationary/fragile regime — write further OTM to keep recovery room.",
    "stagflation": "Stagflationary regime — write further OTM; assignment whipsaw risk is elevated.",
    "crisis": "Crisis regime — write well OTM; prioritize upside-recovery room over premium.",
}


#: Bounds on the effective multiplier after the defensiveness scaling.
_MULTIPLIER_FLOOR = 0.05
_MULTIPLIER_CEIL = 3.0


@dataclass
class RegimeConditionedOverwrite:
    """A regime-tilted covered-call strike pick + its illustration."""

    regime: str
    base_target_delta: float
    defensiveness: float  # the risk-preference scalar applied (1.0 = house default)
    delta_multiplier: float  # the EFFECTIVE multiplier after defensiveness scaling
    adjusted_target_delta: float
    rationale: str
    selected: dict[str, Any] | None  # the chosen chain quote, or None if no match
    covered_call: dict[str, Any] | None  # crypto_covered_call on the pick, or None
    disclaimer: str = DISCLAIMER
    notes: list[str] = field(default_factory=list)


def regime_adjusted_target_delta(
    regime: str, base_target_delta: float, defensiveness: float = 1.0
) -> tuple[float, float]:
    """Return ``(adjusted_target_delta, effective_multiplier)`` for ``regime``.

    ``defensiveness`` scales the *magnitude* of the regime tilt — the single
    risk-preference knob. With house multiplier ``m`` for the regime, the
    effective multiplier is ``1 + (m - 1) * defensiveness``: ``0`` flattens the
    tilt to neutral (1.0), ``1`` is the house default, ``>1`` amplifies it (more
    defensive in fragile regimes, more aggressive in benign ones). Unknown
    regimes use a neutral 1.0. Effective multiplier and target delta are clamped.
    """
    house = _REGIME_DELTA_MULTIPLIER.get(regime, 1.0)
    effective = 1.0 + (house - 1.0) * defensiveness
    effective = max(_MULTIPLIER_FLOOR, min(_MULTIPLIER_CEIL, effective))
    adjusted = max(_DELTA_FLOOR, min(_DELTA_CEIL, base_target_delta * effective))
    return adjusted, effective


def regime_conditioned_overwrite(
    *,
    regime: str,
    spot: float,
    settlement: Settlement,
    quotes: list[ChainQuote],
    base_target_delta: float = 0.25,
    defensiveness: float = 1.0,
    coins: float = 1.0,
) -> RegimeConditionedOverwrite:
    """Pick a covered-call strike whose delta is tilted by the live regime.

    Args:
        regime: Live generic macro regime (expansion / inflationary / deflationary
            / stagflation / crisis).
        spot: Coin price in USD.
        settlement: ``"inverse"`` or ``"linear"``.
        quotes: The option chain (calls with deltas) to select from.
        base_target_delta: The neutral target delta (default 0.25 = 25Δ).
        defensiveness: Risk-preference scalar scaling the regime tilt's magnitude
            (>= 0; ``0`` = no tilt, ``1`` = house default, ``>1`` = amplified).
        coins: Covered quantity for the illustration.

    Returns:
        A :class:`RegimeConditionedOverwrite` with the adjusted target, the chosen
        chain quote, and the covered-call illustration for it (``selected`` /
        ``covered_call`` are ``None`` when no call quote carries a delta).
    """
    if settlement not in ("inverse", "linear"):
        raise ValueError("settlement must be 'inverse' or 'linear'")
    if not 0.0 < base_target_delta < 1.0:
        raise ValueError("base_target_delta must be in (0, 1)")
    if defensiveness < 0.0:
        raise ValueError("defensiveness must be >= 0")

    adjusted, multiplier = regime_adjusted_target_delta(regime, base_target_delta, defensiveness)
    pick = select_by_delta(quotes=quotes, target_delta=adjusted, kind="call")

    selected: dict[str, Any] | None = None
    covered: dict[str, Any] | None = None
    notes: list[str] = []
    if pick is None:
        notes.append("No call quote with a delta to select from — supply a chain with deltas.")
    else:
        cc = crypto_covered_call(
            spot=spot,
            strike=pick.strike,
            expiry_days=pick.expiry_days,
            settlement=settlement,
            coins=coins,
            premium=pick.premium,
            delta=pick.delta,
        )
        selected = {
            "instrument_name": pick.instrument_name,
            "strike": pick.strike,
            "expiry_days": pick.expiry_days,
            "delta": pick.delta,
            "mark_iv": pick.mark_iv,
        }
        covered = {
            "premium_usd": round(cc.premium_usd, 2),
            "premium_coin": cc.premium_coin,
            "annualized_yield_pct": round(cc.annualized_yield_pct, 2),
            "distance_to_strike_pct": round(cc.distance_to_strike_pct, 2),
            "downside_cushion_pct": round(cc.downside_cushion_pct, 3),
            "prob_otm_approx": cc.prob_otm_approx,
        }

    return RegimeConditionedOverwrite(
        regime=regime,
        base_target_delta=base_target_delta,
        defensiveness=defensiveness,
        delta_multiplier=round(multiplier, 4),
        adjusted_target_delta=round(adjusted, 4),
        rationale=_RATIONALE.get(regime, "Neutral target."),
        selected=selected,
        covered_call=covered,
        notes=notes,
    )


__all__ = [
    "RegimeConditionedOverwrite",
    "regime_adjusted_target_delta",
    "regime_conditioned_overwrite",
]
