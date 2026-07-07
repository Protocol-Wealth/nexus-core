# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for public-safe performance math."""

from __future__ import annotations

import math

import jsonschema
import pytest

from nexus_core.app.planning.contract import PlanningInputError
from nexus_core.app.planning.tools import performance_analysis_tool
from nexus_core.engine.planning import (
    MwrCashFlow,
    TwrPeriod,
    benchmark_relative,
    fee_drag,
    money_weighted_return,
    performance_analysis,
    performance_analysis_result_schema,
    time_weighted_return,
)


def test_time_weighted_return_geometrically_links_start_timed_flows() -> None:
    out = time_weighted_return(
        periods=[
            TwrPeriod(start_value=100.0, end_value=110.0),
            TwrPeriod(start_value=110.0, end_value=220.0, net_external_flow=90.0),
        ],
        flow_timing="start",
        periods_per_year=2,
    )

    assert [row["return"] for row in out["periodReturns"]] == [0.1, 0.1]
    assert out["cumulativeReturn"] == pytest.approx(0.21)
    assert out["annualizedReturn"] == pytest.approx(0.21)


def test_time_weighted_return_supports_end_timed_flows() -> None:
    out = time_weighted_return(
        periods=[TwrPeriod(start_value=100.0, end_value=210.0, net_external_flow=100.0)],
        flow_timing="end",
    )

    assert out["periodReturns"][0]["return"] == pytest.approx(0.1)
    assert out["cumulativeReturn"] == pytest.approx(0.1)


def test_money_weighted_return_known_closed_case() -> None:
    out = money_weighted_return(
        flows=[MwrCashFlow(t_years=0.0, amount=-100.0)],
        terminal_value=110.0,
        terminal_time_years=1.0,
    )

    assert out["rate"] == pytest.approx(0.1)
    assert out["method"] == "bracketed_newton_bisection"


def test_twr_and_mwr_diverge_with_large_mid_period_flow() -> None:
    twr = time_weighted_return(
        periods=[
            TwrPeriod(start_value=100.0, end_value=110.0),
            TwrPeriod(start_value=110.0, end_value=959.5, net_external_flow=900.0),
        ],
        flow_timing="start",
        periods_per_year=2,
    )
    mwr = money_weighted_return(
        flows=[
            MwrCashFlow(t_years=0.0, amount=-100.0),
            MwrCashFlow(t_years=0.5, amount=-900.0),
        ],
        terminal_value=959.5,
        terminal_time_years=1.0,
    )

    assert twr["cumulativeReturn"] == pytest.approx(0.045)
    assert mwr["rate"] < 0.0
    assert mwr["rate"] < twr["cumulativeReturn"]


def test_money_weighted_return_rejects_pathological_flows() -> None:
    with pytest.raises(ValueError, match="positive withdrawal or terminal"):
        money_weighted_return(
            flows=[MwrCashFlow(t_years=0.0, amount=-100.0)],
            terminal_value=0.0,
            terminal_time_years=1.0,
        )
    with pytest.raises(ValueError, match="tolerance"):
        money_weighted_return(
            flows=[MwrCashFlow(t_years=0.0, amount=-100.0)],
            terminal_value=110.0,
            terminal_time_years=1.0,
            tolerance=math.inf,
        )
    with pytest.raises(ValueError, match="multiple possible IRR roots"):
        money_weighted_return(
            flows=[
                MwrCashFlow(t_years=0.0, amount=-100.0),
                MwrCashFlow(t_years=1.0, amount=230.0),
                MwrCashFlow(t_years=2.0, amount=-132.0),
            ],
            terminal_value=0.0,
            terminal_time_years=2.0,
        )


def test_fee_drag_identity() -> None:
    out = fee_drag(gross_returns=[0.10, 0.10], fee_rates=[0.01, 0.01], periods_per_year=2)

    assert out["netReturns"] == [0.089, 0.089]
    assert out["cumulativeGrossReturn"] == pytest.approx(0.21)
    assert out["cumulativeNetReturn"] == pytest.approx(0.185921)
    assert out["cumulativeFeeDrag"] == pytest.approx(-0.024079)


def test_benchmark_relative_cumulative_and_annualized_deltas() -> None:
    out = benchmark_relative(
        portfolio_returns=[0.10, 0.0],
        benchmark_returns=[0.05, 0.05],
        periods_per_year=2,
    )

    assert out["relativeReturns"] == [0.05, -0.05]
    assert out["cumulativePortfolioReturn"] == pytest.approx(0.1)
    assert out["cumulativeBenchmarkReturn"] == pytest.approx(0.1025)
    assert out["cumulativeExcessReturn"] == pytest.approx(-0.0025)
    assert out["annualizedExcessReturn"] == pytest.approx(-0.0025)


def test_performance_analysis_composite_and_schema() -> None:
    body = performance_analysis(
        twr_periods=[TwrPeriod(start_value=100.0, end_value=110.0)],
        mwr_flows=[MwrCashFlow(t_years=0.0, amount=-100.0)],
        terminal_value=110.0,
        terminal_time_years=1.0,
        gross_returns=[0.10, 0.10],
        fee_rates=[0.01, 0.01],
        portfolio_returns=[0.10, 0.0],
        benchmark_returns=[0.05, 0.05],
    )
    wire_body = {"contractVersion": "0.1.0", **body}

    assert body["timeWeighted"] is not None
    assert body["moneyWeighted"] is not None
    assert body["feeDrag"] is not None
    assert body["benchmarkRelative"] is not None
    assert "illustrative model results" in body["disclaimer"]
    jsonschema.validate(instance=wire_body, schema=performance_analysis_result_schema())


def test_engine_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        time_weighted_return(periods=[TwrPeriod(start_value=math.inf, end_value=110.0)])
    with pytest.raises(ValueError, match="finite"):
        money_weighted_return(
            flows=[MwrCashFlow(t_years=0.0, amount=-100.0)],
            terminal_value=-math.inf,
            terminal_time_years=1.0,
        )
    with pytest.raises(ValueError, match="finite"):
        fee_drag(gross_returns=[math.nan], fee_rates=[0.01])
    with pytest.raises(ValueError, match="finite"):
        benchmark_relative(portfolio_returns=[math.inf], benchmark_returns=[0.01])


def test_tool_rejects_non_finite_values_before_json_response() -> None:
    with pytest.raises(PlanningInputError, match=r"grossReturns\[0\] must be finite"):
        performance_analysis_tool({"grossReturns": [math.nan], "feeRates": [0.01]})
    with pytest.raises(PlanningInputError, match=r"portfolioReturns\[0\] must be finite"):
        performance_analysis_tool({"portfolioReturns": [math.inf], "benchmarkReturns": [0.01]})
    with pytest.raises(PlanningInputError, match="terminalValue must be finite"):
        performance_analysis_tool(
            {
                "mwrFlows": [{"tYears": 0.0, "amount": -100.0}],
                "terminalValue": -math.inf,
            }
        )
