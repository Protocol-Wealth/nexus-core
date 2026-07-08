# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Historical index-blend math for planning exhibits.

Pure, deterministic functions over aligned monthly return series. No symbols,
provider calls, account names, holdings, transactions, or client records belong
in this module; wrappers may source public proxy histories before calling it.

Educational planning illustration only. Historical index-blend returns are
hypothetical and do not include fees, taxes, costs, or direct investability.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

RebalanceFrequency = Literal["monthly", "annual", "none"]

HISTORICAL_BLEND_DISCLAIMER = (
    "Educational and informational use only. Not investment, tax, legal, or "
    "financial advice, and not a recommendation. Historical blend results are "
    "hypothetical and illustrative index-blend calculations. They assume income "
    "is reinvested and exclude fees, taxes, trading costs, and implementation "
    "frictions. You cannot invest directly in an index. Past performance does "
    "not guarantee future results."
)

_REBALANCE_FREQUENCIES: tuple[RebalanceFrequency, ...] = ("monthly", "annual", "none")
_TRAILING_WINDOWS: tuple[tuple[str, int], ...] = (
    ("1Year", 12),
    ("3Year", 36),
    ("5Year", 60),
    ("7Year", 84),
    ("10Year", 120),
)


def _round_rate(value: float) -> float:
    return round(value, 6)


def _round_value(value: float) -> float:
    return round(value, 4)


def _compound(returns: Sequence[float]) -> float:
    value = 1.0
    for ret in returns:
        value *= 1.0 + ret
    return value - 1.0


def _annualize(total_return: float, months: int) -> float:
    return math.pow(1.0 + total_return, 12.0 / months) - 1.0


def _next_month(label: str) -> str:
    year = int(label[:4])
    month = int(label[5:7])
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def _validate_month_labels(labels: Sequence[str], n_months: int) -> tuple[str, ...]:
    if len(labels) != n_months:
        raise ValueError("month_labels must have the same length as the return series")
    out: list[str] = []
    previous = ""
    for label in labels:
        if (
            not isinstance(label, str)
            or len(label) < 7
            or label[4] != "-"
            or not label[:4].isdigit()
            or not label[5:7].isdigit()
        ):
            raise ValueError("month_labels must be ISO year-month strings like YYYY-MM")
        month = int(label[5:7])
        if not 1 <= month <= 12:
            raise ValueError("month_labels must contain valid calendar months")
        normalized = label[:7]
        if previous:
            if normalized <= previous:
                raise ValueError("month_labels must be strictly increasing")
            if normalized != _next_month(previous):
                raise ValueError("month_labels must be contiguous monthly observations")
        previous = normalized
        out.append(normalized)
    return tuple(out)


def _validate_inputs(
    *,
    monthly_returns_by_id: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
    month_labels: Sequence[str] | None,
    rebalance_frequency: str,
    initial_value: float,
) -> tuple[
    list[str], dict[str, list[float]], dict[str, float], tuple[str, ...], RebalanceFrequency
]:
    if rebalance_frequency not in _REBALANCE_FREQUENCIES:
        raise ValueError("rebalance_frequency must be monthly, annual, or none")
    if isinstance(initial_value, bool) or not math.isfinite(initial_value) or initial_value <= 0.0:
        raise ValueError("initial_value must be a finite positive number")
    if not monthly_returns_by_id:
        raise ValueError("monthly_returns_by_id must be non-empty")
    if set(monthly_returns_by_id) != set(weights):
        raise ValueError("weights must contain exactly the same asset ids as monthly_returns_by_id")

    ids = list(weights)
    if len(set(ids)) != len(ids):
        raise ValueError("asset ids must be unique")
    weight_sum = 0.0
    normalized_weights: dict[str, float] = {}
    normalized_returns: dict[str, list[float]] = {}
    lengths: set[int] = set()
    for asset_id in ids:
        if not asset_id:
            raise ValueError("asset ids must be non-empty strings")
        weight = weights[asset_id]
        if isinstance(weight, bool) or not math.isfinite(weight) or weight < 0.0:
            raise ValueError("weights must be finite non-negative numbers")
        normalized_weights[asset_id] = float(weight)
        weight_sum += float(weight)
        series: list[float] = []
        for ret in monthly_returns_by_id[asset_id]:
            if isinstance(ret, bool) or not math.isfinite(ret) or ret <= -1.0:
                raise ValueError("monthly returns must be finite numbers greater than -100%")
            series.append(float(ret))
        lengths.add(len(series))
        normalized_returns[asset_id] = series
    if len(lengths) != 1:
        raise ValueError("all monthly return series must have the same length")
    n_months = next(iter(lengths))
    if n_months < 3:
        raise ValueError("need at least 3 aligned monthly return observations")
    if abs(weight_sum - 1.0) > 1e-6:
        raise ValueError("weights must sum to 1.0")

    if month_labels is None:
        labels = tuple(f"period-{i + 1:03d}" for i in range(n_months))
    else:
        labels = _validate_month_labels(month_labels, n_months)
    return (
        ids,
        normalized_returns,
        normalized_weights,
        labels,
        cast(RebalanceFrequency, rebalance_frequency),
    )


def _blend_returns(
    *,
    ids: Sequence[str],
    returns_by_id: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
    labels: Sequence[str],
    rebalance_frequency: RebalanceFrequency,
    initial_value: float,
) -> tuple[list[float], list[float]]:
    if rebalance_frequency == "monthly":
        blend_returns = [
            sum(weights[asset_id] * returns_by_id[asset_id][idx] for asset_id in ids)
            for idx in range(len(labels))
        ]
        value = initial_value
        growth: list[float] = []
        for ret in blend_returns:
            value *= 1.0 + ret
            growth.append(value)
        return blend_returns, growth

    asset_values = {asset_id: initial_value * weights[asset_id] for asset_id in ids}
    blend_returns = []
    growth = []
    for idx, label in enumerate(labels):
        starting_total = sum(asset_values.values())
        for asset_id in ids:
            asset_values[asset_id] *= 1.0 + returns_by_id[asset_id][idx]
        ending_total = sum(asset_values.values())
        blend_returns.append(ending_total / starting_total - 1.0)
        growth.append(ending_total)
        annual_boundary = label.endswith("-12") or (
            label.startswith("period-") and (idx + 1) % 12 == 0
        )
        if rebalance_frequency == "annual" and annual_boundary:
            for asset_id in ids:
                asset_values[asset_id] = ending_total * weights[asset_id]
    return blend_returns, growth


def _calendar_year_returns(
    labels: Sequence[str], blend_returns: Sequence[float]
) -> list[dict[str, Any]]:
    by_year: dict[str, list[float]] = {}
    for label, ret in zip(labels, blend_returns, strict=True):
        if label.startswith("period-"):
            continue
        by_year.setdefault(label[:4], []).append(ret)
    return [
        {
            "year": int(year),
            "months": len(returns),
            "return": _round_rate(_compound(returns)),
            "complete": len(returns) == 12,
        }
        for year, returns in sorted(by_year.items())
    ]


def _annualized_returns(
    labels: Sequence[str], blend_returns: Sequence[float]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    quarter = blend_returns[-3:]
    out.append(
        {
            "window": "lastQuarter",
            "months": len(quarter),
            "return": _round_rate(_compound(quarter)),
            "annualized": False,
        }
    )
    if labels[-1].startswith("period-"):
        ytd = blend_returns
    else:
        final_year = labels[-1][:4]
        first_idx = next(i for i, label in enumerate(labels) if label[:4] == final_year)
        ytd = blend_returns[first_idx:]
    out.append(
        {
            "window": "ytd",
            "months": len(ytd),
            "return": _round_rate(_compound(ytd)),
            "annualized": False,
        }
    )

    for window, months in _TRAILING_WINDOWS:
        if len(blend_returns) < months:
            continue
        returns = blend_returns[-months:]
        total = _compound(returns)
        out.append(
            {
                "window": window,
                "months": months,
                "return": _round_rate(_annualize(total, months)),
                "annualized": True,
            }
        )
    return out


def _statistics(blend_returns: Sequence[float]) -> dict[str, Any]:
    total = _compound(blend_returns)
    annualized_mean = _annualize(total, len(blend_returns))
    monthly_sigma = statistics.pstdev(blend_returns) if len(blend_returns) > 1 else 0.0
    annualized_sigma = monthly_sigma * math.sqrt(12.0)
    return {
        "annualizedMean": _round_rate(annualized_mean),
        "annualizedVolatility": _round_rate(annualized_sigma),
        "sigmaBands": {
            "minus4Sigma": _round_rate(annualized_mean - 4.0 * annualized_sigma),
            "minus2Sigma": _round_rate(annualized_mean - 2.0 * annualized_sigma),
            "mean": _round_rate(annualized_mean),
            "plus2Sigma": _round_rate(annualized_mean + 2.0 * annualized_sigma),
            "plus4Sigma": _round_rate(annualized_mean + 4.0 * annualized_sigma),
        },
    }


def historical_blend(
    *,
    monthly_returns_by_id: Mapping[str, Sequence[float]],
    weights: Mapping[str, float],
    month_labels: Sequence[str] | None = None,
    rebalance_frequency: str = "monthly",
    initial_value: float = 1.0,
) -> dict[str, Any]:
    """Return historical blend exhibits from aligned monthly returns.

    Inputs are deliberately de-identified. Asset ids are generic labels supplied
    by the caller (for example, asset-class ids), not account or client fields.
    """

    ids, returns_by_id, clean_weights, labels, frequency = _validate_inputs(
        monthly_returns_by_id=monthly_returns_by_id,
        weights=weights,
        month_labels=month_labels,
        rebalance_frequency=rebalance_frequency,
        initial_value=initial_value,
    )
    blend_returns, growth_values = _blend_returns(
        ids=ids,
        returns_by_id=returns_by_id,
        weights=clean_weights,
        labels=labels,
        rebalance_frequency=frequency,
        initial_value=float(initial_value),
    )
    return {
        "weights": {asset_id: _round_rate(clean_weights[asset_id]) for asset_id in ids},
        "rebalanceFrequency": frequency,
        "months": len(labels),
        "startMonth": labels[0],
        "endMonth": labels[-1],
        "calendarYearReturns": _calendar_year_returns(labels, blend_returns),
        "annualizedReturns": _annualized_returns(labels, blend_returns),
        "growthOfDollar": [
            {"month": label, "value": _round_value(value)}
            for label, value in zip(labels, growth_values, strict=True)
        ],
        "statistics": _statistics(blend_returns),
        "assumptions": {
            "incomeReinvested": True,
            "feesTaxesCostsIncluded": False,
            "directIndexInvestmentPossible": False,
            "returnFrequency": "monthly",
        },
        "disclaimer": HISTORICAL_BLEND_DISCLAIMER,
    }


__all__ = ["HISTORICAL_BLEND_DISCLAIMER", "RebalanceFrequency", "historical_blend"]
