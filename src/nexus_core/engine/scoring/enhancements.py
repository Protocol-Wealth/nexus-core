# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Score enhancements: consistency, base rate anchor, adversarial brief.

These are **post-processing** passes that run after the main check evaluation.
They don't change ``total_passed`` — they add context that helps the reader
interpret a score. The three built-in enhancements capture three common
failure modes in naive scoring systems:

    1. **Consistency** — a stock can pass every quantitative check while
       having extremely volatile fundamentals. Coefficient of variation on
       revenue and EPS flags this.

    2. **Base rate anchor** — when most checks pass (HIGH confidence) but a
       few fail, the failing checks are usually the most predictive. This
       enhancement surfaces divergent checks as a warning.

    3. **Adversarial brief** — for HIGH confidence scores, explicitly frame
       the strongest arguments against the thesis. This is a falsification
       exercise in the Popper sense.

Each enhancement is a function conforming to the ``Enhancement`` signature
in ``framework.py``: ``(result, ctx) -> (key, payload) | None``.
"""

from __future__ import annotations

import statistics
from typing import Any

from .framework import ScoreResult
from .tiers import ConfidenceTier

# ----------------------------------------------------------------------
# 1. Consistency score — CV on revenue / EPS
# ----------------------------------------------------------------------


def consistency_enhancement(
    result: ScoreResult,
    ctx: Any,
) -> tuple[str, dict[str, Any]] | None:
    """Attach a coefficient-of-variation based consistency score.

    Expects ``ctx`` to carry quarterly fundamentals at
    ``ctx.fundamentals["income_statements"]`` (list of dicts with "revenue"
    and "eps" / "netIncome"). Returns None when insufficient data.
    """
    try:
        fundamentals = _get_attr_or_key(ctx, "fundamentals")
        if not fundamentals:
            return None
        stmts = fundamentals.get("income_statements") or []
        if len(stmts) < 3:
            return None

        revenues: list[float] = []
        eps_vals: list[float] = []
        for s in stmts:
            rev = s.get("revenue") or s.get("totalRevenue")
            if isinstance(rev, dict):
                rev = rev.get("raw")
            if rev is not None:
                revenues.append(float(rev))

            eps = s.get("eps") or s.get("dilutedEPS") or s.get("netIncome")
            if isinstance(eps, dict):
                eps = eps.get("raw")
            if eps is not None:
                eps_vals.append(float(eps))

        revenue_cv = _coefficient_of_variation(revenues)
        eps_cv = _coefficient_of_variation(eps_vals)

        primary_cv = revenue_cv if revenue_cv is not None else eps_cv
        if primary_cv is None:
            return None

        if primary_cv < 0.15:
            bonus, interpretation = 0.5, "Low variance"
        elif primary_cv < 0.30:
            bonus, interpretation = 0.0, "Moderate variance"
        else:
            bonus, interpretation = -0.5, "High variance"

        return "consistency", {
            "revenue_cv": round(revenue_cv, 4) if revenue_cv is not None else None,
            "eps_cv": round(eps_cv, 4) if eps_cv is not None else None,
            "score_adjustment": bonus,
            "interpretation": interpretation,
        }
    except Exception:
        return None


def _coefficient_of_variation(values: list[float]) -> float | None:
    """Return stdev / |mean|, or None if <3 values or mean ~0."""
    if len(values) < 3:
        return None
    mean = statistics.mean(values)
    if abs(mean) < 1e-9:
        return None
    return statistics.stdev(values) / abs(mean)


# ----------------------------------------------------------------------
# 2. Base rate anchor
# ----------------------------------------------------------------------

#: Default historical maintenance rates — % of assets at each tier that stay
#: in the same tier at 12 months. Replace with your own backtest if you have
#: the data; these are illustrative.
DEFAULT_BASE_RATE_MAINTENANCE: dict[str, float] = {
    ConfidenceTier.HIGH.value: 0.65,
    ConfidenceTier.MODERATE.value: 0.55,
    ConfidenceTier.LOW.value: 0.40,
    ConfidenceTier.BELOW.value: 0.25,
}


def base_rate_enhancement(
    result: ScoreResult,
    ctx: Any,
    *,
    maintenance_rates: dict[str, float] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """Attach base rate context and divergent-check warnings.

    A check is "divergent" when it disagrees with the tier: e.g. HIGH with
    some failing checks, or BELOW with some passing ones. Divergent checks
    are often the most informative — surfacing them reduces narrative bias.
    """
    rates = maintenance_rates or DEFAULT_BASE_RATE_MAINTENANCE
    pct = rates.get(result.tier.value, 0.50)

    divergent: list[str] = []
    if result.tier == ConfidenceTier.HIGH:
        divergent = [c.name for c in result.checks if c.passed is False]
    elif result.tier == ConfidenceTier.BELOW:
        divergent = [c.name for c in result.checks if c.passed is True]

    return "base_rate", {
        "tier_maintenance_pct": pct,
        "interpretation": (
            f"{pct:.0%} of assets at tier {result.tier.value} historically maintain it at 12 months"
        ),
        "narrative_override_warning": bool(divergent),
        "divergent_checks": divergent,
    }


# ----------------------------------------------------------------------
# 3. Adversarial brief (for HIGH confidence only)
# ----------------------------------------------------------------------


def adversarial_brief_enhancement(
    result: ScoreResult,
    ctx: Any,
) -> tuple[str, dict[str, Any]] | None:
    """Adversarial falsification prompt for HIGH-confidence scores.

    Returns ``None`` for non-HIGH tiers — the exercise only makes sense when
    conviction is high enough that confirmation bias is the dominant risk.
    """
    if result.tier != ConfidenceTier.HIGH:
        return None

    # Pick the 3 weakest checks — failed first, then lowest value.
    check_scores: list[tuple[str, float, bool]] = []
    for c in result.checks:
        if c.passed is False:
            sort_val = 0.0
        elif c.value is not None:
            sort_val = float(c.value)
        else:
            sort_val = 0.5
        check_scores.append((c.name, sort_val, bool(c.passed)))

    weakest = sorted(check_scores, key=lambda x: x[1])[:3]

    subject = result.subject

    return "adversarial_brief", {
        "triggered": True,
        "conviction_tier": result.tier.value,
        "weakest_checks": [
            {"name": name, "score": round(score, 3) if isinstance(score, float) else score}
            for name, score, _ in weakest
        ],
        "failure_modes": [
            (f"{name} currently scores {score:.3f} — if this deteriorates, the thesis weakens")
            for name, score, _ in weakest
        ],
        "falsification_prompt": (
            f"If you had to SHORT {subject}, what's the thesis? "
            f"Focus on: {', '.join(name for name, _, _ in weakest)}"
        ),
        "discipline_note": (
            "The higher the conviction, the harder the falsification attempt must be."
        ),
    }


# ----------------------------------------------------------------------
# Helper: read attribute OR dict key in one call
# ----------------------------------------------------------------------


def _get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


__all__ = [
    "DEFAULT_BASE_RATE_MAINTENANCE",
    "adversarial_brief_enhancement",
    "base_rate_enhancement",
    "consistency_enhancement",
]
