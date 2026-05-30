# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic tests for EMF Check 8 — ASAN Screen (structural advantage).

No network. Builds ``ScoringContext`` objects with fixture dicts and asserts
the pass / fail / auto-pass / missing-data behaviours of the ported logic.
"""

from __future__ import annotations

from nexus_core.engine.scoring import ScoringContext
from nexus_core.engine.scoring.emf.structural_advantage import (
    MAX_STRUCTURAL_SCORE,
    ASANScreenCheck,
    classify_sector,
)


def _ctx(ticker: str = "TEST", **fundamentals: object) -> ScoringContext:
    return ScoringContext(ticker=ticker, fundamentals=dict(fundamentals))


# --- classification --------------------------------------------------------


def test_classify_saas_by_industry() -> None:
    assert classify_sector("Technology", "Software - Infrastructure") == "saas"


def test_classify_semiconductor_by_industry() -> None:
    assert classify_sector("Technology", "Semiconductors") == "semiconductor"


def test_classify_financial_by_sector_field() -> None:
    assert classify_sector("Financial Services", "Insurance - Diversified") == "financial"


def test_classify_unknown() -> None:
    # A sector/industry that matches no SaaS keyword, scoring map, or field map.
    assert classify_sector("Nonexistent Sector", "Nonexistent Industry") == "unknown"


def test_classify_technology_hardware() -> None:
    # AAPL shape: technology sector, hardware industry (not SaaS, not semiconductor).
    assert classify_sector("Technology", "Electronic Computers") == "technology_hardware"
    assert classify_sector("Technology", "Consumer Electronics") == "technology_hardware"


def test_classify_new_buckets_by_sector_field() -> None:
    assert classify_sector("Utilities", "Regulated Electric") == "utilities"
    assert classify_sector("Communication Services", "Telecom Services") == "communication"
    assert classify_sector("Basic Materials", "Specialty Chemicals") == "materials"
    assert classify_sector("Real Estate", "REIT - Residential") == "real_estate"


# --- non-SaaS structural advantage: PASS -----------------------------------


def test_semiconductor_passes_with_strong_factors() -> None:
    # GM > 50%, rev growth > 10% + R&D > 15%, market cap > $50B => 3/3.
    check = ASANScreenCheck()
    ctx = _ctx(
        "NVDA",
        sector="Technology",
        industry="Semiconductors",
        gross_margin=0.62,
        revenue_growth=0.40,
        market_cap=2_000_000_000_000,
        income_statements=[{"researchAndDevelopmentExpenses": 1_000, "revenue": 5_000}],
    )
    result = check(ctx)
    assert result.check_number == 8
    assert result.name == "ASAN Screen"
    assert result.passed is True
    assert result.value == 3.0
    assert result.threshold == 2.0
    assert result.signal == "GREEN"
    assert result.details["sector_type"] == "semiconductor"
    assert result.details["max_score"] == MAX_STRUCTURAL_SCORE


# --- non-SaaS structural advantage: FAIL -----------------------------------


def test_consumer_fails_with_weak_factors() -> None:
    # Flat growth, thin margin, small cap => 0/3 => fail (RED).
    check = ASANScreenCheck()
    ctx = _ctx(
        "SMALLCO",
        sector="Consumer Cyclical",
        industry="Specialty Retail",
        revenue_growth=0.0,
        gross_margin=0.20,
        market_cap=1_000_000_000,
    )
    result = check(ctx)
    assert result.passed is False
    assert result.value == 0.0
    assert result.signal == "RED"
    assert result.details["sector_type"] == "consumer"


def test_consumer_one_factor_is_yellow_fail() -> None:
    # Only brand-premium margin passes (1/3) => fail but YELLOW.
    check = ASANScreenCheck()
    ctx = _ctx(
        "MIDCO",
        sector="Consumer Defensive",
        industry="Packaged Foods",
        revenue_growth=0.0,
        gross_margin=0.55,
        market_cap=1_000_000_000,
    )
    result = check(ctx)
    assert result.value == 1.0
    assert result.passed is False
    assert result.signal == "YELLOW"


# --- SaaS / ASAN Trinity path ----------------------------------------------


def test_saas_vulnerable_ticker_fails() -> None:
    # ASAN hits all three Trinity markers (low conn + seat + discretionary).
    check = ASANScreenCheck()
    ctx = _ctx("ASAN", sector="Technology", industry="Software - Application")
    result = check(ctx)
    assert result.details["sector_type"] == "saas"
    assert result.value == 3.0
    assert result.passed is False
    assert result.signal == "RED"


def test_saas_defensible_ticker_passes() -> None:
    # A non-listed SaaS ticker hits zero markers => SAFE.
    check = ASANScreenCheck()
    ctx = _ctx("SAFECO", sector="Technology", industry="Software - Infrastructure")
    result = check(ctx)
    assert result.details["sector_type"] == "saas"
    assert result.value == 0.0
    assert result.passed is True
    assert result.signal == "GREEN"


# --- D3: unclassifiable sectors are NOT evaluated (fail-safe, not auto-pass) --


def test_unclassifiable_sector_is_not_evaluated() -> None:
    # A genuinely unmappable sector must NOT auto-pass (which would inflate the
    # pass count); it is withheld as insufficient_data.
    check = ASANScreenCheck()
    ctx = _ctx("MYSTERYCO", sector="Nonexistent Sector", industry="Nonexistent Industry")
    result = check(ctx)
    assert result.passed is None
    assert result.signal == "insufficient_data"
    assert result.details["applicable"] is False
    assert result.details["sector_type"] == "unknown"


def test_technology_hardware_is_scored_not_autopassed() -> None:
    # AAPL shape: strong factors → a real PASS (was previously auto-passed as "unknown").
    check = ASANScreenCheck()
    ctx = _ctx(
        "AAPL",
        sector="Technology",
        industry="Electronic Computers",
        gross_margin=0.45,
        revenue_growth=0.08,
        market_cap=3_000_000_000_000,
    )
    result = check(ctx)
    assert result.details["sector_type"] == "technology_hardware"
    assert result.details["applicable"] is True
    assert result.passed is True  # 3/3 factors


# --- missing data degrades to passed=None ----------------------------------


def test_missing_sector_and_industry_returns_none() -> None:
    check = ASANScreenCheck()
    ctx = _ctx("MYSTERY")  # no sector / industry
    result = check(ctx)
    assert result.passed is None
    assert result.value is None
    assert result.signal == "insufficient_data"


def test_empty_fundamentals_returns_none() -> None:
    check = ASANScreenCheck()
    ctx = ScoringContext(ticker="EMPTY")
    result = check(ctx)
    assert result.passed is None
    assert result.signal == "insufficient_data"


# --- precomputed override --------------------------------------------------


def test_precomputed_override_is_used() -> None:
    check = ASANScreenCheck()
    ctx = ScoringContext(
        ticker="PRE",
        fundamentals={"sector": "Technology", "industry": "Semiconductors"},
        extra={
            "asan_screen": {
                "passed": True,
                "value": 2.0,
                "sector_type": "semiconductor",
                "structural_score": 2,
                "signal": "GREEN",
                "interpretation": "precomputed strong",
            }
        },
    )
    result = check(ctx)
    assert result.passed is True
    assert result.value == 2.0
    assert result.details["precomputed"] is True
    assert result.interpretation == "precomputed strong"


# --- robustness: garbage data does not throw -------------------------------


def test_garbage_numeric_fields_do_not_throw() -> None:
    check = ASANScreenCheck()
    ctx = _ctx(
        "JUNK",
        sector="Energy",
        industry="Oil & Gas E&P",
        revenue_growth="not-a-number",
        operating_margin=float("nan"),
        market_cap=None,
    )
    result = check(ctx)
    # All factors unscorable => 0/3 => fail, but no exception.
    assert result.value == 0.0
    assert result.passed is False
