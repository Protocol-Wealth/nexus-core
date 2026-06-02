# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Regime-conditioned safe-withdrawal-rate overlay (educational).

A static "4% rule" ignores the macro regime you retire into — and
sequence-of-returns risk is worst when withdrawals start into an adverse regime.
This applies a regime multiplier to a base safe withdrawal rate: trim it in
stressed regimes, allow a little more in expansion. The multipliers are an
illustrative overlay whose *direction* mirrors the Monte Carlo engine's per-regime
mean-shift / vol-multiplier — they are not a calibrated rule.

This function is pure and takes the regime as an argument; the gateway tool pairs
it with the LIVE regime from the regime engine. Documented as an educational
overlay, not advice — the engine's disclaimer rides on every response.
"""

from __future__ import annotations

from typing import Any

from .regime import GENERIC_REGIMES

#: Illustrative per-regime multiplier on the base safe withdrawal rate. Direction
#: matches the MC engine's regime stress (crisis/stagflation worst). Not calibrated.
_REGIME_SWR_MULTIPLIER: dict[str, float] = {
    "expansion": 1.10,
    "inflationary": 0.95,
    "deflationary": 0.90,
    "stagflation": 0.85,
    "crisis": 0.75,
}


def regime_conditioned_swr(
    *,
    regime: str,
    base_swr: float = 0.04,
    portfolio_balance: float | None = None,
) -> dict[str, Any]:
    """Adjust a base safe withdrawal rate for the given macro ``regime``.

    Args:
        regime: A generic regime label (expansion / inflationary / deflationary /
            stagflation / crisis).
        base_swr: Unconditioned safe withdrawal rate, decimal in (0, 1).
        portfolio_balance: Optional balance; when given, the first-year withdrawal
            at the adjusted rate is returned.

    Returns:
        ``regime``, ``baseSwr``, the ``regimeMultiplier``, the ``adjustedSwr``,
        and (when a balance is given) ``firstYearWithdrawal``.

    Raises:
        ValueError: On an unknown regime or a base_swr outside (0, 1).
    """
    if regime not in GENERIC_REGIMES:
        raise ValueError(f"regime must be one of {', '.join(GENERIC_REGIMES)}")
    if not 0.0 < base_swr < 1.0:
        raise ValueError("base_swr must be in (0, 1)")
    if portfolio_balance is not None and portfolio_balance < 0.0:
        raise ValueError("portfolio_balance must be non-negative")

    multiplier = _REGIME_SWR_MULTIPLIER[regime]
    adjusted = base_swr * multiplier

    result: dict[str, Any] = {
        "regime": regime,
        "baseSwr": round(base_swr, 4),
        "regimeMultiplier": multiplier,
        "adjustedSwr": round(adjusted, 4),
    }
    if portfolio_balance is not None:
        result["firstYearWithdrawal"] = round(portfolio_balance * adjusted, 2)
    return result


__all__ = ["regime_conditioned_swr"]
