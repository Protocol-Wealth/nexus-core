# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Planning tool handlers + registry.

Each handler takes the parsed request body (a ``dict``) and returns the response
payload (a ``dict``) — the gateway adds ``contractVersion`` and maps exceptions
to HTTP status codes. Handlers validate their own inputs and raise
:class:`PlanningInputError` (400) / :class:`PlanningInfeasibleError` (422) with
human-readable messages (the consumer shows them verbatim).

Tools that need data providers (e.g. ``correlation_matrix`` and
``capital_market_assumptions`` need market data) are bound to them by
:func:`build_tool_handlers`, so the registry is constructed per-app with its
dependencies injected. Tool ids are the wire contract and must match the consumer
exactly; the gateway 404s ids that aren't registered.
"""

from __future__ import annotations

import math
import secrets
import statistics
from collections.abc import Callable
from typing import Any, cast

from ...data.providers import MarketDataProvider
from ...engine.planning import (
    GlidePathShape,
    InfeasiblePlanError,
    compute_glide_path,
    correlation_matrix,
    tax_aware_withdrawal,
)
from ...engine.planning.regime import path_cache_key, to_generic_regime, transition_matrix
from ...engine.regime import RegimeEngine
from .contract import PlanningInfeasibleError, PlanningInputError
from .universe import ASSET_UNIVERSE, proxy_tickers, universe_ids

_MAX_SEED = 2**31 - 1

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]

_DEFAULT_LOOKBACK_DAYS = 1260  # ~5 trading years
_MIN_LOOKBACK_DAYS = 30
_MAX_LOOKBACK_DAYS = 3650
_TRADING_DAYS = 252.0


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


def _fetch_aligned_returns(
    market: MarketDataProvider,
    tickers_by_id: dict[str, str],
    *,
    lookback: int,
    as_of: str | None = None,
) -> tuple[dict[str, list[float]], str]:
    """Fetch daily closes per asset, align on common dates, build log returns.

    Returns ``(log_returns_by_id, latest_aligned_iso_date)``. When ``as_of`` is
    given, only closes on/before that ISO date are used. Raises
    :class:`PlanningInfeasibleError` when an asset lacks history or the series do
    not overlap enough to estimate.
    """
    closes_by_id: dict[str, dict[str, float]] = {}
    for asset_id, ticker in tickers_by_id.items():
        bars = market.get_price_history(ticker, days=lookback, interval="1d")
        closes = {b.timestamp: float(b.close) for b in bars if b.close and b.close > 0}
        if as_of is not None:
            closes = {ts: c for ts, c in closes.items() if ts[:10] <= as_of}
        if len(closes) < 3:
            raise PlanningInfeasibleError(f"insufficient price history for '{asset_id}' ({ticker})")
        closes_by_id[asset_id] = closes

    common_dates = set.intersection(*(set(c) for c in closes_by_id.values()))
    if len(common_dates) < 3:
        raise PlanningInfeasibleError(
            "not enough overlapping dates across the requested asset classes"
        )
    dates = sorted(common_dates)

    returns_by_id: dict[str, list[float]] = {}
    for asset_id, closes in closes_by_id.items():
        series = [closes[d] for d in dates]
        returns_by_id[asset_id] = [
            math.log(series[k] / series[k - 1]) for k in range(1, len(series))
        ]
    return returns_by_id, dates[-1][:10]


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


def tax_aware_withdrawal_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``tax_aware_withdrawal`` — RMD-first, tax-efficient withdrawal sequencing."""
    accounts = _require(body, "accounts")
    if not isinstance(accounts, list) or not accounts:
        raise PlanningInputError("accounts must be a non-empty list")
    other = body.get("otherTaxableIncome", 0)
    if isinstance(other, bool) or not isinstance(other, (int, float)):
        raise PlanningInputError("otherTaxableIncome must be a number")
    try:
        return tax_aware_withdrawal(
            year=_as_int(body, "year"),
            filing_status=_as_str(body, "filingStatus"),
            accounts=accounts,
            gross_need=_as_number(body, "grossNeed"),
            age=_as_int(body, "age"),
            other_taxable_income=float(other),
        )
    except InfeasiblePlanError as exc:
        raise PlanningInfeasibleError(str(exc)) from exc
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def _correlation_matrix_tool(body: dict[str, Any], market: MarketDataProvider) -> dict[str, Any]:
    """``correlation_matrix`` — real-data return correlation across asset classes."""
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

    proxies = proxy_tickers()
    tickers: dict[str, str] = {}
    for asset_id in ids:
        ticker = proxies.get(asset_id)
        if ticker is None:
            raise PlanningInfeasibleError(
                f"no return series available for asset class '{asset_id}'. "
                f"Supported asset classes: {', '.join(sorted(proxies))}."
            )
        tickers[asset_id] = ticker

    returns_by_id, as_of = _fetch_aligned_returns(market, tickers, lookback=lookback)
    matrix = correlation_matrix(returns_by_id, shrinkage=shrinkage)
    return {"matrix": matrix, "asOf": as_of}


def _capital_market_assumptions_tool(
    body: dict[str, Any], market: MarketDataProvider
) -> dict[str, Any]:
    """``capital_market_assumptions`` — the engine's real-data asset assumptions.

    Returns ``assetClasses`` (forward expectedReturn + lambda from the engine's
    house view; volatility from the proxy's real history) and a real ``correlations``
    matrix + an ``asOf`` date. Shapes are drop-in for a ``monte_carlo_decumulation``
    request. Unknown id → 400; omitted ids → the full default universe.
    """
    raw_ids = body.get("assetClassIds")
    if raw_ids is None or raw_ids == []:
        ids = universe_ids()
    elif isinstance(raw_ids, list) and all(isinstance(x, str) for x in raw_ids):
        ids = raw_ids
    else:
        raise PlanningInputError("assetClassIds must be a list of strings (or omitted)")

    unknown = [i for i in ids if i not in ASSET_UNIVERSE]
    if unknown:
        raise PlanningInputError(
            f"unknown asset class id(s): {', '.join(unknown)}. "
            f"Known asset classes: {', '.join(universe_ids())}."
        )

    as_of = body.get("asOf")
    if as_of is not None and not isinstance(as_of, str):
        raise PlanningInputError("asOf must be an ISO date string (or omitted)")

    tickers = {i: ASSET_UNIVERSE[i].ticker for i in ids}
    returns_by_id, resolved_as_of = _fetch_aligned_returns(
        market, tickers, lookback=_DEFAULT_LOOKBACK_DAYS, as_of=as_of
    )

    asset_classes: list[dict[str, Any]] = []
    for asset_id in ids:
        assumption = ASSET_UNIVERSE[asset_id]
        returns = returns_by_id[asset_id]
        volatility = statistics.pstdev(returns) * math.sqrt(_TRADING_DAYS) if len(returns) > 1 else 0.0
        asset_classes.append(
            {
                "id": asset_id,
                "label": assumption.label,
                "expectedReturn": assumption.expected_return,
                "volatility": round(volatility, 4),
                "lambda": assumption.lambda_,
            }
        )

    correlations = correlation_matrix(returns_by_id, shrinkage=True)
    return {"assetClasses": asset_classes, "correlations": correlations, "asOf": resolved_as_of}


def _resolve_seed(body: dict[str, Any]) -> int:
    """Return the seed to use: the supplied non-negative int, or a fresh one."""
    seed = body.get("seed")
    if seed is None:
        return secrets.randbelow(_MAX_SEED)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= _MAX_SEED:
        raise PlanningInputError(f"seed must be an integer in [0, {_MAX_SEED}] or null")
    return seed


def _validate_asset_classes(body: dict[str, Any], *, require_lambda: bool) -> list[dict[str, Any]]:
    """Validate the ``assetClasses`` list; require a numeric ``lambda`` when asked."""
    raw = _require(body, "assetClasses")
    if not isinstance(raw, list) or not raw:
        raise PlanningInputError("assetClasses must be a non-empty list")
    for asset in raw:
        if not isinstance(asset, dict) or not isinstance(asset.get("id"), str):
            raise PlanningInputError("each assetClass must be an object with a string id")
        if require_lambda:
            lam = asset.get("lambda")
            if isinstance(lam, bool) or not isinstance(lam, (int, float)):
                raise PlanningInputError(
                    f"assetClass '{asset.get('id')}' requires a numeric lambda (for emf_regime)"
                )
    return raw


def _regime_return_generator_tool(
    body: dict[str, Any], regime_engine: RegimeEngine
) -> dict[str, Any]:
    """``regime_return_generator`` — live current regime + transition matrix + cache key."""
    _validate_asset_classes(body, require_lambda=True)
    horizon = _as_int(body, "horizonYears")
    if not 1 <= horizon <= 200:
        raise PlanningInputError("horizonYears must be an integer in [1, 200]")
    seed_used = _resolve_seed(body)
    result = regime_engine.classify()
    return {
        "currentRegime": to_generic_regime(result.regime),
        "transitionMatrix": transition_matrix(),
        "pathCacheKey": path_cache_key(seed_used),
        "seedUsed": seed_used,
    }


def build_tool_handlers(
    *, market: MarketDataProvider, regime_engine: RegimeEngine
) -> dict[str, ToolHandler]:
    """Construct the planning tool registry with its data dependencies injected.

    Tool ids MUST match the pwplan-core wire contract exactly.
    """

    def correlation_matrix_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _correlation_matrix_tool(body, market)

    def capital_market_assumptions_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _capital_market_assumptions_tool(body, market)

    def regime_return_generator_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _regime_return_generator_tool(body, regime_engine)

    return {
        "glide_path": glide_path_tool,
        "tax_aware_withdrawal": tax_aware_withdrawal_tool,
        "correlation_matrix": correlation_matrix_tool,
        "capital_market_assumptions": capital_market_assumptions_tool,
        "regime_return_generator": regime_return_generator_tool,
    }


__all__ = [
    "ToolHandler",
    "build_tool_handlers",
    "glide_path_tool",
    "tax_aware_withdrawal_tool",
]
