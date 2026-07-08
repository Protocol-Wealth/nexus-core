# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the multi-name collar-book assembly engine (``collar_book``).

Pure math — no market provider, no network, no clock.
"""

from __future__ import annotations

import math

from nexus_core.engine.pricing import (
    CollarBookPosition,
    assemble_collar_book,
)


def _pos(
    symbol: str = "TEST",
    spot: float = 100.0,
    dte: int = 30,
    net_credit: float = 2.0,
    dividend_income_window: float = 0.0,
    score: float | None = None,
    sector: str | None = None,
    expiration: str | None = None,
    put_strike: float | None = None,
    call_strike: float | None = None,
    floor_pct: float | None = None,
    cap_pct: float | None = None,
    executable_net_credit: float | None = None,
    call_bid: float | None = None,
    put_ask: float | None = None,
) -> CollarBookPosition:
    return CollarBookPosition(
        symbol=symbol,
        spot=spot,
        dte=dte,
        net_credit=net_credit,
        dividend_income_window=dividend_income_window,
        score=score,
        sector=sector,
        expiration=expiration,
        put_strike=put_strike,
        call_strike=call_strike,
        floor_pct=floor_pct,
        cap_pct=cap_pct,
        executable_net_credit=executable_net_credit,
        call_bid=call_bid,
        put_ask=put_ask,
    )


def test_whole_contract_flooring_and_income_arithmetic() -> None:
    # One $100 name in a $1M/15-slot book: pass 1 floors the $66,666.67 budget
    # slot to 6 whole contracts; pass 2 tops up to the 12% position cap.
    result = assemble_collar_book([_pos(symbol="ONLY")])
    assert len(result.positions) == 1
    holding = result.positions[0]
    assert holding.capital_per_contract == 10_000.0
    assert holding.contracts == 12  # 6 (pass 1) + 6 (pass 2, to the 12% cap)
    assert holding.notional == 120_000.0
    assert holding.weight_pct == 12.0
    # period = (2.0 + 0.0) × 100 × 12; annual = period × 365 / 30.
    assert holding.period_income == 2_400.0
    assert math.isclose(holding.annual_income, 2_400.0 * 365 / 30, rel_tol=1e-9)
    assert result.notional_deployed == 120_000.0
    assert result.cash_residual == 880_000.0
    assert math.isclose(result.portfolio_yield_pct, 2.0 / 100.0 * 365 / 30 * 100, abs_tol=0.01)
    assert "not investment advice" in result.disclaimer.lower()


def test_price_tier_exclusion_950_stock_in_250k_book() -> None:
    # A $950 stock is one $95,000 contract — infeasible against a $250K/15-name
    # budget slot ($16,666). Reported explicitly, never silently dropped.
    result = assemble_collar_book(
        [_pos(symbol="PRICY", spot=950.0), _pos(symbol="CHEAP", spot=40.0)],
        notional_target=250_000.0,
    )
    assert [e.symbol for e in result.excluded_price_tier] == ["PRICY"]
    assert result.excluded_price_tier[0].capital_per_contract == 95_000.0
    assert [h.symbol for h in result.positions] == ["CHEAP"]
    assert result.counts["excluded_price_tier"] == 1


def test_per_position_cap_honored() -> None:
    result = assemble_collar_book(
        [_pos(symbol="ONLY", spot=10.0)], notional_target=1_000_000.0
    )
    holding = result.positions[0]
    # Room for far more $1,000 contracts than the 12% cap allows.
    assert holding.notional <= 1_000_000.0 * 0.12 + 1e-9
    assert holding.weight_pct <= 12.0


def test_per_sector_cap_honored_and_overflow_excluded() -> None:
    # Six $100 tech names in a $1M book: 25% sector cap = $250K. Pass 1 gives
    # 6 contracts ($60K) to the first four ($240K), trims the fifth to 1
    # contract ($250K total), and excludes the sixth outright. Pass 2 has no
    # sector room left, so the cap holds exactly.
    techs = [_pos(symbol=f"T{i}", sector="Tech") for i in range(6)]
    result = assemble_collar_book(techs)
    sector_total = sum(h.notional for h in result.positions if h.sector == "Tech")
    assert sector_total == 250_000.0
    assert [h.contracts for h in result.positions] == [6, 6, 6, 6, 1]
    assert result.excluded_sector_cap == ["T5"]
    assert result.counts["excluded_sector_cap"] == 1


def test_sector_cap_only_binds_declared_sectors() -> None:
    # Unsectored names are NOT pooled into a phantom bucket: a fully
    # unsectored 15-name book deploys to 100%.
    names = [_pos(symbol=f"N{i:02d}") for i in range(15)]
    result = assemble_collar_book(names)
    assert result.excluded_sector_cap == []
    assert result.deploy_pct == 100.0


def test_residual_top_up_respects_ranking_and_caps() -> None:
    # 15 identical $100 names: pass 1 deploys 6 contracts each ($900K); pass 2
    # walks the ranking with the $100K residual — +6 to the first name (its
    # 12% cap), +4 to the second, nothing further. Symbols break the tie.
    names = [_pos(symbol=f"N{i:02d}") for i in range(15)]
    result = assemble_collar_book(names)
    contracts = {h.symbol: h.contracts for h in result.positions}
    assert contracts["N00"] == 12
    assert contracts["N01"] == 10
    assert all(contracts[f"N{i:02d}"] == 6 for i in range(2, 15))
    assert result.notional_deployed == 1_000_000.0
    assert result.cash_residual == 0.0
    assert result.deploy_pct == 100.0
    assert result.warnings == []  # 15 names ≥ 12 minimum, 100% ≥ 90% deploy


def test_capital_weighted_floor_and_cap_from_strikes() -> None:
    positions = [
        _pos(symbol="AAA", spot=100.0, put_strike=85.0, call_strike=110.0),
        _pos(symbol="BBB", spot=50.0, put_strike=45.0, call_strike=60.0),
    ]
    result = assemble_collar_book(positions, notional_target=250_000.0)
    by_symbol = {h.symbol: h for h in result.positions}
    assert by_symbol["AAA"].floor_pct == 15.0  # derived: (100 - 85) / 100
    assert by_symbol["BBB"].cap_pct == 20.0  # derived: (60 - 50) / 50
    expected_floor = sum(
        (h.floor_pct or 0.0) * h.notional for h in result.positions
    ) / result.notional_deployed
    assert result.capital_weighted_floor_pct is not None
    assert math.isclose(result.capital_weighted_floor_pct, round(expected_floor, 2))
    assert result.capital_weighted_cap_pct is not None


def test_capital_weighted_floor_none_when_data_absent() -> None:
    # One name carries strikes, the other nothing — a partial average would
    # misstate the book, so the aggregate is None.
    positions = [
        _pos(symbol="AAA", put_strike=85.0, call_strike=110.0),
        _pos(symbol="BBB"),
    ]
    result = assemble_collar_book(positions)
    assert result.capital_weighted_floor_pct is None
    assert result.capital_weighted_cap_pct is None


def test_explicit_floor_pct_passthrough_wins_over_strikes() -> None:
    result = assemble_collar_book(
        [_pos(symbol="AAA", put_strike=85.0, floor_pct=14.0, cap_pct=9.5)]
    )
    holding = result.positions[0]
    assert holding.floor_pct == 14.0  # given value, not the strike-derived 15.0
    assert holding.cap_pct == 9.5
    assert holding.put_strike == 85.0  # strikes still echoed for display


def test_degenerate_inputs_excluded_not_raised() -> None:
    result = assemble_collar_book(
        [
            _pos(symbol="ZSPOT", spot=0.0),
            _pos(symbol="NSPOT", spot=-5.0),
            _pos(symbol="ZDTE", dte=0),
            _pos(symbol="NDTE", dte=-10),
            _pos(symbol="GOOD"),
        ]
    )
    reasons = {e.symbol: e.reason for e in result.excluded_degenerate}
    assert set(reasons) == {"ZSPOT", "NSPOT", "ZDTE", "NDTE"}
    assert "spot" in reasons["ZSPOT"] and "spot" in reasons["NSPOT"]
    assert "dte" in reasons["ZDTE"] and "dte" in reasons["NDTE"]
    assert [h.symbol for h in result.positions] == ["GOOD"]
    assert result.counts == {
        "input": 5,
        "held": 1,
        "excluded_price_tier": 0,
        "excluded_sector_cap": 0,
        "excluded_degenerate": 4,
    }


def test_degenerate_params_degrade_not_raise() -> None:
    result = assemble_collar_book([_pos()], notional_target=0.0)
    assert result.positions == []
    assert result.warnings  # explains why nothing was assembled


def test_ranking_by_score_when_all_scored() -> None:
    # LOWYIELD carries the higher external score and must rank (and size) first
    # even though HIYIELD has the better income yield.
    positions = [
        _pos(symbol="HIYIELD", net_credit=5.0, score=1.0),
        _pos(symbol="LOWYIELD", net_credit=1.0, score=9.0),
    ]
    result = assemble_collar_book(positions, notional_target=250_000.0)
    assert [h.symbol for h in result.positions] == ["LOWYIELD", "HIYIELD"]
    assert result.warnings == [] or all("score" not in w for w in result.warnings)


def test_ranking_falls_back_to_income_yield_without_scores() -> None:
    positions = [
        _pos(symbol="LOWYIELD", net_credit=1.0),
        _pos(symbol="HIYIELD", net_credit=5.0),
    ]
    result = assemble_collar_book(positions, notional_target=250_000.0)
    assert [h.symbol for h in result.positions] == ["HIYIELD", "LOWYIELD"]


def test_partial_scores_fall_back_with_warning() -> None:
    positions = [
        _pos(symbol="SCORED", net_credit=1.0, score=9.0),
        _pos(symbol="UNSCORED", net_credit=5.0),
    ]
    result = assemble_collar_book(positions, notional_target=250_000.0)
    # Income-yield fallback: the unscored high-yield name still ranks first.
    assert [h.symbol for h in result.positions] == ["UNSCORED", "SCORED"]
    assert any("score" in w for w in result.warnings)


def test_breadth_and_cash_drag_warnings_but_no_yield_policing() -> None:
    # A single 60%-annualized-yield name: breadth + deploy warnings fire, but
    # the reported yield draws NO band warning — the engine describes, it does
    # not prescribe.
    result = assemble_collar_book([_pos(net_credit=5.0, dte=30)])
    assert any("minimum" in w for w in result.warnings)
    assert any("cash drag" in w for w in result.warnings)
    assert result.portfolio_yield_pct > 30.0
    assert not any("band" in w.lower() or "yield" in w.lower() for w in result.warnings)


def test_net_debit_book_reports_negative_income() -> None:
    result = assemble_collar_book([_pos(net_credit=-1.5)])
    assert result.annual_income < 0.0
    assert result.portfolio_yield_pct < 0.0
    assert result.positions[0].period_income < 0.0


def test_dividend_income_window_adds_to_period_income() -> None:
    plain = assemble_collar_book([_pos(net_credit=2.0)])
    with_div = assemble_collar_book([_pos(net_credit=2.0, dividend_income_window=0.5)])
    assert with_div.positions[0].contracts == plain.positions[0].contracts
    assert with_div.positions[0].period_income > plain.positions[0].period_income
    # Per contract: (2.0 + 0.5) × 100 vs 2.0 × 100 over the same window.
    ratio = with_div.positions[0].period_income / plain.positions[0].period_income
    assert math.isclose(ratio, 2.5 / 2.0, rel_tol=1e-9)


def test_bid_ask_executable_credit_reports_fill_haircut() -> None:
    result = assemble_collar_book([_pos(net_credit=2.0, call_bid=1.8, put_ask=0.3)])
    holding = result.positions[0]
    assert holding.stock_price == 100.0
    assert holding.shares == 1200
    assert holding.executable_net_credit == 1.5
    assert holding.fill_haircut == 0.5
    assert holding.period_income == 2400.0
    assert holding.executable_period_income == 1800.0
    assert holding.executable_yield_pct == 18.25
    assert result.fill_haircut == 600.0
    assert result.portfolio_yield_pct == 24.33
    assert result.executable_portfolio_yield_pct == 18.25
    assert result.fill_haircut_yield_pct == 6.08


def test_explicit_executable_net_credit_wins_over_bid_ask() -> None:
    result = assemble_collar_book(
        [_pos(net_credit=2.0, executable_net_credit=1.25, call_bid=1.8, put_ask=0.3)]
    )
    holding = result.positions[0]
    assert holding.executable_net_credit == 1.25
    assert holding.fill_haircut == 0.75


def test_n_positions_max_bounds_the_book() -> None:
    names = [_pos(symbol=f"N{i:02d}") for i in range(30)]
    result = assemble_collar_book(names, n_positions_max=20, n_positions_target=20)
    assert len(result.positions) <= 20


def test_n_positions_max_hard_stop() -> None:
    # With a low n_max and a target below the 95% pass-1 fill threshold, the
    # ranking walk must stop at exactly n_max held names.
    names = [_pos(symbol=f"N{i}") for i in range(5)]
    result = assemble_collar_book(
        names, n_positions_min=1, n_positions_target=1, n_positions_max=3
    )
    assert len(result.positions) == 3


def test_position_cap_below_budget_slot_is_price_tier_exclusion() -> None:
    # Budget slot ($100K) fits two $50K contracts, but the 12% position cap
    # ($12K) fits none — reported as a price-tier exclusion.
    result = assemble_collar_book(
        [_pos(symbol="BIG", spot=500.0)],
        notional_target=100_000.0,
        n_positions_min=1,
        n_positions_target=1,
        n_positions_max=1,
    )
    assert [e.symbol for e in result.excluded_price_tier] == ["BIG"]
    assert result.positions == []


def test_empty_book_reports_zeroes_and_none_aggregates() -> None:
    result = assemble_collar_book([_pos(symbol="BAD", spot=0.0)])
    assert result.positions == []
    assert result.notional_deployed == 0.0
    assert result.portfolio_yield_pct == 0.0
    assert result.capital_weighted_floor_pct is None
    assert result.capital_weighted_cap_pct is None
    assert result.counts["held"] == 0
