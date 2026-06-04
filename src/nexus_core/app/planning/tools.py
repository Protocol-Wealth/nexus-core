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
from dataclasses import asdict
from typing import Any, cast

from ...data.providers import MarketDataProvider
from ...engine.planning import (
    GlidePathShape,
    InfeasiblePlanError,
    analyze_roth_conversion,
    bracket_headroom,
    compute_glide_path,
    correlation_matrix,
    fire,
    irmaa_headroom,
    monte_carlo_decumulation,
    portfolio_xray,
    rebalance,
    reference_bracket_table,
    reference_irmaa_table,
    reference_state_rule,
    regime_conditioned_swr,
    risk_metrics,
    rmd,
    roth_conversion,
    sequence_conversions,
    sequence_of_returns_stress,
    social_security_claiming,
    tax_aware_withdrawal,
)
from ...engine.planning.case import (
    PlanningContract,
    PlanningContractError,
    engine_filing_status,
)
from ...engine.planning.regime import (
    path_cache_key,
    seed_from_cache_key,
    to_generic_regime,
    transition_matrix,
)
from ...engine.planning.tables import (
    AcaSituation,
    BracketTable,
    IrmaaTable,
    StateConversionRule,
    TableError,
)
from ...engine.planning.tax import FilingStatus
from ...engine.regime import RegimeEngine
from .contract import PlanningInfeasibleError, PlanningInputError
from .universe import ASSET_UNIVERSE, proxy_tickers, universe_ids

_MAX_SEED = 2**31 - 1
_MC_MAX_PATHS = 50000
_RETURN_MODELS = (
    "multivariate_normal",
    "student_t",
    "block_bootstrap",
    "markov_regime",
    "emf_regime",
)

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


def _as_num_list(body: dict[str, Any], key: str) -> list[float]:
    value = _require(body, key)
    if (
        not isinstance(value, list)
        or not value
        or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in value)
    ):
        raise PlanningInputError(f"field '{key}' must be a non-empty list of numbers")
    return [float(x) for x in value]


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


_FILING_STATUSES: tuple[FilingStatus, ...] = (
    "single",
    "married_joint",
    "married_separate",
    "head_of_household",
)


def roth_conversion_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``roth_conversion`` — convert-now vs. leave-pre-tax after-tax comparison."""
    filing = _as_str(body, "filingStatus")
    if filing not in _FILING_STATUSES:
        raise PlanningInputError(f"filingStatus must be one of {', '.join(_FILING_STATUSES)}")
    taxes_from = body.get("taxesPaidFromConversion", False)
    if not isinstance(taxes_from, bool):
        raise PlanningInputError("taxesPaidFromConversion must be a boolean")
    try:
        return roth_conversion(
            current_taxable_income=_as_number(body, "currentTaxableIncome"),
            filing_status=filing,
            conversion_amount=_as_number(body, "conversionAmount"),
            growth_rate=_as_number(body, "growthRate"),
            years=_as_int(body, "years"),
            retirement_marginal_rate=_as_number(body, "retirementMarginalRate"),
            taxes_paid_from_conversion=taxes_from,
        )
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def sequence_of_returns_stress_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``sequence_of_returns_stress`` — ordering effect on a fixed return set."""
    try:
        return sequence_of_returns_stress(
            initial_balance=_as_number(body, "initialBalance"),
            net_spend_by_year=_as_num_list(body, "netSpendByYear"),
            annual_returns=_as_num_list(body, "annualReturns"),
        )
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def rmd_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``rmd`` — required minimum distribution for a traditional account."""
    try:
        return rmd(age=_as_int(body, "age"), balance=_as_number(body, "balance"))
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def tax_bracket_headroom_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``tax_bracket_headroom`` — marginal bracket + room before the next rate."""
    filing = _as_str(body, "filingStatus")
    if filing not in _FILING_STATUSES:
        raise PlanningInputError(f"filingStatus must be one of {', '.join(_FILING_STATUSES)}")
    target = body.get("targetRate")
    if target is not None and (isinstance(target, bool) or not isinstance(target, (int, float))):
        raise PlanningInputError("targetRate must be a number or omitted")
    try:
        return bracket_headroom(
            taxable_income=_as_number(body, "taxableIncome"),
            filing_status=filing,
            target_rate=float(target) if target is not None else None,
        )
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def social_security_claiming_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``social_security_claiming`` — benefit by claim age + breakeven ages."""
    fra = body.get("fraAge", 67)
    if isinstance(fra, bool) or not isinstance(fra, int):
        raise PlanningInputError("fraAge must be an integer or omitted")
    try:
        return social_security_claiming(pia_monthly=_as_number(body, "piaMonthly"), fra_age=fra)
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def fire_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``fire`` — FIRE / Coast-FIRE numbers + years/age to financial independence."""
    swr = body.get("swr", 0.04)
    if isinstance(swr, bool) or not isinstance(swr, (int, float)):
        raise PlanningInputError("swr must be a number or omitted")
    try:
        return fire(
            current_age=_as_int(body, "currentAge"),
            retirement_age=_as_int(body, "retirementAge"),
            current_balance=_as_number(body, "currentBalance"),
            annual_contribution=_as_number(body, "annualContribution"),
            growth_rate=_as_number(body, "growthRate"),
            annual_spend=_as_number(body, "annualSpend"),
            swr=float(swr),
        )
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def risk_metrics_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``risk_metrics`` — annualized risk statistics for a periodic return series."""
    rf = body.get("riskFreeRate", 0.0)
    if isinstance(rf, bool) or not isinstance(rf, (int, float)):
        raise PlanningInputError("riskFreeRate must be a number or omitted")
    ppy = body.get("periodsPerYear", 1)
    if isinstance(ppy, bool) or not isinstance(ppy, int):
        raise PlanningInputError("periodsPerYear must be an integer or omitted")
    try:
        return risk_metrics(
            returns=_as_num_list(body, "returns"),
            risk_free_rate=float(rf),
            periods_per_year=ppy,
        )
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def rebalance_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``rebalance`` — drift + self-financing trades to reach target weights.

    Current holdings come from the same blended portfolio as the other
    portfolio tools (accounts × allocations); ``targetWeights`` is the desired
    allocation (ids must be declared asset classes, weights sum to 1).
    """
    asset_classes = _validate_asset_classes(body, require_lambda=False)
    asset_ids = [str(a["id"]) for a in asset_classes]
    if len(set(asset_ids)) != len(asset_ids):
        raise PlanningInputError("asset class ids must be unique")
    weights, total = _blended_weights(body.get("accounts"), asset_ids)
    holdings = {aid: w * total for aid, w in zip(asset_ids, weights, strict=True)}

    raw_targets = _require(body, "targetWeights")
    if not isinstance(raw_targets, dict) or not raw_targets:
        raise PlanningInputError("targetWeights must be a non-empty object")
    id_set = set(asset_ids)
    targets: dict[str, float] = {}
    for asset_id, weight in raw_targets.items():
        if asset_id not in id_set:
            raise PlanningInputError(
                f"targetWeights references undeclared asset class '{asset_id}'"
            )
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise PlanningInputError("target weights must be numbers")
        targets[asset_id] = float(weight)
    try:
        return rebalance(holdings=holdings, target_weights=targets)
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def _regime_conditioned_swr_tool(
    body: dict[str, Any], regime_engine: RegimeEngine
) -> dict[str, Any]:
    """``regime_conditioned_swr`` — base SWR adjusted for the LIVE macro regime."""
    base = body.get("baseSwr", 0.04)
    if isinstance(base, bool) or not isinstance(base, (int, float)):
        raise PlanningInputError("baseSwr must be a number or omitted")
    balance = body.get("portfolioBalance")
    if balance is not None and (isinstance(balance, bool) or not isinstance(balance, (int, float))):
        raise PlanningInputError("portfolioBalance must be a number or omitted")
    regime = to_generic_regime(regime_engine.classify().regime)
    try:
        return regime_conditioned_swr(
            regime=regime,
            base_swr=float(base),
            portfolio_balance=float(balance) if balance is not None else None,
        )
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def _portfolio_xray_tool(body: dict[str, Any], regime_engine: RegimeEngine) -> dict[str, Any]:
    """``portfolio_xray`` — regime-aware structural diagnostics for a portfolio."""
    asset_classes = _validate_asset_classes(body, require_lambda=False)
    asset_ids = [str(a["id"]) for a in asset_classes]
    if len(set(asset_ids)) != len(asset_ids):
        raise PlanningInputError("asset class ids must be unique")
    means = [_num_field(a, "expectedReturn") for a in asset_classes]
    vols = [_num_field(a, "volatility") for a in asset_classes]
    lambdas = [
        float(a["lambda"]) if isinstance(a.get("lambda"), (int, float)) else 0.0
        for a in asset_classes
    ]
    weights, _total = _blended_weights(body.get("accounts"), asset_ids)
    accounts = body["accounts"]  # validated by _blended_weights above
    balances: dict[str, float] = {}
    for acct in accounts:
        balances[acct["type"]] = balances.get(acct["type"], 0.0) + float(acct["balance"])
    regime = to_generic_regime(regime_engine.classify().regime)
    try:
        return portfolio_xray(
            asset_ids=asset_ids,
            weights=weights,
            means=means,
            vols=vols,
            lambdas=lambdas,
            account_balances=balances,
            regime=regime,
        )
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
        volatility = (
            statistics.pstdev(returns) * math.sqrt(_TRADING_DAYS) if len(returns) > 1 else 0.0
        )
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


def _num_field(asset: dict[str, Any], key: str) -> float:
    value = asset.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanningInputError(f"assetClass '{asset.get('id')}' field '{key}' must be a number")
    return float(value)


def _blended_weights(accounts: Any, asset_ids: list[str]) -> tuple[list[float], float]:
    """Validate accounts and return (blended portfolio weights, total balance)."""
    if not isinstance(accounts, list) or not accounts:
        raise PlanningInputError("accounts must be a non-empty list")
    id_set = set(asset_ids)
    weighted = dict.fromkeys(asset_ids, 0.0)
    total = 0.0
    for acct in accounts:
        if not isinstance(acct, dict):
            raise PlanningInputError("each account must be an object")
        balance = acct.get("balance")
        if isinstance(balance, bool) or not isinstance(balance, (int, float)) or balance < 0:
            raise PlanningInputError("account balance must be a non-negative number")
        allocation = acct.get("allocation")
        if not isinstance(allocation, dict) or not allocation:
            raise PlanningInputError("account allocation must be a non-empty object")
        weight_sum = 0.0
        for asset_id, weight in allocation.items():
            if asset_id not in id_set:
                raise PlanningInputError(
                    f"account allocation references undeclared asset class '{asset_id}'"
                )
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise PlanningInputError("allocation weights must be numbers")
            weight_sum += weight
            weighted[asset_id] += float(balance) * float(weight)
        if abs(weight_sum - 1.0) > 1e-6:
            raise PlanningInputError(
                f"allocation for {acct.get('type')} account sums to {weight_sum:.4f}, must sum to 1"
            )
        total += float(balance)
    if total <= 0:
        raise PlanningInfeasibleError("total portfolio balance must be positive")
    return [weighted[aid] / total for aid in asset_ids], total


def _net_spend_schedule(
    *,
    current_age: int,
    retirement_age: int,
    years: int,
    annual_spend: float,
    spend_cola: float,
    body: dict[str, Any],
) -> list[float]:
    """Per-year net withdrawal: 0 while accumulating (age < retirementAge), then
    COLA-grown spend minus active guaranteed income once decumulating."""
    incomes = body.get("guaranteedIncome", [])
    if not isinstance(incomes, list):
        raise PlanningInputError("guaranteedIncome must be a list")
    parsed: list[tuple[float, int, float]] = []
    for income in incomes:
        if not isinstance(income, dict):
            raise PlanningInputError("each guaranteedIncome must be an object")
        amount = income.get("annualAmount")
        start = income.get("startAge")
        cola = income.get("colaRate", 0.0)
        if (
            isinstance(amount, bool)
            or not isinstance(amount, (int, float))
            or isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(cola, bool)
            or not isinstance(cola, (int, float))
        ):
            raise PlanningInputError(
                "guaranteedIncome needs numeric annualAmount, integer startAge, numeric colaRate"
            )
        parsed.append((float(amount), start, float(cola)))

    schedule: list[float] = []
    for year in range(years):
        age = current_age + year
        if age < retirement_age:
            schedule.append(0.0)  # accumulation: portfolio grows untouched
            continue
        spend = annual_spend * (1.0 + spend_cola) ** year
        income_total = sum(
            amount * (1.0 + cola) ** (age - start) for amount, start, cola in parsed if age >= start
        )
        schedule.append(spend - income_total)
    return schedule


def _build_correlation(
    body: dict[str, Any], asset_ids: list[str], market: MarketDataProvider
) -> list[list[float]]:
    """Use the client's correlations if given, else self-estimate via the same
    Ledoit-Wolf estimator correlation_matrix exposes (proxy-mapped ids only;
    unmapped ids default to uncorrelated)."""
    provided = body.get("correlations")
    if isinstance(provided, dict):
        return [
            [1.0 if a == b else float(provided.get(a, {}).get(b, 0.0)) for b in asset_ids]
            for a in asset_ids
        ]
    if provided is not None:
        raise PlanningInputError("correlations must be an object or null")

    estimated: dict[str, dict[str, float]] = {}
    proxies = proxy_tickers()
    mapped = {aid: proxies[aid] for aid in asset_ids if aid in proxies}
    if len(mapped) >= 2:
        try:
            returns_by_id, _ = _fetch_aligned_returns(
                market, mapped, lookback=_DEFAULT_LOOKBACK_DAYS
            )
            estimated = correlation_matrix(returns_by_id, shrinkage=True)
        except PlanningInfeasibleError:
            estimated = {}
    return [
        [1.0 if a == b else float(estimated.get(a, {}).get(b, 0.0)) for b in asset_ids]
        for a in asset_ids
    ]


def _monte_carlo_decumulation_tool(
    body: dict[str, Any], market: MarketDataProvider, regime_engine: RegimeEngine
) -> dict[str, Any]:
    """``monte_carlo_decumulation`` — the primary decumulation simulation."""
    current_age = _as_int(body, "currentAge")
    horizon_age = _as_int(body, "horizonAge")
    if not 0 < current_age < horizon_age <= 120:
        raise PlanningInputError("ages must satisfy 0 < currentAge < horizonAge <= 120")
    years = horizon_age - current_age

    return_model = _as_str(body, "returnModel")
    if return_model not in _RETURN_MODELS:
        raise PlanningInputError(f"returnModel must be one of {', '.join(_RETURN_MODELS)}")

    asset_classes = _validate_asset_classes(body, require_lambda=return_model == "emf_regime")
    asset_ids = [str(a["id"]) for a in asset_classes]
    if len(set(asset_ids)) != len(asset_ids):
        raise PlanningInputError("asset class ids must be unique")
    means = [_num_field(a, "expectedReturn") for a in asset_classes]
    vols = [_num_field(a, "volatility") for a in asset_classes]
    if any(v < 0 for v in vols):
        raise PlanningInputError("asset volatility must be non-negative")
    lambdas = [
        float(a.get("lambda", 0.0)) if isinstance(a.get("lambda"), (int, float)) else 0.0
        for a in asset_classes
    ]

    # Optional retirementAge: the portfolio accumulates untouched until then,
    # then decumulates. Omitted ⇒ currentAge (withdraw from the start).
    retirement_age = body.get("retirementAge")
    if retirement_age is None:
        retirement_age = current_age
    elif (
        isinstance(retirement_age, bool)
        or not isinstance(retirement_age, int)
        or not current_age <= retirement_age <= horizon_age
    ):
        raise PlanningInputError(
            "retirementAge must be an integer with currentAge <= retirementAge <= horizonAge"
        )

    weights, initial_balance = _blended_weights(body.get("accounts"), asset_ids)
    annual_spend = _as_number(body, "annualSpend")
    if annual_spend < 0:
        raise PlanningInputError("annualSpend must be non-negative")
    spend_cola = body.get("spendColaRate", 0.0)
    if isinstance(spend_cola, bool) or not isinstance(spend_cola, (int, float)):
        raise PlanningInputError("spendColaRate must be a number")
    net_spend = _net_spend_schedule(
        current_age=current_age,
        retirement_age=retirement_age,
        years=years,
        annual_spend=annual_spend,
        spend_cola=float(spend_cola),
        body=body,
    )

    paths = body.get("paths", 10000)
    if isinstance(paths, bool) or not isinstance(paths, int) or not 1 <= paths <= _MC_MAX_PATHS:
        raise PlanningInputError(f"paths must be an integer in [1, {_MC_MAX_PATHS}]")

    correlation = _build_correlation(body, asset_ids, market)
    seed_used = _resolve_seed(body)
    cache_seed = seed_from_cache_key(body.get("pathCacheKey"))
    regime_seed = cache_seed if cache_seed is not None else seed_used
    current_regime = "expansion"
    if return_model == "emf_regime":
        current_regime = to_generic_regime(regime_engine.classify().regime)

    return monte_carlo_decumulation(
        years=years,
        weights=weights,
        means=means,
        vols=vols,
        lambdas=lambdas,
        correlation=correlation,
        initial_balance=initial_balance,
        net_spend_by_year=net_spend,
        return_model=return_model,
        paths=paths,
        seed=seed_used,
        regime_seed=regime_seed,
        current_regime=current_regime,
    )


def _opt_num(body: dict[str, Any], key: str, default: float) -> float:
    if key not in body or body[key] is None:
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanningInputError(f"field '{key}' must be a number")
    return float(value)


def _resolve_engine_filing_status(raw: Any) -> FilingStatus:
    """Accept the contract codes (single/mfj/mfs) or the engine's own statuses."""
    if not isinstance(raw, str):
        raise PlanningInputError("filing_status must be a string")
    if raw in ("single", "mfj", "mfs"):
        return engine_filing_status(cast("Any", raw))
    if raw in ("married_joint", "married_separate", "head_of_household"):
        return cast(FilingStatus, raw)
    raise PlanningInputError("filing_status must be one of single/mfj/mfs")


def irmaa_headroom_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``irmaa_headroom`` — room before the next projected Medicare IRMAA cliff."""
    try:
        raw_table = body.get("irmaa_table")
        if raw_table is not None:
            table = IrmaaTable.from_dict(raw_table)
        else:
            fs = _resolve_engine_filing_status(body.get("filing_status", "single"))
            source_year = body.get("source_year", 2025)
            if isinstance(source_year, bool) or not isinstance(source_year, int):
                raise PlanningInputError("source_year must be an integer")
            table = reference_irmaa_table(fs, source_year=source_year)
        result = irmaa_headroom(
            table=table,
            target_premium_year=_as_int(body, "target_premium_year"),
            magi_ex_conversion=_as_number(body, "magi_ex_conversion"),
            per_person=_as_int(body, "per_person"),
            inflation=_as_number(body, "inflation"),
            buffer=_as_number(body, "buffer"),
        )
    except TableError as exc:
        raise PlanningInputError(str(exc)) from exc
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc
    return asdict(result)


def _parse_contract(body: dict[str, Any]) -> PlanningContract:
    raw = body.get("contract")
    if not isinstance(raw, dict):
        raise PlanningInputError("'contract' (a PlanningContract object) is required")
    try:
        return PlanningContract.from_dict(raw)
    except PlanningContractError as exc:
        raise PlanningInputError(str(exc)) from exc


def _resolve_tables(
    body: dict[str, Any], contract: PlanningContract
) -> tuple[BracketTable, IrmaaTable, StateConversionRule | None, str, str, str]:
    """Use caller-injected tables when present, else the engine reference set."""
    try:
        if body.get("bracket_table") is not None:
            bt, bt_src = BracketTable.from_dict(body["bracket_table"]), "caller_provided"
        else:
            bt, bt_src = reference_bracket_table(contract.tax_year), "engine_reference"
        if body.get("irmaa_table") is not None:
            it, it_src = IrmaaTable.from_dict(body["irmaa_table"]), "caller_provided"
        else:
            it, it_src = reference_irmaa_table(contract.engine_filing_status), "engine_reference"
        if body.get("state_rule") is not None:
            sr: StateConversionRule | None = StateConversionRule.from_dict(body["state_rule"])
            sr_src = "caller_provided"
        else:
            sr, sr_src = reference_state_rule(contract.state_code), "engine_reference"
    except TableError as exc:
        raise PlanningInputError(str(exc)) from exc
    return bt, it, sr, bt_src, it_src, sr_src


def _resolve_aca(body: dict[str, Any]) -> AcaSituation | None:
    """Parse an optional injected ACA situation; ``None`` ⇒ ACA cliff stays a note."""
    raw = body.get("aca")
    if raw is None:
        return None
    try:
        return AcaSituation.from_dict(raw)
    except (TableError, KeyError, TypeError, ValueError) as exc:
        raise PlanningInputError(f"invalid 'aca': {exc}") from exc


def analyze_roth_conversion_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``analyze_roth_conversion`` — composite multi-year Roth/IRMAA analysis."""
    contract = _parse_contract(body)
    bt, it, sr, bt_src, it_src, sr_src = _resolve_tables(body, contract)
    result = analyze_roth_conversion(
        contract,
        irmaa_table=it,
        bracket_table=bt,
        state_rule=sr,
        aca=_resolve_aca(body),
        irmaa_inflation=_opt_num(body, "irmaa_inflation", 0.03),
        irmaa_buffer=_opt_num(body, "irmaa_buffer", 5_000.0),
        growth_rate=_opt_num(body, "growth_rate", 0.05),
        bracket_table_source=bt_src,
        irmaa_table_source=it_src,
        state_rule_source=sr_src,
    )
    return asdict(result)


def sequence_conversions_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``sequence_conversions`` — the multi-year split roll-up only."""
    contract = _parse_contract(body)
    bt, it, sr, _bt_src, _it_src, _sr_src = _resolve_tables(body, contract)
    result = sequence_conversions(
        contract,
        irmaa_table=it,
        bracket_table=bt,
        state_rule=sr,
        aca=_resolve_aca(body),
        irmaa_inflation=_opt_num(body, "irmaa_inflation", 0.03),
        irmaa_buffer=_opt_num(body, "irmaa_buffer", 5_000.0),
        growth_rate=_opt_num(body, "growth_rate", 0.05),
    )
    return asdict(result)


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

    def monte_carlo_decumulation_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _monte_carlo_decumulation_tool(body, market, regime_engine)

    def regime_conditioned_swr_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _regime_conditioned_swr_tool(body, regime_engine)

    def portfolio_xray_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _portfolio_xray_tool(body, regime_engine)

    return {
        "monte_carlo_decumulation": monte_carlo_decumulation_tool,
        "glide_path": glide_path_tool,
        "tax_aware_withdrawal": tax_aware_withdrawal_tool,
        "correlation_matrix": correlation_matrix_tool,
        "capital_market_assumptions": capital_market_assumptions_tool,
        "regime_return_generator": regime_return_generator_tool,
        "roth_conversion": roth_conversion_tool,
        "sequence_of_returns_stress": sequence_of_returns_stress_tool,
        "rmd": rmd_tool,
        "tax_bracket_headroom": tax_bracket_headroom_tool,
        "social_security_claiming": social_security_claiming_tool,
        "regime_conditioned_swr": regime_conditioned_swr_tool,
        "portfolio_xray": portfolio_xray_tool,
        "fire": fire_tool,
        "risk_metrics": risk_metrics_tool,
        "rebalance": rebalance_tool,
        "irmaa_headroom": irmaa_headroom_tool,
        "analyze_roth_conversion": analyze_roth_conversion_tool,
        "sequence_conversions": sequence_conversions_tool,
    }


__all__ = [
    "ToolHandler",
    "analyze_roth_conversion_tool",
    "build_tool_handlers",
    "fire_tool",
    "glide_path_tool",
    "irmaa_headroom_tool",
    "sequence_conversions_tool",
    "rebalance_tool",
    "risk_metrics_tool",
    "rmd_tool",
    "roth_conversion_tool",
    "sequence_of_returns_stress_tool",
    "social_security_claiming_tool",
    "tax_aware_withdrawal_tool",
    "tax_bracket_headroom_tool",
]
