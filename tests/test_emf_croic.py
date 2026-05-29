# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic tests for EMF Check 1 — CROIC.

No network. Builds ``ScoringContext`` instances from fixture dicts and asserts
the pass / fail / missing-data behaviour ported from pw-nexus.
"""

from __future__ import annotations

from nexus_core.engine.scoring import CheckResult, ScoringContext
from nexus_core.engine.scoring.emf.croic import (
    BASELINE_THRESHOLD,
    CROICCheck,
    compute_croic,
)


def _ctx(**fundamentals: object) -> ScoringContext:
    return ScoringContext(ticker="TEST", fundamentals=dict(fundamentals))


def test_threshold_is_eight_percent() -> None:
    assert BASELINE_THRESHOLD == 0.08


def test_precomputed_pass() -> None:
    """Precomputed CROIC above 8% passes."""
    result = CROICCheck()(_ctx(croic=0.12))
    assert isinstance(result, CheckResult)
    assert result.check_number == 1
    assert result.name == "CROIC"
    assert result.value == 0.12
    assert result.threshold == 0.08
    assert result.passed is True
    assert result.signal == "solid"


def test_precomputed_strong_signal_above_fifteen_percent() -> None:
    result = CROICCheck()(_ctx(croic=0.20))
    assert result.passed is True
    assert result.signal == "strong"
    assert "Strong" in result.interpretation


def test_precomputed_fail_below_threshold() -> None:
    """A positive-but-weak CROIC fails the 8% gate."""
    result = CROICCheck()(_ctx(croic=0.05))
    assert result.passed is False
    assert result.signal == "weak"


def test_negative_croic_fails_with_negative_signal() -> None:
    result = CROICCheck()(_ctx(croic=-0.03))
    assert result.passed is False
    assert result.signal == "negative"


def test_exactly_at_threshold_does_not_pass() -> None:
    """Pass rule is strict ``> threshold``; equality is a fail."""
    result = CROICCheck()(_ctx(croic=0.08))
    assert result.passed is False


def test_missing_data_yields_passed_none() -> None:
    """No precomputed value and no statements -> best-effort insufficient_data."""
    result = CROICCheck()(_ctx())
    assert result.value is None
    assert result.passed is None
    assert result.signal == "insufficient_data"


def test_garbage_precomputed_value_falls_back_to_none() -> None:
    result = CROICCheck()(_ctx(croic="not-a-number"))
    assert result.value is None
    assert result.passed is None
    assert result.signal == "insufficient_data"


def test_compute_from_raw_statements() -> None:
    """FCF = OCF - |CapEx|; IC = equity + debt (cash NOT subtracted)."""
    cf = {"operatingCashFlow": 1000.0, "capitalExpenditures": -200.0}
    bs = {"totalStockholdersEquity": 5000.0, "totalDebt": 1000.0}
    # FCF = 1000 + (-200) = 800; IC = 5000 + 1000 = 6000; CROIC = 0.1333
    croic = compute_croic(cf, bs)
    assert croic is not None
    assert round(croic, 4) == 0.1333

    result = CROICCheck()(
        ScoringContext(
            ticker="RAW",
            fundamentals={"cash_flows": [cf], "balance_sheets": [bs]},
        )
    )
    assert result.value == 0.1333
    assert result.passed is True
    assert result.signal == "solid"


def test_compute_capex_positive_sign_convention() -> None:
    """Positive CapEx (absolute magnitude) is subtracted."""
    cf = {"operatingCashFlow": 1000.0, "capitalExpenditures": 200.0}
    bs = {"totalStockholdersEquity": 5000.0, "totalDebt": 1000.0}
    # FCF = 1000 - 200 = 800; same IC -> 0.1333
    assert compute_croic(cf, bs) == 0.1333


def test_compute_does_not_subtract_cash() -> None:
    """Regression: Jan-2026 fix — cash must NOT reduce invested capital."""
    cf = {"operatingCashFlow": 600.0, "capitalExpenditures": -100.0}
    bs = {
        "totalStockholdersEquity": 4000.0,
        "totalDebt": 1000.0,
        "cashAndCashEquivalents": 3000.0,
    }
    # IC = 4000 + 1000 = 5000 (cash ignored). FCF = 500. CROIC = 0.10
    assert compute_croic(cf, bs) == 0.10


def test_compute_handles_raw_envelope() -> None:
    """Provider {"raw": ...} envelopes are unwrapped."""
    cf = {"operatingCashFlow": {"raw": 1000.0}, "capitalExpenditures": {"raw": -200.0}}
    bs = {"totalStockholdersEquity": {"raw": 5000.0}, "totalDebt": {"raw": 1000.0}}
    assert compute_croic(cf, bs) == 0.1333


def test_compute_missing_inputs_returns_none() -> None:
    assert compute_croic(None, None) is None
    assert compute_croic({}, {}) is None
    # Non-positive equity -> None
    assert compute_croic(
        {"operatingCashFlow": 100.0},
        {"totalStockholdersEquity": 0.0, "totalDebt": 50.0},
    ) is None


def test_sector_adjustment_lowers_threshold() -> None:
    """A competitive-sector multiplier < 1 lets a sub-8% CROIC pass."""
    ctx = ScoringContext(
        ticker="TECH",
        fundamentals={"croic": 0.07},
        extra={"croic_sector_adjustment": 0.85},
    )
    result = CROICCheck()(ctx)
    # adjusted threshold = 0.08 * 0.85 = 0.068; 0.07 > 0.068 -> pass
    assert result.passed is True
    assert result.details["adjusted_threshold"] == 0.068
    assert result.details["sector_adjusted"] is True


def test_sector_adjustment_raises_threshold() -> None:
    """A stable-sector multiplier > 1 fails a borderline CROIC."""
    ctx = ScoringContext(
        ticker="UTIL",
        fundamentals={"croic": 0.09},
        extra={"croic_sector_adjustment": 1.20},
    )
    result = CROICCheck()(ctx)
    # adjusted threshold = 0.096; 0.09 < 0.096 -> fail
    assert result.passed is False
