# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Regime taxonomy, transition structure, and path simulation for planning.

The pwplan-core contract uses a generic market-cycle ``Regime`` vocabulary
(``expansion | inflationary | deflationary | stagflation | crisis``). nexus-core's
``RegimeEngine`` classifies into the canonical EMF regimes
(``GROWTH | TRANSITION | HARD_ASSET | DEFLATION | REPRESSION``); :data:`_EMF_TO_GENERIC`
translates the live classification to the consumer's labels at the wire boundary
(the EMF *definitions* stay canonical in ``engine.regime``).

``currentRegime`` is the **live** classification; the transition matrix is an
**illustrative, calibrated** regime-persistence structure (documented, not a
fitted estimate — a historical fit is a future refinement). The Markov path
simulation drives ``regimePathSummary`` for the regime-aware Monte Carlo models.
Pure + deterministic given a seeded RNG. Educational only — not advice.
"""

from __future__ import annotations

import numpy as np

#: Generic planning regimes (the pwplan-core contract vocabulary), in order.
GENERIC_REGIMES: tuple[str, ...] = (
    "expansion",
    "inflationary",
    "deflationary",
    "stagflation",
    "crisis",
)

#: Live EMF regime code -> generic planning label (a wire-boundary translation;
#: the canonical EMF definitions live in nexus_core.engine.regime).
_EMF_TO_GENERIC: dict[str, str] = {
    "GROWTH": "expansion",
    "HARD_ASSET": "inflationary",
    "DEFLATION": "deflationary",
    "REPRESSION": "stagflation",
    "TRANSITION": "crisis",
}

#: Illustrative regime-transition structure P(next | current). Rows sum to 1;
#: high diagonal persistence. The ``expansion`` row matches the contract's §3.5
#: example. Calibrated/illustrative — NOT a fitted estimate.
_TRANSITION: dict[str, dict[str, float]] = {
    "expansion": {"expansion": 0.80, "inflationary": 0.08, "deflationary": 0.04, "stagflation": 0.04, "crisis": 0.04},
    "inflationary": {"expansion": 0.10, "inflationary": 0.70, "deflationary": 0.03, "stagflation": 0.12, "crisis": 0.05},
    "deflationary": {"expansion": 0.12, "inflationary": 0.05, "deflationary": 0.68, "stagflation": 0.03, "crisis": 0.12},
    "stagflation": {"expansion": 0.06, "inflationary": 0.18, "deflationary": 0.06, "stagflation": 0.62, "crisis": 0.08},
    "crisis": {"expansion": 0.25, "inflationary": 0.05, "deflationary": 0.15, "stagflation": 0.05, "crisis": 0.50},
}


def to_generic_regime(emf_code: str) -> str:
    """Translate a live EMF regime code to the generic contract label."""
    return _EMF_TO_GENERIC.get(emf_code, "expansion")


def transition_matrix() -> dict[str, dict[str, float]]:
    """Return a copy of the 5x5 generic regime-transition matrix (rows sum to 1)."""
    return {frm: dict(row) for frm, row in _TRANSITION.items()}


def path_cache_key(seed: int) -> str:
    """Mint an opaque, decodable path-cache key encoding the generating seed."""
    return f"emf-v1-{seed}"


def seed_from_cache_key(key: str | None) -> int | None:
    """Extract the seed from a path-cache key, or ``None`` (treated as a miss)."""
    if not key or not key.startswith("emf-v1-"):
        return None
    try:
        return int(key[len("emf-v1-") :])
    except ValueError:
        return None


def simulate_regime_path(
    start_regime: str, years: int, rng: np.random.Generator
) -> list[str]:
    """Simulate a length-``years`` Markov regime path from ``start_regime``."""
    regimes = list(GENERIC_REGIMES)
    index = {r: i for i, r in enumerate(regimes)}
    probs = np.array([[_TRANSITION[frm][to] for to in regimes] for frm in regimes])
    current = start_regime if start_regime in index else "expansion"
    path = [current]
    for _ in range(max(0, years - 1)):
        current = regimes[int(rng.choice(len(regimes), p=probs[index[current]]))]
        path.append(current)
    return path


__all__ = [
    "GENERIC_REGIMES",
    "path_cache_key",
    "seed_from_cache_key",
    "simulate_regime_path",
    "to_generic_regime",
    "transition_matrix",
]
