# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic tests for EMF Check #7 — Sector Tailwind.

No network. Builds ``ScoringContext`` objects with fixture dicts and asserts
the pass / fail / missing-data (passed=None) branches plus the faithful
3-month return computation.
"""

from __future__ import annotations

from nexus_core.engine.scoring.checks import ScoringContext
from nexus_core.engine.scoring.emf.sector_tailwind import (
    SECTOR_ETF_MAP,
    THRESHOLD_DESC,
    SectorTailwindCheck,
    compute_period_return,
    sector_etf_for,
)


def _ctx(**kwargs: object) -> ScoringContext:
    fundamentals = dict(kwargs.pop("fundamentals", {}) or {})  # type: ignore[arg-type]
    extra = dict(kwargs.pop("extra", {}) or {})  # type: ignore[arg-type]
    return ScoringContext(
        ticker=str(kwargs.pop("ticker", "TEST")),
        fundamentals=fundamentals,
        extra=extra,
    )


# --- helper: sector ETF mapping --------------------------------------------


def test_sector_etf_for_maps_known_sectors() -> None:
    assert sector_etf_for("Technology") == "XLK"
    assert sector_etf_for("financial services") == "XLF"
    assert sector_etf_for("Real Estate") == "XLRE"
    # Synonyms map to the same ETF.
    assert sector_etf_for("financials") == SECTOR_ETF_MAP["financials"] == "XLF"


def test_sector_etf_for_unknown_or_empty() -> None:
    assert sector_etf_for("Crypto") is None
    assert sector_etf_for("") is None


# --- helper: 3-month return -------------------------------------------------


def test_compute_period_return_matches_upstream_formula() -> None:
    # ((110 - 100) / 100) * 100 == 10.0
    bars = [{"close": 100.0}, {"close": 105.0}, {"close": 110.0}]
    assert compute_period_return(bars) == 10.0


def test_compute_period_return_supports_c_alias() -> None:
    bars = [{"c": 200.0}, {"c": 180.0}]
    assert compute_period_return(bars) == -10.0


def test_compute_period_return_insufficient_bars() -> None:
    assert compute_period_return([]) is None
    assert compute_period_return([{"close": 100.0}]) is None


def test_compute_period_return_nonpositive_first_close() -> None:
    assert compute_period_return([{"close": 0.0}, {"close": 50.0}]) is None


# --- pass branch ------------------------------------------------------------


def test_pass_when_sector_outperforms_spx() -> None:
    ctx = _ctx(
        ticker="NVDA",
        fundamentals={"sector": "Technology"},
        extra={"sector_change": 12.0, "spy_change": 5.0},
    )
    result = SectorTailwindCheck()(ctx)
    assert result.check_number == 7
    assert result.name == "Sector Tailwind"
    assert result.passed is True
    assert result.value == 12.0
    assert result.threshold == 5.0  # SPY return is the comparison bar
    assert result.signal == "green"
    assert result.details["sector_etf"] == "XLK"
    assert result.details["threshold_desc"] == THRESHOLD_DESC
    assert "outperforming" in result.interpretation


def test_pass_from_raw_price_windows() -> None:
    # Sector +20% vs SPY +5% -> pass, recomputed from raw bars.
    ctx = _ctx(
        fundamentals={"sector": "Energy"},
        extra={
            "sector_prices": [{"close": 100.0}, {"close": 120.0}],
            "spy_prices": [{"close": 100.0}, {"close": 105.0}],
        },
    )
    result = SectorTailwindCheck()(ctx)
    assert result.passed is True
    assert result.value == 20.0
    assert result.threshold == 5.0
    assert result.details["sector_etf"] == "XLE"


# --- fail branch ------------------------------------------------------------


def test_fail_when_sector_underperforms_spx() -> None:
    ctx = _ctx(
        ticker="XOM",
        fundamentals={"sector": "Energy"},
        extra={"sector_change": -3.0, "spy_change": 4.0},
    )
    result = SectorTailwindCheck()(ctx)
    assert result.passed is False
    assert result.value == -3.0
    assert result.threshold == 4.0
    assert result.signal == "red"
    assert "underperforming" in result.interpretation


def test_fail_is_strict_inequality_on_tie() -> None:
    # Equal returns -> not strictly greater -> fail (upstream: sector > spy).
    ctx = _ctx(
        fundamentals={"sector": "Healthcare"},
        extra={"sector_change": 5.0, "spy_change": 5.0},
    )
    result = SectorTailwindCheck()(ctx)
    assert result.passed is False


# --- missing-data branch (passed=None) -------------------------------------


def test_missing_returns_yields_none() -> None:
    ctx = _ctx(fundamentals={"sector": "Technology"})
    result = SectorTailwindCheck()(ctx)
    assert result.passed is None
    assert result.signal == "insufficient_data"
    assert result.details["sector_etf"] == "XLK"


def test_unmapped_sector_yields_none_with_message() -> None:
    ctx = _ctx(
        fundamentals={"sector": "Crypto"},
        extra={"sector_change": 9.0, "spy_change": 1.0},
    )
    result = SectorTailwindCheck()(ctx)
    # sector_etf is None, but returns are present -> still evaluable (upstream
    # only blocks when returns are missing, not when the ETF map misses).
    assert result.passed is True
    assert result.details["sector_etf"] is None


def test_no_sector_yields_none() -> None:
    ctx = _ctx()
    result = SectorTailwindCheck()(ctx)
    assert result.passed is None
    assert result.signal == "insufficient_data"
    assert result.interpretation == "Sector not identified"


def test_partial_returns_yield_none() -> None:
    # Only one side present -> cannot compare -> passed=None.
    ctx = _ctx(
        fundamentals={"sector": "Utilities"},
        extra={"sector_change": 7.0},
    )
    result = SectorTailwindCheck()(ctx)
    assert result.passed is None
    assert result.value == 7.0
    assert result.threshold is None


def test_garbage_returns_degrade_to_none() -> None:
    ctx = _ctx(
        fundamentals={"sector": "Industrials"},
        extra={"sector_change": "not-a-number", "spy_change": None},
    )
    result = SectorTailwindCheck()(ctx)
    assert result.passed is None
    assert result.signal == "insufficient_data"

