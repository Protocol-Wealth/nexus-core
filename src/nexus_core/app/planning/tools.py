# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Planning tool handlers + registry.

Each handler takes the parsed request body (a ``dict``) and returns the response
payload (a ``dict``) — the gateway adds ``contractVersion`` and maps exceptions
to HTTP status codes. Handlers validate their own inputs and raise
:class:`PlanningInputError` (400) / :class:`PlanningInfeasibleError` (422) with
human-readable messages (the consumer shows them verbatim).

Tools that need data providers (e.g. ``correlation_matrix`` needs market data)
are bound to them by :func:`build_tool_handlers`, so the registry is constructed
per-app with its dependencies injected. Tool ids are the wire contract and must
match the consumer exactly; the gateway 404s ids that aren't registered.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any, cast

from ...data.providers import MarketDataProvider
from ...engine.planning import GlidePathShape, compute_glide_path, correlation_matrix
from .contract import PlanningInfeasibleError, PlanningInputError

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

#: Asset-class id -> liquid ETF (or crypto) proxy ticker for return-series
#: estimation. The engine does not hard-code an asset *universe* (callers pass
#: arbitrary ids elsewhere); this map only backs correlation estimation from
#: real market data. Unknown ids are reported as infeasible with this list.
_ASSET_PROXIES: dict[str, str] = {
    "us_equity": "VTI",
    "us_large_cap": "SPY",
    "us_small_cap": "IWM",
    "intl_equity": "VXUS",
    "developed_ex_us": "EFA",
    "em_equity": "VWO",
    "us_bonds": "AGG",
    "us_treasuries": "GOVT",
    "tips": "TIP",
    "high_yield": "HYG",
    "real_estate": "VNQ",
    "commodities": "DBC",
    "gold": "GLD",
    "bitcoin": "BTC-USD",
}

_DEFAULT_LOOKBACK_DAYS = 1260  # ~5 trading years
_MIN_LOOKBACK_DAYS = 30
_MAX_LOOKBACK_DAYS = 3650


def _require(body: dict[str, Any], key: str) -> Any:
    if key not in body:
        raise PlanningInputError(f"missing required field '{key}'")
    return body[key]


def _as_int(body: dict[str, Any], key: str) -> int:
    value = _require(body, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise PlanningInputError(f"field '{key}' must be a whole number; got {value!r}")
    return int(value)


def _as_number(body: dict[str, Any], key: str) -> float:
    value = _require(body, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanningInputError(f"field '{key}' must be a number; got {value!r}")
    return float(value)


def _as_str(body: dict[str, Any], key: str) -> str:
    value = _require(body, key)
    if not isinstance(value, str):
        raise PlanningInputError(f"field '{key}' must be a string; got {value!r}")
    return value


def _as_str_list(body: dict[str, Any], key: str) -> list[str]:
    value = _require(body, key)
    if not isinstance(value, list) or not value or not all(isinstance(x, str) for x in value):
        raise PlanningInputError(f"field '{key}' must be a non-empty list of strings")
    return value


def glide_path_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``glide_path`` — equity weight by age across the planning horizon."""
    start = _as_number(body, "startEquityWeight")
    end = _as_number(body, "endEquityWeight")
    shape = _as_str(body, "shape")
    try:
        path = compute_glide_path(
            current_age=_as_int(body, "currentAge"),
            retirement_age=_as_int(body, "retirementAge"),
            horizon_age=_as_int(body, "horizonAge"),
            start_equity_weight=start,
            end_equity_weight=end,
            shape=cast(GlidePathShape, shape),
        )
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc
    return {"equityWeightByAge": {str(age): round(weight, 4) for age, weight in path.items()}}


def _correlation_matrix_tool(body: dict[str, Any], market: MarketDataProvider) -> dict[str, Any]:
    """``correlation_matrix`` — real-data return correlation across asset classes.

    Each asset-class id is resolved to a liquid proxy (see :data:`_ASSET_PROXIES`),
    its daily closes are fetched over ``lookbackDays``, aligned on common dates,
    and converted to log returns for sample or Ledoit-Wolf correlation.
    """
    ids = _as_str_list(body, "assetClassIds")
    lookback = body.get("lookbackDays", _DEFAULT_LOOKBACK_DAYS)
    if (
        isinstance(lookback, bool)
        or not isinstance(lookback, int)
        or not _MIN_LOOKBACK_DAYS <= lookback <= _MAX_LOOKBACK_DAYS
    ):
        raise PlanningInputError(
            f"lookbackDays must be an integer in [{_MIN_LOOKBACK_DAYS}, {_MAX_LOOKBACK_DAYS}]"
        )
    shrinkage = body.get("shrinkage", True)
    if not isinstance(shrinkage, bool):
        raise PlanningInputError("shrinkage must be a boolean")

    closes_by_id: dict[str, dict[str, float]] = {}
    for asset_id in ids:
        ticker = _ASSET_PROXIES.get(asset_id)
        if ticker is None:
            supported = ", ".join(sorted(_ASSET_PROXIES))
            raise PlanningInfeasibleError(
                f"no return series available for asset class '{asset_id}'. "
                f"Supported asset classes: {supported}."
            )
        bars = market.get_price_history(ticker, days=lookback, interval="1d")
        closes = {b.timestamp: float(b.close) for b in bars if b.close and b.close > 0}
        if len(closes) < 3:
            raise PlanningInfeasibleError(
                f"insufficient price history for '{asset_id}' ({ticker})"
            )
        closes_by_id[asset_id] = closes

    common_dates = set.intersection(*(set(c) for c in closes_by_id.values()))
    if len(common_dates) < 3:
        raise PlanningInfeasibleError(
            "not enough overlapping dates across the requested asset classes to estimate correlation"
        )
    dates = sorted(common_dates)

    returns_by_id: dict[str, list[float]] = {}
    for asset_id, closes in closes_by_id.items():
        series = [closes[d] for d in dates]
        returns_by_id[asset_id] = [
            math.log(series[k] / series[k - 1]) for k in range(1, len(series))
        ]

    matrix = correlation_matrix(returns_by_id, shrinkage=shrinkage)
    return {"matrix": matrix, "asOf": dates[-1][:10]}


def build_tool_handlers(*, market: MarketDataProvider) -> dict[str, ToolHandler]:
    """Construct the planning tool registry with its data dependencies injected.

    Tool ids MUST match the pwplan-core wire contract exactly.
    """

    def correlation_matrix_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _correlation_matrix_tool(body, market)

    return {
        "glide_path": glide_path_tool,
        "correlation_matrix": correlation_matrix_tool,
    }


__all__ = ["ToolHandler", "build_tool_handlers", "glide_path_tool"]
