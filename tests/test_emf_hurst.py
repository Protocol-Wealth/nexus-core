# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic tests for EMF Check 3 — Hurst exponent (trend persistence)."""

from __future__ import annotations

import numpy as np

from nexus_core.engine.scoring import ScoringContext
from nexus_core.engine.scoring.emf.hurst import HurstCheck, compute_hurst


def _bars(closes: list[float]) -> list[dict[str, float]]:
    return [{"close": c} for c in closes]


def _trending_closes(n: int = 260, drift: float = 0.004, seed: int = 7) -> list[float]:
    """A strongly persistent (trending) series -> high Hurst."""
    rng = np.random.default_rng(seed)
    # Small noise on a steady upward drift produces H well above 0.55.
    steps = drift + rng.normal(0.0, 0.001, size=n)
    return list(100.0 * np.exp(np.cumsum(steps)))


def _mean_reverting_closes(n: int = 260, seed: int = 11) -> list[float]:
    """An anti-persistent (oscillating) series -> low Hurst."""
    rng = np.random.default_rng(seed)
    closes = [100.0]
    for _ in range(n - 1):
        # Pull back toward the mean each step -> negative autocorrelation.
        pull = (100.0 - closes[-1]) * 0.6
        closes.append(closes[-1] + pull + rng.normal(0.0, 0.5))
    return closes


# ---------------- compute_hurst helper ----------------


def test_compute_hurst_trending_is_high() -> None:
    h = compute_hurst(_trending_closes())
    assert h is not None
    assert h > 0.55


def test_compute_hurst_mean_reverting_is_low() -> None:
    h = compute_hurst(_mean_reverting_closes())
    assert h is not None
    assert h < 0.55


def test_compute_hurst_clamped_and_rounded() -> None:
    h = compute_hurst(_trending_closes())
    assert h is not None
    assert 0.0 <= h <= 1.0
    # Rounded to 4 dp.
    assert h == round(h, 4)


def test_compute_hurst_insufficient_points() -> None:
    assert compute_hurst([100.0, 101.0, 102.0]) is None


def test_compute_hurst_rejects_nonpositive_prices() -> None:
    closes = _trending_closes()
    closes[10] = 0.0
    assert compute_hurst(closes) is None


# ---------------- HurstCheck — pass / fail / missing ----------------


def test_check_passes_on_trending_prices() -> None:
    ctx = ScoringContext(ticker="TREND", prices=_bars(_trending_closes()))
    result = HurstCheck()(ctx)
    assert result.check_number == 3
    assert result.name == "Hurst"
    assert result.value is not None
    assert result.value > 0.55
    assert result.passed is True
    assert result.signal == "GREEN"


def test_check_fails_on_mean_reverting_prices() -> None:
    ctx = ScoringContext(ticker="REVERT", prices=_bars(_mean_reverting_closes()))
    result = HurstCheck()(ctx)
    assert result.value is not None
    assert result.value <= 0.55
    assert result.passed is False
    assert result.signal in {"YELLOW", "RED"}


def test_check_precomputed_value_passes() -> None:
    ctx = ScoringContext(ticker="PRE", fundamentals={"hurst": 0.62})
    result = HurstCheck()(ctx)
    assert result.value == 0.62
    assert result.passed is True
    assert result.signal == "GREEN"
    assert "H=0.620" in result.interpretation


def test_check_precomputed_value_fails_mean_reverting() -> None:
    ctx = ScoringContext(ticker="PRE", fundamentals={"hurst": 0.40})
    result = HurstCheck()(ctx)
    assert result.value == 0.40
    assert result.passed is False
    assert result.signal == "RED"


def test_check_precomputed_random_walk_is_yellow_and_fails() -> None:
    ctx = ScoringContext(ticker="PRE", fundamentals={"hurst": 0.50})
    result = HurstCheck()(ctx)
    assert result.passed is False
    assert result.signal == "YELLOW"


def test_check_threshold_is_exclusive_at_055() -> None:
    # Exactly 0.55 must NOT pass (rule is strictly > 0.55).
    ctx = ScoringContext(ticker="EDGE", fundamentals={"hurst": 0.55})
    result = HurstCheck()(ctx)
    assert result.passed is False
    assert result.signal == "YELLOW"


def test_check_fundamentals_value_beats_extra() -> None:
    ctx = ScoringContext(
        ticker="BOTH",
        fundamentals={"hurst": 0.62},
        extra={"hurst": 0.10},
    )
    result = HurstCheck()(ctx)
    assert result.value == 0.62


def test_check_extra_value_used_when_no_fundamentals() -> None:
    ctx = ScoringContext(ticker="X", extra={"hurst": 0.62})
    result = HurstCheck()(ctx)
    assert result.value == 0.62
    assert result.passed is True


def test_check_missing_data_returns_none() -> None:
    ctx = ScoringContext(ticker="EMPTY")
    result = HurstCheck()(ctx)
    assert result.value is None
    assert result.passed is None
    assert result.signal == "insufficient_data"
    assert result.threshold == 0.55


def test_check_too_few_bars_returns_none() -> None:
    ctx = ScoringContext(ticker="SHORT", prices=_bars([100.0 + i for i in range(20)]))
    result = HurstCheck()(ctx)
    assert result.value is None
    assert result.passed is None
    assert result.signal == "insufficient_data"


def test_check_garbage_prices_returns_none() -> None:
    bars: list[dict[str, object]] = [{"close": "n/a"} for _ in range(60)]
    ctx = ScoringContext(ticker="JUNK", prices=bars)
    result = HurstCheck()(ctx)
    assert result.value is None
    assert result.passed is None


def test_check_garbage_precomputed_falls_through_to_none() -> None:
    ctx = ScoringContext(ticker="JUNK", fundamentals={"hurst": "oops"})
    result = HurstCheck()(ctx)
    assert result.value is None
    assert result.passed is None


def test_check_custom_threshold() -> None:
    ctx = ScoringContext(ticker="C", fundamentals={"hurst": 0.58})
    # With a stricter 0.60 threshold, 0.58 fails.
    result = HurstCheck(threshold=0.60)(ctx)
    assert result.threshold == 0.60
    assert result.passed is False

