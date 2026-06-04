# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""ACA premium-tax-credit (PTC) cliff estimate for the Roth-conversion composite.

A **flag-with-magnitude estimate — NOT a precise PTC determination** — of how a
Roth conversion's MAGI bump erodes (or, at the 400% FPL hard cliff, vaporizes) a
household's ACA marketplace premium tax credit. Quantified only when an
:class:`~nexus_core.engine.planning.tables.AcaSituation` is injected; otherwise
the composite leaves a qualitative note. This needs no PlanningContract change —
the situation is an injected parameter, like the state-tax rule.

The PTC is ``max(0, benchmark - applicable_pct(MAGI%FPL) * MAGI)``. The applicable
percentage ramps linearly from 0% at/below ``lower_fpl_pct`` to
``cap_contribution_pct`` at ``cap_fpl_pct`` (the ARPA/IRA basis). Under
``cliff_mode="hard_400fpl"`` (pre-2021 / post-2025) a MAGI above ``cap_fpl_pct``
zeroes the PTC; under ``capped_8_5`` the contribution stays capped with no cliff.

Pure + deterministic; no I/O. Educational scenario analysis, not tax advice.
"""

from __future__ import annotations

from dataclasses import dataclass

from .tables import AcaSituation


def applicable_pct(pct_fpl: float, s: AcaSituation) -> float:
    """Expected-contribution percentage at a given MAGI-as-fraction-of-FPL."""
    if pct_fpl <= s.lower_fpl_pct:
        return 0.0
    if pct_fpl >= s.cap_fpl_pct:
        return s.cap_contribution_pct
    frac = (pct_fpl - s.lower_fpl_pct) / (s.cap_fpl_pct - s.lower_fpl_pct)
    return s.cap_contribution_pct * frac


def aca_ptc(magi: float, s: AcaSituation) -> float:
    """Estimated annual PTC at ``magi`` (0 above the 400% FPL hard cliff)."""
    fpl = s.fpl()
    pct_fpl = magi / fpl if fpl > 0.0 else 0.0
    if s.cliff_mode == "hard_400fpl" and pct_fpl > s.cap_fpl_pct:
        return 0.0
    expected = applicable_pct(pct_fpl, s) * magi
    return max(0.0, s.benchmark_premium_annual - expected)


@dataclass(frozen=True, slots=True)
class AcaCliffEstimate:
    """Internal estimate used to build the year note (not part of the output ABI)."""

    pct_fpl_before: float
    pct_fpl_after: float
    ptc_before: float
    ptc_after: float
    incremental_ptc_loss: float
    crosses_hard_cliff: bool


def aca_cliff_estimate(magi_before: float, magi_after: float, s: AcaSituation) -> AcaCliffEstimate:
    """Estimate the conversion's PTC erosion: MAGI before → after."""
    fpl = s.fpl()
    before = magi_before / fpl if fpl > 0.0 else 0.0
    after = magi_after / fpl if fpl > 0.0 else 0.0
    ptc_before = aca_ptc(magi_before, s)
    ptc_after = aca_ptc(magi_after, s)
    crosses = s.cliff_mode == "hard_400fpl" and before <= s.cap_fpl_pct < after
    return AcaCliffEstimate(
        pct_fpl_before=before,
        pct_fpl_after=after,
        ptc_before=ptc_before,
        ptc_after=ptc_after,
        incremental_ptc_loss=max(0.0, ptc_before - ptc_after),
        crosses_hard_cliff=crosses,
    )


__all__ = ["AcaCliffEstimate", "aca_cliff_estimate", "aca_ptc", "applicable_pct"]
