# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Public-safe performance math.

The functions in this module accept only de-identified numeric series: period
values, external-flow amounts, fee rates, and return series. They deliberately
do not accept account names, holdings, symbols, transaction rows, tax lots,
advisor notes, approvals, or audit records.

Cash-flow sign convention for MWR/XIRR is investor perspective: contributions
into the portfolio are negative amounts, withdrawals are positive amounts, and
the terminal value is positive.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

from ...disclaimers import MC_DISCLAIMER

FlowTiming = Literal["start", "end"]

_ROUND = 6
_MAX_RATE = 1_000_000.0


@dataclass(frozen=True, slots=True)
class TwrPeriod:
    start_value: float
    end_value: float
    net_external_flow: float = 0.0


@dataclass(frozen=True, slots=True)
class MwrCashFlow:
    t_years: float
    amount: float


def _round(value: float) -> float:
    return round(value, _ROUND)


def _ensure_finite(value: float, field: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field} values must be finite")


def _validate_periods_per_year(periods_per_year: int) -> None:
    if periods_per_year < 1:
        raise ValueError("periods_per_year must be >= 1")


def _validate_return_series(values: list[float], field: str) -> None:
    if not values:
        raise ValueError(f"{field} must be a non-empty return series")
    for value in values:
        _ensure_finite(value, field)
    if any(r <= -1.0 for r in values):
        raise ValueError(f"{field} values must be > -1")


def _compound_return(returns: list[float]) -> float:
    return float(math.prod(1.0 + r for r in returns) - 1.0)


def _annualized_return(cumulative_return: float, periods: int, periods_per_year: int) -> float:
    if cumulative_return <= -1.0:
        return -1.0
    return float((1.0 + cumulative_return) ** (periods_per_year / periods) - 1.0)


def time_weighted_return(
    *,
    periods: list[TwrPeriod],
    flow_timing: FlowTiming = "start",
    periods_per_year: int = 1,
) -> dict[str, Any]:
    """Geometrically link sub-period returns.

    ``net_external_flow`` is positive for contributions into the portfolio and
    negative for withdrawals. With ``flow_timing="start"`` (default), the flow is
    included in starting capital: ``end / (start + flow) - 1``. With
    ``flow_timing="end"``, the flow is removed from ending value:
    ``(end - flow) / start - 1``.
    """

    if flow_timing not in ("start", "end"):
        raise ValueError("flow_timing must be start or end")
    _validate_periods_per_year(periods_per_year)
    if not periods:
        raise ValueError("periods must be non-empty")

    rows: list[dict[str, Any]] = []
    returns: list[float] = []
    for index, period in enumerate(periods):
        _ensure_finite(period.start_value, "period start value")
        _ensure_finite(period.end_value, "period end value")
        _ensure_finite(period.net_external_flow, "period net external flow")
        if period.start_value < 0.0 or period.end_value < 0.0:
            raise ValueError("period start and end values must be >= 0")
        if flow_timing == "start":
            denominator = period.start_value + period.net_external_flow
            if denominator <= 0.0:
                raise ValueError("start-value plus flow must be > 0 for start-timed TWR")
            period_return = period.end_value / denominator - 1.0
        else:
            if period.start_value <= 0.0:
                raise ValueError("start value must be > 0 for end-timed TWR")
            adjusted_end = period.end_value - period.net_external_flow
            if adjusted_end < 0.0:
                raise ValueError("end-value minus flow must be >= 0 for end-timed TWR")
            period_return = adjusted_end / period.start_value - 1.0

        if period_return < -1.0:
            raise ValueError("sub-period return cannot be less than -100%")
        returns.append(period_return)
        rows.append(
            {
                "period": index,
                "startValue": _round(period.start_value),
                "endValue": _round(period.end_value),
                "netExternalFlow": _round(period.net_external_flow),
                "return": _round(period_return),
            }
        )

    cumulative = _compound_return(returns)
    return {
        "periods": len(periods),
        "periodsPerYear": periods_per_year,
        "flowTiming": flow_timing,
        "periodReturns": rows,
        "cumulativeReturn": _round(cumulative),
        "annualizedReturn": _round(_annualized_return(cumulative, len(periods), periods_per_year)),
    }


def _npv(
    rate: float, flows: list[MwrCashFlow], terminal_value: float, terminal_time: float
) -> float:
    base = 1.0 + rate
    if base <= 0.0:
        raise ValueError("rate must be greater than -100%")
    return float(
        sum(flow.amount / (base**flow.t_years) for flow in flows)
        + terminal_value / (base**terminal_time)
    )


def _npv_derivative(
    rate: float, flows: list[MwrCashFlow], terminal_value: float, terminal_time: float
) -> float:
    base = 1.0 + rate
    return float(
        sum(-flow.t_years * flow.amount / (base ** (flow.t_years + 1.0)) for flow in flows)
        - terminal_time * terminal_value / (base ** (terminal_time + 1.0))
    )


def _cash_flow_sign_changes(
    flows: list[MwrCashFlow], terminal_value: float, terminal_time: float
) -> int:
    events = sorted(
        [(flow.t_years, flow.amount) for flow in flows] + [(terminal_time, terminal_value)]
    )
    signs = [1 if amount > 0.0 else -1 for _, amount in events if amount != 0.0]
    return sum(
        1 for previous, current in zip(signs, signs[1:], strict=False) if previous != current
    )


def _infer_terminal_time(flows: list[MwrCashFlow], terminal_time_years: float | None) -> float:
    if terminal_time_years is not None:
        return terminal_time_years
    positive_times = [flow.t_years for flow in flows if flow.t_years > 0.0]
    return max(positive_times) if positive_times else 1.0


def money_weighted_return(
    *,
    flows: list[MwrCashFlow],
    terminal_value: float,
    terminal_time_years: float | None = None,
    tolerance: float = 1e-10,
    max_iterations: int = 100,
) -> dict[str, Any]:
    """Solve an XIRR-style money-weighted return.

    Uses bracketed Newton steps with bisection fallback. To avoid silently
    selecting an arbitrary answer when cash-flow signs alternate, the function
    fails closed when the ordered flow stream has more than one sign change.
    """

    if not flows:
        raise ValueError("flows must be non-empty")
    _ensure_finite(terminal_value, "terminal_value")
    if terminal_time_years is not None:
        _ensure_finite(terminal_time_years, "terminal_time_years")
    if terminal_value < 0.0:
        raise ValueError("terminal_value must be >= 0")
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError("tolerance must be finite and > 0")
    if max_iterations < 1:
        raise ValueError("max_iterations must be >= 1")
    for flow in flows:
        _ensure_finite(flow.t_years, "flow time")
        _ensure_finite(flow.amount, "flow amount")
        if flow.t_years < 0.0:
            raise ValueError("flow times must be >= 0")

    terminal_time = _infer_terminal_time(flows, terminal_time_years)
    if terminal_time <= 0.0:
        raise ValueError("terminal_time_years must be > 0")
    if terminal_time < max(flow.t_years for flow in flows):
        raise ValueError("terminal_time_years must be >= every flow time")
    if not any(flow.amount < 0.0 for flow in flows):
        raise ValueError("at least one contribution flow must be negative")
    if terminal_value <= 0.0 and not any(flow.amount > 0.0 for flow in flows):
        raise ValueError("at least one positive withdrawal or terminal value is required")
    if _cash_flow_sign_changes(flows, terminal_value, terminal_time) > 1:
        raise ValueError("cash-flow signs allow multiple possible IRR roots")

    lo = -0.999999999
    hi = 1.0
    f_lo = _npv(lo, flows, terminal_value, terminal_time)
    f_hi = _npv(hi, flows, terminal_value, terminal_time)
    expansions = 0
    while f_lo * f_hi > 0.0 and hi < _MAX_RATE:
        hi = hi * 2.0 + 1.0
        f_hi = _npv(hi, flows, terminal_value, terminal_time)
        expansions += 1
    if f_lo * f_hi > 0.0:
        raise ValueError("could not bracket a money-weighted return root")

    rate = (lo + hi) / 2.0
    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        f_rate = _npv(rate, flows, terminal_value, terminal_time)
        if abs(f_rate) <= tolerance:
            break
        derivative = _npv_derivative(rate, flows, terminal_value, terminal_time)
        candidate = rate - f_rate / derivative if derivative != 0.0 else math.nan
        if not math.isfinite(candidate) or candidate <= lo or candidate >= hi:
            candidate = (lo + hi) / 2.0
        f_candidate = _npv(candidate, flows, terminal_value, terminal_time)
        if f_lo * f_candidate <= 0.0:
            hi = candidate
        else:
            lo = candidate
            f_lo = f_candidate
        rate = candidate
        if abs(hi - lo) <= tolerance:
            break
    else:
        raise ValueError("money-weighted return did not converge")

    return {
        "rate": _round(rate),
        "terminalTimeYears": _round(terminal_time),
        "iterations": iterations,
        "bracketExpansions": expansions,
        "method": "bracketed_newton_bisection",
    }


def fee_drag(
    *,
    gross_returns: list[float],
    fee_rates: list[float],
    periods_per_year: int = 1,
) -> dict[str, Any]:
    """Compare gross and net return series after per-period fee rates."""

    _validate_periods_per_year(periods_per_year)
    _validate_return_series(gross_returns, "gross_returns")
    if len(gross_returns) != len(fee_rates):
        raise ValueError("gross_returns and fee_rates must have the same length")
    for value in fee_rates:
        _ensure_finite(value, "fee_rates")
    if any(rate < 0.0 or rate >= 1.0 for rate in fee_rates):
        raise ValueError("fee_rates must be >= 0 and < 1")

    net_returns = [
        (1.0 + gross) * (1.0 - fee) - 1.0
        for gross, fee in zip(gross_returns, fee_rates, strict=True)
    ]
    cumulative_gross = _compound_return(gross_returns)
    cumulative_net = _compound_return(net_returns)
    annualized_gross = _annualized_return(cumulative_gross, len(gross_returns), periods_per_year)
    annualized_net = _annualized_return(cumulative_net, len(net_returns), periods_per_year)
    return {
        "periods": len(gross_returns),
        "periodsPerYear": periods_per_year,
        "netReturns": [_round(value) for value in net_returns],
        "cumulativeGrossReturn": _round(cumulative_gross),
        "cumulativeNetReturn": _round(cumulative_net),
        "cumulativeFeeDrag": _round(cumulative_net - cumulative_gross),
        "annualizedGrossReturn": _round(annualized_gross),
        "annualizedNetReturn": _round(annualized_net),
        "annualizedFeeDrag": _round(annualized_net - annualized_gross),
    }


def benchmark_relative(
    *,
    portfolio_returns: list[float],
    benchmark_returns: list[float],
    periods_per_year: int = 1,
) -> dict[str, Any]:
    """Cumulative and annualized portfolio-vs-benchmark return deltas."""

    _validate_periods_per_year(periods_per_year)
    _validate_return_series(portfolio_returns, "portfolio_returns")
    _validate_return_series(benchmark_returns, "benchmark_returns")
    if len(portfolio_returns) != len(benchmark_returns):
        raise ValueError("portfolio_returns and benchmark_returns must have the same length")

    cumulative_portfolio = _compound_return(portfolio_returns)
    cumulative_benchmark = _compound_return(benchmark_returns)
    annualized_portfolio = _annualized_return(
        cumulative_portfolio, len(portfolio_returns), periods_per_year
    )
    annualized_benchmark = _annualized_return(
        cumulative_benchmark, len(benchmark_returns), periods_per_year
    )
    return {
        "periods": len(portfolio_returns),
        "periodsPerYear": periods_per_year,
        "relativeReturns": [
            _round(portfolio - benchmark)
            for portfolio, benchmark in zip(portfolio_returns, benchmark_returns, strict=True)
        ],
        "cumulativePortfolioReturn": _round(cumulative_portfolio),
        "cumulativeBenchmarkReturn": _round(cumulative_benchmark),
        "cumulativeExcessReturn": _round(cumulative_portfolio - cumulative_benchmark),
        "annualizedPortfolioReturn": _round(annualized_portfolio),
        "annualizedBenchmarkReturn": _round(annualized_benchmark),
        "annualizedExcessReturn": _round(annualized_portfolio - annualized_benchmark),
    }


def performance_analysis(
    *,
    twr_periods: list[TwrPeriod] | None = None,
    flow_timing: FlowTiming = "start",
    periods_per_year: int = 1,
    mwr_flows: list[MwrCashFlow] | None = None,
    terminal_value: float | None = None,
    terminal_time_years: float | None = None,
    gross_returns: list[float] | None = None,
    fee_rates: list[float] | None = None,
    portfolio_returns: list[float] | None = None,
    benchmark_returns: list[float] | None = None,
) -> dict[str, Any]:
    """Composite performance math for report/review exhibits."""

    has_twr = twr_periods is not None
    has_mwr = mwr_flows is not None or terminal_value is not None or terminal_time_years is not None
    has_fee_drag = gross_returns is not None or fee_rates is not None
    has_benchmark = portfolio_returns is not None or benchmark_returns is not None
    if not any((has_twr, has_mwr, has_fee_drag, has_benchmark)):
        raise ValueError("request at least one performance analysis section")

    twr = (
        time_weighted_return(
            periods=twr_periods,
            flow_timing=flow_timing,
            periods_per_year=periods_per_year,
        )
        if twr_periods is not None
        else None
    )

    if mwr_flows is None and (terminal_value is not None or terminal_time_years is not None):
        raise ValueError("mwr_flows are required when terminal value/time is supplied")
    if mwr_flows is not None and terminal_value is None:
        raise ValueError("terminal_value is required for money-weighted return")
    mwr = (
        money_weighted_return(
            flows=mwr_flows,
            terminal_value=terminal_value,
            terminal_time_years=terminal_time_years,
        )
        if mwr_flows is not None and terminal_value is not None
        else None
    )

    if (gross_returns is None) != (fee_rates is None):
        raise ValueError("gross_returns and fee_rates must be supplied together")
    drag = (
        fee_drag(
            gross_returns=gross_returns,
            fee_rates=fee_rates,
            periods_per_year=periods_per_year,
        )
        if gross_returns is not None and fee_rates is not None
        else None
    )

    if (portfolio_returns is None) != (benchmark_returns is None):
        raise ValueError("portfolio_returns and benchmark_returns must be supplied together")
    relative = (
        benchmark_relative(
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            periods_per_year=periods_per_year,
        )
        if portfolio_returns is not None and benchmark_returns is not None
        else None
    )

    return {
        "timeWeighted": twr,
        "moneyWeighted": mwr,
        "feeDrag": drag,
        "benchmarkRelative": relative,
        "assumptions": {
            "flowTiming": flow_timing,
            "periodsPerYear": periods_per_year,
            "cashFlowSignConvention": "investor_perspective_contributions_negative",
            "compositeTool": "performance_analysis",
        },
        "disclaimer": MC_DISCLAIMER,
    }


__all__ = [
    "FlowTiming",
    "MwrCashFlow",
    "TwrPeriod",
    "benchmark_relative",
    "fee_drag",
    "money_weighted_return",
    "performance_analysis",
    "time_weighted_return",
]
