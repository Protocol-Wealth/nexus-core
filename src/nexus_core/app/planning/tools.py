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
from dataclasses import asdict, dataclass
from typing import Any, cast

from ...data.providers import MarketDataProvider
from ...disclaimers import FULL
from ...engine.planning import (
    Direction,
    GlidePathShape,
    GuardrailParams,
    InfeasiblePlanError,
    SolveResult,
    analyze_goals,
    analyze_roth_conversion,
    bracket_headroom,
    compute_glide_path,
    correlation_matrix,
    fire,
    irmaa_headroom,
    monte_carlo_decumulation,
    portfolio_xray,
    project_cash_flow,
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
    solve_integer_monotone,
    solve_monotone,
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
from .report import assemble_report
from .universe import ASSET_UNIVERSE, proxy_tickers, universe_ids

_MAX_SEED = 2**31 - 1
_MC_MAX_PATHS = 50000
# DoS bounds (SECURITY-AUDIT-2026-06-09 H8): the public, unauthenticated
# monte_carlo surface allocated a (paths, years, n_assets) float64 array and
# ran O(n^2) correlation + O(n^3) Cholesky on an UNBOUNDED asset count, so a
# tiny request body amplified to a multi-GB allocation. Cap the asset count
# (bounds n for every tool that builds a correlation matrix) and bound the
# combined simulation-array cell count.
_MAX_ASSET_CLASSES = 64
_MC_MAX_CELLS = 50_000_000  # paths * years * n_assets float64 -> <= ~400 MB
_RETURN_MODELS = (
    "multivariate_normal",
    "student_t",
    "block_bootstrap",
    "markov_regime",
    "emf_regime",
)
_SPEND_SCHEDULE_MODES = frozenset({"delta", "override", "one_time"})

# ── Goal solver (solve_goal) ─────────────────────────────────────────────────
# A fixed seed pins the success curve across search iterations (an unseeded MC
# redraws paths each call → a noisy curve that makes bisection oscillate); it
# mirrors the pinned SOLVE_SEED the prior BFF-side spend solver used.
_SOLVE_SEED = 4242421
# Reduced paths during the search; one full-paths confirmation runs at the
# solved value (the full run is the authoritative reported success).
_SOLVE_PATHS = 2000
_SOLVE_FOR = (
    "annual_spend",
    "annual_contribution",
    "savings_rate",
    "retirement_age",
    "initial_savings",
)


@dataclass(frozen=True)
class _SpendScheduleEntry:
    mode: str
    start_age: int
    end_age: int
    amount: float
    cola_rate: float

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
        # Key by calendar DATE (not the full timestamp). Asset classes route to
        # different providers whose daily-bar timestamps differ in format and
        # time-of-day (a crypto source emits "...T00:00:00Z"; an equity source
        # emits a bare date or a market-close time). A full-timestamp
        # set-intersection then shares almost no keys, so mixing BTC-USD with
        # NYSE ETFs — and the default universe, which includes bitcoin — raised
        # "not enough overlapping dates". Date-keying aligns on common trading
        # days (crypto weekends simply fall out against the equity calendar).
        closes = {b.timestamp[:10]: float(b.close) for b in bars if b.close and b.close > 0}
        if as_of is not None:
            closes = {d: c for d, c in closes.items() if d <= as_of}
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


#: ``analyze_goals`` wire field (camelCase) → engine field (snake_case). The
#: wire contract is identity-free: NO free-text label — only an opaque ``id``,
#: the enum ``kind``, and numbers. The consumer re-attaches labels by id.
_GOAL_FIELD_MAP = {
    "id": "id",
    "kind": "kind",
    "targetAmount": "target_amount",
    "yearsToGoal": "years_to_goal",
    "currentAssets": "current_assets",
    "monthlyContribution": "monthly_contribution",
    "priority": "priority",
    "fundingYears": "funding_years",
    "inflationRate": "inflation_rate",
    "expectedReturn": "expected_return",
}

_MAX_GOALS = 100


def analyze_goals_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``analyze_goals`` — per-goal funding status + a present-value aggregate."""
    raw_goals = _require(body, "goals")
    if not isinstance(raw_goals, list) or not raw_goals:
        raise PlanningInputError("goals must be a non-empty list")
    if len(raw_goals) > _MAX_GOALS:
        raise PlanningInputError(f"at most {_MAX_GOALS} goals are supported")
    goals: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_goals):
        if not isinstance(raw, dict):
            raise PlanningInputError(f"goals[{index}] must be an object")
        kind = raw.get("kind")
        if kind is not None and (not isinstance(kind, str) or not kind):
            raise PlanningInputError(f"goals[{index}].kind must be a non-empty string")
        translated: dict[str, Any] = {}
        for wire_key, engine_key in _GOAL_FIELD_MAP.items():
            if wire_key in raw and raw[wire_key] is not None:
                translated[engine_key] = raw[wire_key]
        goals.append(translated)

    default_inflation = body.get("defaultInflationRate", 0.025)
    if isinstance(default_inflation, bool) or not isinstance(default_inflation, (int, float)):
        raise PlanningInputError("defaultInflationRate must be a number or omitted")
    default_return = body.get("defaultExpectedReturn", 0.05)
    if isinstance(default_return, bool) or not isinstance(default_return, (int, float)):
        raise PlanningInputError("defaultExpectedReturn must be a number or omitted")
    shared_pool = body.get("sharedFundingPool")
    translated_shared_pool: dict[str, Any] | None = None
    if shared_pool is not None:
        if not isinstance(shared_pool, dict):
            raise PlanningInputError("sharedFundingPool must be an object")
        translated_shared_pool = {}
        for wire_key, engine_key in (
            ("currentAssets", "current_assets"),
            ("monthlyContribution", "monthly_contribution"),
        ):
            if wire_key in shared_pool and shared_pool[wire_key] is not None:
                translated_shared_pool[engine_key] = shared_pool[wire_key]

    try:
        return analyze_goals(
            goals=goals,
            default_inflation_rate=float(default_inflation),
            default_expected_return=float(default_return),
            shared_funding_pool=translated_shared_pool,
        )
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc


def _optional_number(body: dict[str, Any], key: str, default: float) -> float:
    """A numeric field that defaults when omitted; rejects non-numbers."""
    value = body.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanningInputError(f"{key} must be a number or omitted")
    return float(value)


def project_cash_flow_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``project_cash_flow`` — year-by-year cash flow + net worth + lifetime tax."""
    filing_status = body.get("filingStatus", "married_joint")
    if not isinstance(filing_status, str):
        raise PlanningInputError("filingStatus must be a string or omitted")
    base_year = body.get("baseYear")
    if base_year is not None and (isinstance(base_year, bool) or not isinstance(base_year, int)):
        raise PlanningInputError("baseYear must be an integer or omitted")
    try:
        return project_cash_flow(
            current_age=_as_int(body, "currentAge"),
            retirement_age=_as_int(body, "retirementAge"),
            terminal_age=_as_int(body, "terminalAge"),
            current_income=_as_number(body, "currentIncome"),
            current_expenses=_as_number(body, "currentExpenses"),
            current_portfolio=_as_number(body, "currentPortfolio"),
            filing_status=cast(Any, filing_status),
            income_growth_rate=_optional_number(body, "incomeGrowthRate", 0.03),
            expense_inflation_rate=_optional_number(body, "expenseInflationRate", 0.025),
            expected_return=_optional_number(body, "expectedReturn", 0.05),
            retirement_income=_optional_number(body, "retirementIncome", 0.0),
            current_liabilities=_optional_number(body, "currentLiabilities", 0.0),
            base_year=base_year,
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


#: ``riskProfile`` → mean-variance risk-aversion (lambda) for max_quadratic_utility.
#: Higher lambda penalizes variance more (conservative, bond-tilted); lower
#: tolerates it (aggressive, return-tilted). Monotonic across the efficient frontier.
RISK_AVERSION_BY_PROFILE: dict[str, float] = {
    "conservative": 8.0,
    "moderate_conservative": 5.0,
    "moderate": 3.0,
    "moderate_aggressive": 1.75,
    "aggressive": 1.0,
}

#: Objectives the moments-driven allocator accepts (mirrors MOMENT_OBJECTIVES;
#: kept local so importing tools.py never imports the optimization package).
_ALLOCATION_OBJECTIVES = frozenset(
    {"max_sharpe", "min_volatility", "max_quadratic_utility", "efficient_return", "efficient_risk"}
)


def _resolve_allocation_universe(body: dict[str, Any]) -> list[str]:
    """Validate ``assetClassIds`` (default = full universe) for the allocator."""
    raw_ids = body.get("assetClassIds")
    if raw_ids is None or raw_ids == []:
        ids = universe_ids()
    elif isinstance(raw_ids, list) and all(isinstance(x, str) for x in raw_ids):
        ids = raw_ids
    else:
        raise PlanningInputError("assetClassIds must be a list of strings (or omitted)")
    if len(set(ids)) != len(ids):
        raise PlanningInputError("assetClassIds must be unique")
    unknown = [i for i in ids if i not in ASSET_UNIVERSE]
    if unknown:
        raise PlanningInputError(
            f"unknown asset class id(s): {', '.join(unknown)}. "
            f"Known asset classes: {', '.join(universe_ids())}."
        )
    if len(ids) < 2:
        raise PlanningInputError("optimize_allocation needs at least 2 asset classes")
    if len(ids) > _MAX_ASSET_CLASSES:
        raise PlanningInputError(f"at most {_MAX_ASSET_CLASSES} asset classes are supported")
    return ids


def _resolve_weight_bounds(body: dict[str, Any], n_assets: int) -> tuple[float, float]:
    """Validate optional ``weightBounds`` ([min, max]); default (0, 1)."""
    raw = body.get("weightBounds")
    if raw is None:
        return (0.0, 1.0)
    if (
        not isinstance(raw, list)
        or len(raw) != 2
        or any(isinstance(b, bool) or not isinstance(b, (int, float)) for b in raw)
    ):
        raise PlanningInputError("weightBounds must be a [min, max] pair of numbers")
    lo, hi = float(raw[0]), float(raw[1])
    if not 0.0 <= lo <= hi <= 1.0:
        raise PlanningInputError("weightBounds must satisfy 0 <= min <= max <= 1")
    if hi * n_assets < 1.0:
        raise PlanningInfeasibleError(
            f"weightBounds upper bound {hi} is too low for {n_assets} assets "
            f"(a fully-invested portfolio needs an upper bound >= {1.0 / n_assets:.3f})"
        )
    if lo * n_assets > 1.0:
        raise PlanningInfeasibleError(
            f"weightBounds lower bound {lo} is too high for {n_assets} assets "
            f"(the minimum weights already exceed 100%; need a lower bound <= {1.0 / n_assets:.3f})"
        )
    return (lo, hi)


def _resolve_allocation_objective(
    body: dict[str, Any], live_regime: str, regime_optimizer_map: dict[str, str]
) -> tuple[str, str, float, float | None, float | None]:
    """Resolve (objective, source, riskAversion, targetReturn, targetVolatility).

    Precedence: explicit ``objective`` > ``riskProfile`` > (``regimeAware`` ⇒
    regime-selected) > ``max_sharpe``. ``riskProfile`` maps to
    ``max_quadratic_utility`` at the profile's risk-aversion.
    """
    objective = body.get("objective")
    risk_profile = body.get("riskProfile")
    risk_aversion = 1.0
    target_return: float | None = None
    target_volatility: float | None = None

    if objective is not None:
        if risk_profile is not None:
            raise PlanningInputError("pass either objective or riskProfile, not both")
        if not isinstance(objective, str) or objective not in _ALLOCATION_OBJECTIVES:
            raise PlanningInputError(
                f"objective must be one of {sorted(_ALLOCATION_OBJECTIVES)}"
            )
        if objective == "max_quadratic_utility":
            ra = body.get("riskAversion", 3.0)
            if isinstance(ra, bool) or not isinstance(ra, (int, float)) or ra <= 0:
                raise PlanningInputError("riskAversion must be a positive number")
            risk_aversion = float(ra)
        elif objective == "efficient_return":
            target_return = _as_number(body, "targetReturn")
        elif objective == "efficient_risk":
            target_volatility = _as_number(body, "targetVolatility")
        return objective, "explicit", risk_aversion, target_return, target_volatility

    if risk_profile is not None:
        if not isinstance(risk_profile, str) or risk_profile not in RISK_AVERSION_BY_PROFILE:
            raise PlanningInputError(
                f"riskProfile must be one of {sorted(RISK_AVERSION_BY_PROFILE)}"
            )
        return (
            "max_quadratic_utility",
            "riskProfile",
            RISK_AVERSION_BY_PROFILE[risk_profile],
            None,
            None,
        )

    regime_aware = body.get("regimeAware", True)
    if not isinstance(regime_aware, bool):
        raise PlanningInputError("regimeAware must be a boolean")
    if regime_aware:
        selected = regime_optimizer_map.get(live_regime, "max_sharpe")
        # The regime map may select 'hrp' (TRANSITION); HRP has no moments-only
        # form, so fall back to its risk-robust intent: min_volatility.
        if selected not in _ALLOCATION_OBJECTIVES:
            selected = "min_volatility"
        return selected, "regime", risk_aversion, None, None
    return "max_sharpe", "default", risk_aversion, None, None


def _finite_round(value: float | None, ndigits: int) -> float | None:
    """Round a metric; coerce ``None`` and non-finite (inf/nan) to ``None``.

    A degenerate input (e.g. a zero-volatility asset) can drive Sharpe to ±inf.
    ``inf``/``nan`` are not JSON-compliant and would crash the response renderer
    outside the gateway's error mapping, so normalize them to ``null`` here.
    """
    if value is None or not math.isfinite(value):
        return None
    return round(value, ndigits)


def _optimize_allocation_tool(
    body: dict[str, Any], market: MarketDataProvider, regime_engine: RegimeEngine
) -> dict[str, Any]:
    """``optimize_allocation`` — optimizer-driven target asset-class weights.

    Composes the engine's capital-market assumptions — forward house-view returns
    (or a ``historical`` mean), real-data volatility, and a Ledoit-Wolf-shrunk
    correlation matrix — into a mean-variance optimization, returning target
    weights per asset class. Driven by a ``riskProfile`` (mapped to a
    mean-variance risk-aversion), an explicit ``objective``, or — by default — an
    objective selected for the LIVE macro regime. Educational illustration only,
    not investment advice or a recommendation.
    """
    from ...engine.optimization import REGIME_OPTIMIZER_MAP, optimize_from_moments

    ids = _resolve_allocation_universe(body)

    return_model = body.get("returnModel", "house_view")
    if return_model not in ("house_view", "historical"):
        raise PlanningInputError("returnModel must be 'house_view' or 'historical'")

    lookback = body.get("lookbackDays", _DEFAULT_LOOKBACK_DAYS)
    if (
        isinstance(lookback, bool)
        or not isinstance(lookback, int)
        or not _MIN_LOOKBACK_DAYS <= lookback <= _MAX_LOOKBACK_DAYS
    ):
        raise PlanningInputError(
            f"lookbackDays must be an integer in [{_MIN_LOOKBACK_DAYS}, {_MAX_LOOKBACK_DAYS}]"
        )

    as_of = body.get("asOf")
    if as_of is not None and not isinstance(as_of, str):
        raise PlanningInputError("asOf must be an ISO date string (or omitted)")

    rf = body.get("riskFreeRate", 0.045)
    if isinstance(rf, bool) or not isinstance(rf, (int, float)):
        raise PlanningInputError("riskFreeRate must be a number or omitted")
    rf = float(rf)

    weight_bounds = _resolve_weight_bounds(body, len(ids))

    raw_regime = regime_engine.classify().regime
    live_regime = str(getattr(raw_regime, "value", raw_regime))
    objective, objective_source, risk_aversion, target_return, target_volatility = (
        _resolve_allocation_objective(body, live_regime, dict(REGIME_OPTIMIZER_MAP))
    )

    tickers = {i: ASSET_UNIVERSE[i].ticker for i in ids}
    returns_by_id, resolved_as_of = _fetch_aligned_returns(
        market, tickers, lookback=lookback, as_of=as_of
    )

    vol_by_id: dict[str, float] = {}
    for asset_id in ids:
        series = returns_by_id[asset_id]
        vol_by_id[asset_id] = (
            statistics.pstdev(series) * math.sqrt(_TRADING_DAYS) if len(series) > 1 else 0.0
        )
    # A zero-variance asset can't be risk-optimized: its correlation row is 0/0
    # (NaN) and it would make the covariance singular. Reject it cleanly (422)
    # rather than letting NaN propagate into the solver.
    degenerate = [aid for aid in ids if vol_by_id[aid] <= 0.0]
    if degenerate:
        raise PlanningInfeasibleError(
            "cannot optimize: no price variation (zero estimated volatility) for "
            f"asset class(es): {', '.join(degenerate)}"
        )
    corr = correlation_matrix(returns_by_id, shrinkage=True)
    # Annualized covariance from the published CMA: Sigma_ij = corr_ij * vol_i * vol_j.
    cov = [[corr[ri][ci] * vol_by_id[ri] * vol_by_id[ci] for ci in ids] for ri in ids]

    if return_model == "house_view":
        mu = {i: ASSET_UNIVERSE[i].expected_return for i in ids}
    else:
        # Historical: the mean of daily LOG returns annualizes to a *geometric*
        # (continuously-compounded) drift, but mean-variance optimization expects
        # the *arithmetic* expected return. They differ by ~sigma^2/2, so add the
        # convexity adjustment (vol_by_id is already the annualized stdev, so its
        # square is the annualized variance). Without this, the historical model
        # double-penalizes high-volatility assets.
        mu = {
            i: statistics.fmean(returns_by_id[i]) * _TRADING_DAYS + 0.5 * vol_by_id[i] ** 2
            for i in ids
        }

    try:
        result = optimize_from_moments(
            mu,
            cov,
            ids,
            objective=objective,
            risk_aversion=risk_aversion,
            target_return=target_return,
            target_volatility=target_volatility,
            weight_bounds=weight_bounds,
            risk_free_rate=rf,
        )
    except ImportError as exc:
        raise PlanningInfeasibleError(
            "portfolio optimization requires the optional PyPortfolioOpt dependency "
            "(the [optimization] extra), which this deployment does not have installed."
        ) from exc
    except ValueError as exc:
        raise PlanningInfeasibleError(f"could not solve the allocation: {exc}") from exc

    weights = {aid: round(w, 6) for aid, w in result.weights.items() if abs(w) > 1e-6}
    asset_classes = [
        {
            "id": aid,
            "label": ASSET_UNIVERSE[aid].label,
            "expectedReturn": round(mu[aid], 6),
            "volatility": round(vol_by_id[aid], 6),
            "weight": round(result.weights.get(aid, 0.0), 6),
        }
        for aid in ids
    ]
    payload: dict[str, Any] = {
        "weights": weights,
        "assetClasses": asset_classes,
        "objective": result.method,
        "objectiveSource": objective_source,
        "returnModel": return_model,
        "expectedReturn": _finite_round(result.expected_return, 6),
        "expectedVolatility": _finite_round(result.expected_volatility, 6),
        "sharpeRatio": _finite_round(result.sharpe_ratio, 4),
        "riskFreeRate": rf,
        "weightBounds": list(weight_bounds),
        "regime": live_regime,
        "asOf": resolved_as_of,
    }
    risk_profile = body.get("riskProfile")
    if isinstance(risk_profile, str):
        payload["riskProfile"] = risk_profile
    if objective == "max_quadratic_utility":
        payload["riskAversion"] = risk_aversion
    if objective_source == "regime":
        payload["regimeNote"] = f"Objective '{result.method}' selected for the live regime."
    return payload


_MAX_REPORT_SECTIONS = 40


def _parse_report_section(raw: Any, index: int) -> dict[str, Any]:
    """Validate one report-section input into a clean dict for ``assemble_report``."""
    if not isinstance(raw, dict):
        raise PlanningInputError(f"sections[{index}] must be an object")
    kind = raw.get("kind")
    if not isinstance(kind, str) or not kind:
        raise PlanningInputError(f"sections[{index}].kind must be a non-empty string")
    section: dict[str, Any] = {"kind": kind}

    title = raw.get("title")
    if title is not None:
        if not isinstance(title, str) or not title:
            raise PlanningInputError(f"sections[{index}].title must be a non-empty string")
        section["title"] = title

    data = raw.get("data")
    if data is not None:
        if not isinstance(data, dict):
            raise PlanningInputError(f"sections[{index}].data must be an object")
        section["data"] = data

    for list_field in ("findings", "assumptions"):
        value = raw.get(list_field)
        if value is not None:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise PlanningInputError(
                    f"sections[{index}].{list_field} must be a list of strings"
                )
            section[list_field] = value
    return section


def _build_planning_report_tool(
    body: dict[str, Any], regime_engine: RegimeEngine
) -> dict[str, Any]:
    """``build_planning_report`` — assemble planning tool outputs into a report.

    Takes the (de-identified) outputs of the other planning tools as ``sections``
    and returns one ordered, render-ready report envelope: canonical section
    order, auto-derived findings for recognized section kinds, consolidated
    assumptions, and the comprehensive disclaimer. PII-free — it composes numeric
    tool outputs, never identity. Not a substitute for an advisor's IPS.
    """
    raw_sections = _require(body, "sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise PlanningInputError("sections must be a non-empty list")
    if len(raw_sections) > _MAX_REPORT_SECTIONS:
        raise PlanningInputError(f"at most {_MAX_REPORT_SECTIONS} sections are supported")
    sections = [_parse_report_section(raw, i) for i, raw in enumerate(raw_sections)]

    title = body.get("title", "Planning Analysis Report")
    if not isinstance(title, str) or not title:
        raise PlanningInputError("title must be a non-empty string (or omitted)")

    include_regime = body.get("includeRegime", True)
    if not isinstance(include_regime, bool):
        raise PlanningInputError("includeRegime must be a boolean")
    regime: str | None = None
    if include_regime:
        raw_regime = regime_engine.classify().regime
        regime = str(getattr(raw_regime, "value", raw_regime))

    report = assemble_report(sections, title=title, regime=regime)
    return {"report": report, "disclaimer": FULL}


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
    if len(raw) > _MAX_ASSET_CLASSES:
        raise PlanningInputError(
            f"assetClasses must have at most {_MAX_ASSET_CLASSES} entries"
        )
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


def _as_optional_age(entry: dict[str, Any], key: str, default: int) -> int:
    value = entry.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= 120:
        raise PlanningInputError(f"spendSchedule {key} must be an integer age in [1, 120]")
    return value


def _parse_spend_schedule(body: dict[str, Any]) -> list[_SpendScheduleEntry]:
    """Parse optional gross-spend adjustments.

    ``annualSpend`` remains the base first-year spend grown by ``spendColaRate``.
    Schedule entries modify that gross spend after retirementAge and before
    guaranteed income is netted out:

    - ``delta`` (default): add/subtract a recurring amount over an age range.
    - ``override``: replace gross spend over an age range.
    - ``one_time``: add/subtract once at ``startAge``.
    """
    raw = body.get("spendSchedule", [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PlanningInputError("spendSchedule must be a list")

    parsed: list[_SpendScheduleEntry] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise PlanningInputError("each spendSchedule entry must be an object")
        mode = entry.get("mode", "delta")
        if not isinstance(mode, str) or mode not in _SPEND_SCHEDULE_MODES:
            raise PlanningInputError(
                "spendSchedule mode must be one of delta, override, one_time"
            )
        start_age = _as_optional_age(entry, "startAge", 0)
        end_age = _as_optional_age(entry, "endAge", start_age)
        if end_age < start_age:
            raise PlanningInputError("spendSchedule endAge must be >= startAge")
        amount = entry.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise PlanningInputError("spendSchedule amount must be a number")
        if mode == "override" and amount < 0:
            raise PlanningInputError("spendSchedule override amount must be non-negative")
        cola_rate = entry.get("colaRate", 0.0)
        if isinstance(cola_rate, bool) or not isinstance(cola_rate, (int, float)):
            raise PlanningInputError("spendSchedule colaRate must be a number")
        parsed.append(
            _SpendScheduleEntry(
                mode=mode,
                start_age=start_age,
                end_age=start_age if mode == "one_time" else end_age,
                amount=float(amount),
                cola_rate=float(cola_rate),
            )
        )
    return parsed


def _apply_spend_schedule(
    *,
    base_spend: float,
    age: int,
    entries: list[_SpendScheduleEntry],
) -> float:
    spend = base_spend
    override_seen = False
    for entry in entries:
        if not entry.start_age <= age <= entry.end_age:
            continue
        amount = entry.amount * (1.0 + entry.cola_rate) ** (age - entry.start_age)
        if entry.mode == "override":
            if override_seen:
                raise PlanningInputError("spendSchedule override entries must not overlap")
            spend = amount
            override_seen = True
        else:
            spend += amount
    return spend


def _net_spend_schedule(
    *,
    current_age: int,
    retirement_age: int,
    years: int,
    annual_spend: float,
    spend_cola: float,
    body: dict[str, Any],
    annual_contribution: float = 0.0,
    contribution_cola: float = 0.0,
) -> list[float]:
    """Per-year net withdrawal: 0 while accumulating (age < retirementAge), then
    COLA-grown spend minus active guaranteed income once decumulating.

    ``annual_contribution`` (default 0 — the historical behavior, byte-identical)
    models retirement saving during the accumulation years as a NEGATIVE net draw,
    i.e. a portfolio inflow the decumulation engine adds before growth each year.
    This runs through the real Monte Carlo engine (a negative ``this_w`` is a
    contribution, not a special case) — it is NOT a deterministic approximation.
    """
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

    spend_entries = _parse_spend_schedule(body)
    schedule: list[float] = []
    for year in range(years):
        age = current_age + year
        if age < retirement_age:
            if annual_contribution:
                # Accumulation with saving: a negative net draw = a portfolio inflow.
                schedule.append(-annual_contribution * (1.0 + contribution_cola) ** year)
            else:
                schedule.append(0.0)  # accumulation: portfolio grows untouched
            continue
        spend = annual_spend * (1.0 + spend_cola) ** year
        spend = _apply_spend_schedule(base_spend=spend, age=age, entries=spend_entries)
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


def _parse_guardrails(body: dict[str, Any], *, spend_cola: float) -> GuardrailParams | None:
    """Parse the optional Guyton-Klinger guardrail config; None ⇒ static withdrawal.

    Inflation defaults to the plan's ``spendColaRate`` so a guardrail run inflates
    at the same rate the static plan would, absent an explicit override.
    """
    raw = body.get("guardrails")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PlanningInputError("guardrails must be an object or null")
    if raw.get("rule", "guyton_klinger") != "guyton_klinger":
        raise PlanningInputError("guardrails.rule must be 'guyton_klinger'")
    inflation = _opt_num(raw, "inflation", spend_cola)
    band = _opt_num(raw, "band", 0.20)
    raise_pct = _opt_num(raw, "raise", 0.10)
    cut = _opt_num(raw, "cut", 0.10)
    if not 0.0 < band < 1.0:
        raise PlanningInputError("guardrails.band must be in (0, 1)")
    if not 0.0 <= raise_pct < 1.0 or not 0.0 <= cut < 1.0:
        raise PlanningInputError("guardrails.raise and guardrails.cut must be in [0, 1)")
    if not math.isfinite(inflation):  # NaN/inf would poison the spending bands
        raise PlanningInputError("guardrails.inflation must be finite")
    if inflation < 0.0:
        raise PlanningInputError("guardrails.inflation must be non-negative")
    freeze = raw.get("freezeAfterLoss", True)
    if not isinstance(freeze, bool):
        raise PlanningInputError("guardrails.freezeAfterLoss must be a boolean")
    final_years = raw.get("preservationFinalYears", 15)
    if isinstance(final_years, bool) or not isinstance(final_years, int) or final_years < 0:
        raise PlanningInputError("guardrails.preservationFinalYears must be a non-negative integer")
    return GuardrailParams(
        inflation=inflation,
        band=band,
        raise_pct=raise_pct,
        cut=cut,
        freeze_after_loss=freeze,
        preservation_final_years=final_years,
    )


@dataclass(frozen=True)
class _MonteCarloContext:
    """A parsed, ready-to-run decumulation body.

    Everything the ``monte_carlo_decumulation`` engine needs, parsed ONCE — so the
    goal solver can evaluate many candidate values in-process (rebuilding only the
    per-iteration ``net_spend_by_year`` / ``initial_balance``) without re-parsing,
    re-validating, or re-fetching the (network-bound) correlation matrix. ``body``
    is retained so the solver can rebuild the net-spend schedule against a
    different spend / retirement age / contribution.
    """

    years: int
    current_age: int
    weights: list[float]
    means: list[float]
    vols: list[float]
    lambdas: list[float]
    correlation: list[list[float]]
    return_model: str
    paths: int
    seed: int
    regime_seed: int
    current_regime: str
    retirement_age: int
    annual_spend: float
    spend_cola: float
    initial_balance: float
    net_spend: list[float]
    guardrails: GuardrailParams | None
    body: dict[str, Any]


def _prepare_monte_carlo(
    body: dict[str, Any], market: MarketDataProvider, regime_engine: RegimeEngine
) -> _MonteCarloContext:
    """Parse + validate a decumulation body into a reusable :class:`_MonteCarloContext`.

    This is the full parsing/validation of ``monte_carlo_decumulation`` (identical
    order + messages), factored out so both the tool and the solver share one
    dispatch. The returned context carries the base ``net_spend`` + ``guardrails``
    so the tool runs unchanged; the solver overrides the varied field per iteration.
    """
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
    guardrails = _parse_guardrails(body, spend_cola=float(spend_cola))

    paths = body.get("paths", 10000)
    if isinstance(paths, bool) or not isinstance(paths, int) or not 1 <= paths <= _MC_MAX_PATHS:
        raise PlanningInputError(f"paths must be an integer in [1, {_MC_MAX_PATHS}]")
    # Bound the (paths, years, n_assets) simulation-array allocation (H8).
    if paths * years * len(asset_classes) > _MC_MAX_CELLS:
        raise PlanningInputError(
            "paths * years * assetClasses exceeds the simulation-cell budget; "
            "reduce paths, the horizon, or the number of asset classes"
        )

    correlation = _build_correlation(body, asset_ids, market)
    seed_used = _resolve_seed(body)
    cache_seed = seed_from_cache_key(body.get("pathCacheKey"))
    regime_seed = cache_seed if cache_seed is not None else seed_used
    current_regime = "expansion"
    if return_model == "emf_regime":
        current_regime = to_generic_regime(regime_engine.classify().regime)

    return _MonteCarloContext(
        years=years,
        current_age=current_age,
        weights=weights,
        means=means,
        vols=vols,
        lambdas=lambdas,
        correlation=correlation,
        return_model=return_model,
        paths=paths,
        seed=seed_used,
        regime_seed=regime_seed,
        current_regime=current_regime,
        retirement_age=retirement_age,
        annual_spend=annual_spend,
        spend_cola=float(spend_cola),
        initial_balance=initial_balance,
        net_spend=net_spend,
        guardrails=guardrails,
        body=body,
    )


def _run_monte_carlo(
    ctx: _MonteCarloContext,
    *,
    initial_balance: float,
    net_spend_by_year: list[float],
    paths: int | None = None,
    guardrails: GuardrailParams | None = None,
) -> dict[str, Any]:
    """Run one in-process decumulation over a prepared context.

    Only ``initial_balance`` / ``net_spend_by_year`` (and optionally the path
    count) vary per solver iteration; everything else is reused. The pinned
    ``seed`` + ``regime_seed`` make the success curve smooth across iterations.
    """
    return monte_carlo_decumulation(
        years=ctx.years,
        weights=ctx.weights,
        means=ctx.means,
        vols=ctx.vols,
        lambdas=ctx.lambdas,
        correlation=ctx.correlation,
        initial_balance=initial_balance,
        net_spend_by_year=net_spend_by_year,
        return_model=ctx.return_model,
        paths=ctx.paths if paths is None else paths,
        seed=ctx.seed,
        regime_seed=ctx.regime_seed,
        current_regime=ctx.current_regime,
        current_age=ctx.current_age,
        guardrails=guardrails,
    )


def _mc_success(
    ctx: _MonteCarloContext,
    *,
    initial_balance: float,
    net_spend_by_year: list[float],
    paths: int | None = None,
) -> float:
    """The scalar success probability of one in-process run (the solver evaluate)."""
    result = _run_monte_carlo(
        ctx, initial_balance=initial_balance, net_spend_by_year=net_spend_by_year, paths=paths
    )
    return float(result["successProbability"])


def _monte_carlo_decumulation_tool(
    body: dict[str, Any], market: MarketDataProvider, regime_engine: RegimeEngine
) -> dict[str, Any]:
    """``monte_carlo_decumulation`` — the primary decumulation simulation."""
    ctx = _prepare_monte_carlo(body, market, regime_engine)
    return _run_monte_carlo(
        ctx,
        initial_balance=ctx.initial_balance,
        net_spend_by_year=ctx.net_spend,
        guardrails=ctx.guardrails,
    )


def _total_guaranteed_income(body: dict[str, Any]) -> float:
    """Sum the (year-0 nominal) guaranteed income — a best-effort upper-bound aid.

    Used only to widen the default annual-spend ceiling so the upper bound sits
    safely in the fails-almost-surely region. The schedule builder already
    validated ``guaranteedIncome`` during :func:`_prepare_monte_carlo`.
    """
    incomes = body.get("guaranteedIncome", [])
    if not isinstance(incomes, list):
        return 0.0
    total = 0.0
    for income in incomes:
        if isinstance(income, dict):
            amount = income.get("annualAmount")
            if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                total += float(amount)
    return total


def _default_solve_bounds(solve_for: str, ctx: _MonteCarloContext) -> tuple[float, float]:
    """Sensible per-variable default search bounds when ``bounds`` is omitted."""
    horizon_age = ctx.current_age + ctx.years
    if solve_for == "annual_spend":
        # 0 (always the safest) → a 25%-of-portfolio draw plus all guaranteed
        # income: a withdrawal rate that fails over any real horizon.
        return 0.0, ctx.initial_balance * 0.25 + _total_guaranteed_income(ctx.body)
    if solve_for == "annual_contribution":
        return 0.0, max(ctx.annual_spend, ctx.initial_balance * 0.25, 10_000.0)
    if solve_for == "savings_rate":
        return 0.0, 1.0
    if solve_for == "retirement_age":
        return float(ctx.current_age), float(horizon_age)
    # initial_savings: 0 → enough capital that the plan is almost surely funded.
    return 0.0, max(ctx.initial_balance * 3.0, ctx.annual_spend * ctx.years, 100_000.0)


def _parse_solve_bounds(
    body: dict[str, Any], solve_for: str, ctx: _MonteCarloContext
) -> tuple[float, float]:
    """Resolve the search bounds — caller-supplied ``bounds`` or per-variable defaults."""
    default_lo, default_hi = _default_solve_bounds(solve_for, ctx)
    raw = body.get("bounds")
    if raw is None:
        return default_lo, default_hi
    if not isinstance(raw, dict):
        raise PlanningInputError("bounds must be an object or null")
    lo = _opt_num(raw, "min", default_lo)
    hi = _opt_num(raw, "max", default_hi)
    if not hi > lo:
        raise PlanningInputError("bounds.max must be greater than bounds.min")
    if solve_for == "retirement_age":
        if lo != int(lo) or hi != int(hi):
            raise PlanningInputError("bounds for retirement_age must be whole ages")
        if lo < ctx.current_age or hi > ctx.current_age + ctx.years:
            raise PlanningInputError(
                "retirement_age bounds must satisfy currentAge <= min < max <= horizonAge"
            )
    elif solve_for == "savings_rate":
        if lo < 0.0 or hi > 1.0:
            raise PlanningInputError("savings_rate bounds must lie within [0, 1]")
    elif lo < 0.0:
        raise PlanningInputError("bounds.min must be non-negative")
    return lo, hi


def _schedule_for(
    ctx: _MonteCarloContext,
    *,
    annual_spend: float | None = None,
    retirement_age: int | None = None,
    annual_contribution: float = 0.0,
) -> list[float]:
    """Rebuild the net-spend schedule with one field overridden (cheap; no network)."""
    return _net_spend_schedule(
        current_age=ctx.current_age,
        retirement_age=ctx.retirement_age if retirement_age is None else retirement_age,
        years=ctx.years,
        annual_spend=ctx.annual_spend if annual_spend is None else annual_spend,
        spend_cola=ctx.spend_cola,
        body=ctx.body,
        annual_contribution=annual_contribution,
    )


def _round_solve_x(solve_for: str, x: float) -> float | int:
    if solve_for == "retirement_age":
        return int(round(x))
    if solve_for == "savings_rate":
        return round(x, 4)
    return round(x, 2)


def _solve_goal_variable(
    ctx: _MonteCarloContext, solve_for: str, *, lo: float, hi: float, target: float
) -> tuple[SolveResult, Direction, Callable[[float], tuple[float, list[float]]]]:
    """Build the per-variable evaluate closure, run the solver, and return the result.

    The returned mapper turns a solved value into the ``(initial_balance,
    net_spend_by_year)`` pair for the full-paths confirmation run.
    """
    solve_paths = min(ctx.paths, _SOLVE_PATHS)

    if solve_for == "annual_spend":
        direction: Direction = "decreasing"

        def spend_inputs(value: float) -> tuple[float, list[float]]:
            return ctx.initial_balance, _schedule_for(ctx, annual_spend=value)

        result = solve_monotone(
            evaluate=lambda x: _mc_success(
                ctx, initial_balance=ctx.initial_balance,
                net_spend_by_year=_schedule_for(ctx, annual_spend=x), paths=solve_paths,
            ),
            lo=lo, hi=hi, target=target, direction=direction,
        )
        return result, direction, spend_inputs

    if solve_for == "annual_contribution":
        direction = "increasing"

        def contrib_inputs(value: float) -> tuple[float, list[float]]:
            return ctx.initial_balance, _schedule_for(ctx, annual_contribution=value)

        result = solve_monotone(
            evaluate=lambda x: _mc_success(
                ctx, initial_balance=ctx.initial_balance,
                net_spend_by_year=_schedule_for(ctx, annual_contribution=x), paths=solve_paths,
            ),
            lo=lo, hi=hi, target=target, direction=direction,
        )
        return result, direction, contrib_inputs

    if solve_for == "savings_rate":
        income = ctx.body.get("annualIncome")
        if isinstance(income, bool) or not isinstance(income, (int, float)) or income <= 0:
            raise PlanningInputError(
                "solveFor 'savings_rate' requires a positive numeric 'annualIncome' in the body"
            )
        income_f = float(income)
        direction = "increasing"

        def rate_inputs(value: float) -> tuple[float, list[float]]:
            return ctx.initial_balance, _schedule_for(ctx, annual_contribution=value * income_f)

        result = solve_monotone(
            evaluate=lambda x: _mc_success(
                ctx, initial_balance=ctx.initial_balance,
                net_spend_by_year=_schedule_for(ctx, annual_contribution=x * income_f),
                paths=solve_paths,
            ),
            lo=lo, hi=hi, target=target, direction=direction,
        )
        return result, direction, rate_inputs

    if solve_for == "retirement_age":
        direction = "increasing"

        def age_inputs(value: float) -> tuple[float, list[float]]:
            return ctx.initial_balance, _schedule_for(ctx, retirement_age=int(round(value)))

        result = solve_integer_monotone(
            evaluate=lambda x: _mc_success(
                ctx, initial_balance=ctx.initial_balance,
                net_spend_by_year=_schedule_for(ctx, retirement_age=int(round(x))),
                paths=solve_paths,
            ),
            lo=int(round(lo)), hi=int(round(hi)),
            target=target, direction=direction,
        )
        return result, direction, age_inputs

    # initial_savings: only the starting balance varies; the schedule is fixed.
    direction = "increasing"

    def balance_inputs(value: float) -> tuple[float, list[float]]:
        return value, ctx.net_spend

    result = solve_monotone(
        evaluate=lambda x: _mc_success(
            ctx, initial_balance=x, net_spend_by_year=ctx.net_spend, paths=solve_paths,
        ),
        lo=lo, hi=hi, target=target, direction=direction,
    )
    return result, direction, balance_inputs


def _solve_goal_tool(
    body: dict[str, Any], market: MarketDataProvider, regime_engine: RegimeEngine
) -> dict[str, Any]:
    """``solve_goal`` — solve one plan variable to a target success probability.

    Parses ``{ solveFor, targetSuccess, bounds?, ...baseMonteCarloBody }``, closes
    an evaluate over the in-process decumulation engine (pinned seed + reduced
    paths during the search), monotone-bisects to the target, then runs ONE
    full-paths confirmation at the solved value. Numbers + enums only — an
    illustration, not advice.
    """
    solve_for = _as_str(body, "solveFor")
    if solve_for not in _SOLVE_FOR:
        raise PlanningInputError(f"solveFor must be one of {', '.join(_SOLVE_FOR)}")
    target = _as_number(body, "targetSuccess")
    if not 0.0 < target <= 1.0:
        raise PlanningInputError("targetSuccess must be a number in (0, 1]")

    # The remaining body is a full monte_carlo_decumulation request. Pin the seed
    # (unless the caller pinned their own) so the success curve is smooth.
    mc_body = {k: v for k, v in body.items() if k not in {"solveFor", "targetSuccess", "bounds"}}
    mc_body.setdefault("seed", _SOLVE_SEED)
    ctx = _prepare_monte_carlo(mc_body, market, regime_engine)

    lo, hi = _parse_solve_bounds(body, solve_for, ctx)
    result, direction, to_inputs = _solve_goal_variable(
        ctx, solve_for, lo=lo, hi=hi, target=target
    )

    # One authoritative confirmation at the solved value, at full paths.
    confirm_balance, confirm_net = to_inputs(result.solved_value)
    confirm = _run_monte_carlo(
        ctx, initial_balance=confirm_balance, net_spend_by_year=confirm_net, paths=ctx.paths
    )
    achieved = round(float(confirm["successProbability"]), 4)

    response: dict[str, Any] = {
        "solveFor": solve_for,
        "targetSuccess": round(target, 4),
        "feasible": result.feasible,
        "solvedValue": _round_solve_x(solve_for, result.solved_value),
        "achievedSuccess": achieved,
        "direction": direction,
        "bounds": {
            "min": _round_solve_x(solve_for, lo),
            "max": _round_solve_x(solve_for, hi),
        },
        "iterations": result.iterations,
        "pathsSearch": min(ctx.paths, _SOLVE_PATHS),
        "pathsConfirm": ctx.paths,
        "seedUsed": ctx.seed,
        "successCurve": [
            {
                "x": _round_solve_x(solve_for, point.x),
                "successProbability": point.success_probability,
            }
            for point in result.success_curve
        ],
        "terminalValues": confirm["terminalValues"],
    }
    if solve_for in ("annual_contribution", "savings_rate"):
        # Accumulation modeled as a real in-engine inflow — an exact run, not an
        # FV approximation. Surfaced as an enum so the method is auditable.
        response["savingsMethod"] = "net_spend_inflow"
    if not result.feasible:
        # Target sits above the achievable ceiling within bounds → the confirmed
        # success at the boundary IS the best this plan can do (never raise).
        response["bestAchievable"] = achieved
    return response


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

    def solve_goal_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _solve_goal_tool(body, market, regime_engine)

    def regime_conditioned_swr_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _regime_conditioned_swr_tool(body, regime_engine)

    def portfolio_xray_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _portfolio_xray_tool(body, regime_engine)

    def optimize_allocation_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _optimize_allocation_tool(body, market, regime_engine)

    def build_planning_report_tool(body: dict[str, Any]) -> dict[str, Any]:
        return _build_planning_report_tool(body, regime_engine)

    return {
        "monte_carlo_decumulation": monte_carlo_decumulation_tool,
        "solve_goal": solve_goal_tool,
        "analyze_goals": analyze_goals_tool,
        "project_cash_flow": project_cash_flow_tool,
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
        "optimize_allocation": optimize_allocation_tool,
        "fire": fire_tool,
        "risk_metrics": risk_metrics_tool,
        "rebalance": rebalance_tool,
        "irmaa_headroom": irmaa_headroom_tool,
        "analyze_roth_conversion": analyze_roth_conversion_tool,
        "sequence_conversions": sequence_conversions_tool,
        "build_planning_report": build_planning_report_tool,
    }


__all__ = [
    "ToolHandler",
    "analyze_goals_tool",
    "analyze_roth_conversion_tool",
    "build_tool_handlers",
    "fire_tool",
    "glide_path_tool",
    "irmaa_headroom_tool",
    "project_cash_flow_tool",
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
