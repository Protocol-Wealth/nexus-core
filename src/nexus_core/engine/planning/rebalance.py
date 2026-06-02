# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Rebalance-to-target drift + trade list (educational).

Given current holdings (value per asset id) and a set of target weights, report
the per-asset drift from target and the self-financing trades (buys positive,
sells negative) that restore the target allocation, plus the one-way turnover.

Pure and deterministic — plain numbers in, plain data out; no market data, no
transaction-cost or tax-lot modelling, no minimum-trade thresholds. It is a
planning illustration of allocation drift, not a trade instruction and not
investment advice.
"""

from __future__ import annotations

from typing import Any

#: Tolerance for the target-weight sum check.
_WEIGHT_SUM_TOL = 1e-6


def rebalance(
    *,
    holdings: dict[str, float],
    target_weights: dict[str, float],
) -> dict[str, Any]:
    """Drift and trades to move ``holdings`` to ``target_weights``.

    Args:
        holdings: Current value per asset id (each >= 0; total > 0).
        target_weights: Target weight per asset id (each >= 0; sum to 1).

    Returns:
        ``totalValue``, ``turnover`` (sum of buys = sum of sells, the one-way
        turnover), and ``perAsset`` — one row per id present in either map, each
        ``{id, currentWeight, targetWeight, drift, tradeAmount}`` (drift =
        current − target; tradeAmount > 0 buy, < 0 sell), sorted by id.
    """
    if not holdings:
        raise ValueError("holdings must be a non-empty mapping")
    if not target_weights:
        raise ValueError("target_weights must be a non-empty mapping")
    if any(v < 0 for v in holdings.values()):
        raise ValueError("holding values must be >= 0")
    if any(w < 0 for w in target_weights.values()):
        raise ValueError("target weights must be >= 0")

    total = sum(holdings.values())
    if total <= 0:
        raise ValueError("total holdings value must be > 0")
    weight_sum = sum(target_weights.values())
    if abs(weight_sum - 1.0) > _WEIGHT_SUM_TOL:
        raise ValueError(f"target weights sum to {weight_sum:.4f}, must sum to 1")

    per_asset: list[dict[str, Any]] = []
    turnover = 0.0
    for asset_id in sorted(set(holdings) | set(target_weights)):
        current_weight = holdings.get(asset_id, 0.0) / total
        target_weight = target_weights.get(asset_id, 0.0)
        trade = (target_weight - current_weight) * total
        if trade > 0:
            turnover += trade
        per_asset.append(
            {
                "id": asset_id,
                "currentWeight": round(current_weight, 4),
                "targetWeight": round(target_weight, 4),
                "drift": round(current_weight - target_weight, 4),
                "tradeAmount": round(trade, 2),
            }
        )

    return {
        "totalValue": round(total, 2),
        "turnover": round(turnover, 2),
        "perAsset": per_asset,
    }


__all__ = ["rebalance"]
