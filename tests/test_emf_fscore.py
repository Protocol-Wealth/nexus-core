# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic unit tests for EMF Check #2 (Piotroski F-Score).

No network. Builds ``ScoringContext`` objects from fixture dicts and asserts
pass / fail / missing-data behaviour plus the raw computation helper.
"""

from __future__ import annotations

from nexus_core.engine.scoring import ScoringContext
from nexus_core.engine.scoring.emf.fscore import (
    THRESHOLD,
    FScoreCheck,
    compute_fscore,
)


def _ctx(fundamentals: dict[str, object]) -> ScoringContext:
    return ScoringContext(ticker="TEST", fundamentals=fundamentals)


# --- raw statements that should score a perfect 9 -----------------------------
# current FY strictly better on every signal vs prior FY.
PERFECT_FUNDAMENTALS: dict[str, object] = {
    "income_statements": [
        {"netIncome": 120.0, "revenue": 1100.0, "grossProfit": 660.0},  # current
        {"netIncome": 100.0, "revenue": 1000.0, "grossProfit": 500.0},  # prior
    ],
    "balance_sheets": [
        {
            "totalAssets": 900.0,
            "longTermDebt": 100.0,
            "totalCurrentAssets": 600.0,
            "totalCurrentLiabilities": 200.0,
            "commonStockSharesOutstanding": 100.0,
        },
        {
            "totalAssets": 1000.0,
            "longTermDebt": 200.0,
            "totalCurrentAssets": 500.0,
            "totalCurrentLiabilities": 300.0,
            "commonStockSharesOutstanding": 100.0,
        },
    ],
    "cash_flows": [{"operatingCashFlow": 200.0}],
}


def test_precomputed_passes() -> None:
    res = FScoreCheck()(_ctx({"f_score": 7}))
    assert res.check_number == 2
    assert res.name == "F-Score"
    assert res.value == 7.0
    assert res.threshold == 6.0
    assert res.passed is True
    assert res.signal == "strong"


def test_precomputed_fails_below_threshold() -> None:
    res = FScoreCheck()(_ctx({"f_score": 4}))
    assert res.value == 4.0
    assert res.passed is False
    assert res.signal == "weak"


def test_precomputed_boundary_six_passes() -> None:
    # Threshold is >= 6 (canonical pw-nexus rule).
    res = FScoreCheck()(_ctx({"f_score": THRESHOLD}))
    assert res.passed is True
    assert res.signal == "average"  # 6 -> >=5 band, not strong


def test_fscore_key_alias() -> None:
    res = FScoreCheck()(_ctx({"fscore": 8}))
    assert res.value == 8.0
    assert res.passed is True


def test_compute_from_raw_statements_perfect_nine() -> None:
    score = compute_fscore(
        PERFECT_FUNDAMENTALS["income_statements"],  # type: ignore[arg-type]
        PERFECT_FUNDAMENTALS["balance_sheets"],  # type: ignore[arg-type]
        PERFECT_FUNDAMENTALS["cash_flows"],  # type: ignore[arg-type]
    )
    assert score == 9


def test_check_computes_from_raw_when_no_precomputed() -> None:
    res = FScoreCheck()(_ctx(PERFECT_FUNDAMENTALS))
    assert res.value == 9.0
    assert res.passed is True
    assert res.signal == "strong"
    assert res.details == {"score": 9, "max": 9}


def test_provider_envelope_raw_values() -> None:
    # Values may arrive wrapped as {"raw": n} (FMP/provider envelope).
    fundamentals: dict[str, object] = {
        "income_statements": [
            {"netIncome": {"raw": 120.0}, "revenue": {"raw": 1100.0},
             "grossProfit": {"raw": 660.0}},
            {"netIncome": {"raw": 100.0}, "revenue": {"raw": 1000.0},
             "grossProfit": {"raw": 500.0}},
        ],
        "balance_sheets": PERFECT_FUNDAMENTALS["balance_sheets"],
        "cash_flows": PERFECT_FUNDAMENTALS["cash_flows"],
    }
    res = FScoreCheck()(_ctx(fundamentals))
    assert res.value == 9.0
    assert res.passed is True


def test_weak_company_fails() -> None:
    # Loss-making, deteriorating, diluting, levering up -> low score.
    fundamentals: dict[str, object] = {
        "income_statements": [
            {"netIncome": -50.0, "revenue": 900.0, "grossProfit": 300.0},
            {"netIncome": 100.0, "revenue": 1000.0, "grossProfit": 500.0},
        ],
        "balance_sheets": [
            {
                "totalAssets": 1100.0,
                "longTermDebt": 300.0,
                "totalCurrentAssets": 400.0,
                "totalCurrentLiabilities": 400.0,
                "commonStockSharesOutstanding": 120.0,
            },
            {
                "totalAssets": 1000.0,
                "longTermDebt": 200.0,
                "totalCurrentAssets": 500.0,
                "totalCurrentLiabilities": 300.0,
                "commonStockSharesOutstanding": 100.0,
            },
        ],
        "cash_flows": [{"operatingCashFlow": -20.0}],
    }
    res = FScoreCheck()(_ctx(fundamentals))
    assert res.value is not None
    assert res.value < THRESHOLD
    assert res.passed is False
    assert res.signal == "weak"


def test_missing_data_returns_none() -> None:
    res = FScoreCheck()(_ctx({}))
    assert res.value is None
    assert res.passed is None
    assert res.signal == "insufficient_data"
    assert res.threshold == 6.0


def test_insufficient_history_returns_none() -> None:
    # Only one period of statements -> cannot compute YoY signals.
    fundamentals: dict[str, object] = {
        "income_statements": [{"netIncome": 100.0, "revenue": 1000.0}],
        "balance_sheets": [{"totalAssets": 1000.0}],
    }
    res = FScoreCheck()(_ctx(fundamentals))
    assert res.passed is None
    assert res.signal == "insufficient_data"


def test_garbage_precomputed_falls_back_to_none() -> None:
    res = FScoreCheck()(_ctx({"f_score": "not-a-number"}))
    assert res.value is None
    assert res.passed is None
    assert res.signal == "insufficient_data"


def test_compute_returns_none_on_short_history() -> None:
    assert compute_fscore([{"netIncome": 1.0}], [], None) is None
    assert compute_fscore(None, None, None) is None
