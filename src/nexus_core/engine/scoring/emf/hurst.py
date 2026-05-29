# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF Check 3 — Hurst exponent (trend persistence).

Faithful port of pw-nexus ``_check_hurst`` (``portfolio_engine.py``) plus the
``calculate_hurst`` Rescaled-Range (R/S) estimator (``enhanced_metrics.py``).

The Hurst exponent ``H`` classifies the long-memory of a price series:

* ``H > 0.55`` — persistent trend, momentum favored (GREEN)
* ``0.45 < H <= 0.55`` — random walk, no clear trend (YELLOW)
* ``H <= 0.45`` — mean-reverting, contrarian favored (RED)

Threshold (pass rule): ``H > 0.55``.

Source: Hurst (1951) / Mandelbrot (1960s-70s).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..checks import CheckResult, ScoringContext

__all__ = ["HurstCheck", "compute_hurst"]

# Default R/S analysis parameters (match pw-nexus calculate_hurst).
_MIN_LAGS = 10
_MAX_LAGS = 100
# Multi-window analysis: short / mid / long horizons (trading days).
_WINDOWS = (7, 30, 90)
# Minimum points required per window when running the multi-window path.
_WINDOW_MIN_POINTS = 20
# Minimum series length before multi-window analysis is attempted.
_MULTI_WINDOW_MIN = 50
# Momentum-divergence trigger: |short H - long H| at or above this gap.
_DIVERGENCE_DELTA = 0.15


def compute_hurst(
    prices: list[float],
    *,
    min_lags: int = _MIN_LAGS,
    max_lags: int = _MAX_LAGS,
    min_points: int = 50,
) -> float | None:
    """Hurst exponent via Rescaled Range (R/S) analysis.

    Faithful port of pw-nexus ``calculate_hurst``: log returns, R/S over a
    range of lags, log-log linear regression slope, clamped to ``[0, 1]``.

    Args:
        prices: Closing prices, oldest to newest.
        min_lags: Minimum lag for the R/S sweep.
        max_lags: Maximum lag for the R/S sweep.
        min_points: Minimum number of prices required (else ``None``).

    Returns:
        The Hurst exponent rounded to 4 dp, or ``None`` if it can't be computed
        (too few points, degenerate variance, regression underdetermined).
    """
    if not prices or len(prices) < min_points:
        return None

    try:
        arr = np.asarray(prices, dtype=np.float64)
        if np.any(arr <= 0):
            # Log returns require strictly positive prices.
            return None

        returns = np.log(arr[1:] / arr[:-1])
        returns = returns[~np.isnan(returns)]
        if len(returns) < min_points:
            return None

        max_lag = min(max_lags, len(returns) // 2)
        rs_values: list[tuple[int, float]] = []
        for lag in range(min_lags, max_lag):
            rs_lag: list[float] = []
            for i in range(0, len(returns) - lag, lag):
                chunk = returns[i : i + lag]
                if len(chunk) < lag:
                    continue
                mean = float(np.mean(chunk))
                cumdev = np.cumsum(chunk - mean)
                rng = float(np.max(cumdev) - np.min(cumdev))
                std = float(np.std(chunk, ddof=1))
                if std > 1e-10:
                    rs_lag.append(rng / std)
            if rs_lag:
                rs_values.append((lag, float(np.mean(rs_lag))))

        if len(rs_values) < 5:
            return None

        log_lags = np.log([float(x[0]) for x in rs_values])
        log_rs = np.log([x[1] for x in rs_values])
        coeffs = np.polyfit(log_lags, log_rs, 1)
        hurst = float(coeffs[0])
        hurst = max(0.0, min(1.0, hurst))
        return round(hurst, 4)
    except Exception:
        # Best-effort: never throw from a check helper.
        return None


def _extract_closes(prices: list[dict[str, Any]]) -> list[float]:
    """Pull closing prices (oldest to newest) from a list of price bars."""
    closes: list[float] = []
    for bar in prices:
        if not isinstance(bar, dict):
            continue
        raw = bar.get("close", bar.get("Close"))
        if raw is None:
            continue
        try:
            closes.append(float(raw))
        except (TypeError, ValueError):
            continue
    return closes


def _multi_window_hurst(
    closes: list[float],
) -> tuple[float | None, str | None]:
    """Multi-window (7/30/90-day) Hurst with momentum-divergence detection.

    Primary value is the 90-day Hurst (falls back to 30-day), matching
    pw-nexus ``_check_hurst``.

    Returns:
        ``(value, momentum_divergence)`` where ``momentum_divergence`` is
        ``"breakout_candidate"``, ``"reversion_candidate"`` or ``None``.
    """
    window_results: dict[int, float] = {}
    for w in _WINDOWS:
        window_prices = closes[-w:] if w < len(closes) else closes
        if len(window_prices) >= _WINDOW_MIN_POINTS:
            result = compute_hurst(window_prices, min_points=_WINDOW_MIN_POINTS)
            if result is not None:
                window_results[w] = result

    value: float | None = None
    if 90 in window_results:
        value = window_results[90]
    elif 30 in window_results:
        value = window_results[30]

    momentum_divergence: str | None = None
    if 7 in window_results and (90 in window_results or 30 in window_results):
        long_h = window_results.get(90, window_results.get(30, 0.5))
        short_h = window_results[7]
        if abs(short_h - long_h) >= _DIVERGENCE_DELTA:
            momentum_divergence = (
                "breakout_candidate" if short_h > long_h else "reversion_candidate"
            )

    return value, momentum_divergence


class HurstCheck:
    """EMF Check 3 — Hurst exponent (trend persistence), pass rule ``H > 0.55``.

    Resolution order for the Hurst value:

    1. Precomputed ``ctx.fundamentals["hurst"]`` (or ``ctx.extra["hurst"]``).
    2. Multi-window R/S analysis over ``ctx.prices`` (needs >= 50 bars).

    Degrades to ``passed=None`` / ``signal="insufficient_data"`` when neither a
    precomputed value nor enough price history is available.
    """

    def __init__(self, threshold: float = 0.55) -> None:
        self.threshold = threshold

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        value: float | None = None
        momentum_divergence: str | None = None

        # 1. Precomputed value wins (fundamentals first, then extra).
        precomputed = ctx.fundamentals.get("hurst")
        if precomputed is None:
            precomputed = ctx.extra.get("hurst")
        if precomputed is not None:
            try:
                value = float(precomputed)
            except (TypeError, ValueError):
                value = None

        # 2. Otherwise compute from raw prices via multi-window R/S analysis.
        if value is None and ctx.prices:
            closes = _extract_closes(ctx.prices)
            if len(closes) >= _MULTI_WINDOW_MIN:
                value, momentum_divergence = _multi_window_hurst(closes)

        details: dict[str, Any] = {}
        if momentum_divergence:
            details["momentum_divergence"] = momentum_divergence

        if value is None:
            return CheckResult(
                check_number=3,
                name="Hurst",
                value=None,
                threshold=self.threshold,
                passed=None,
                signal="insufficient_data",
                interpretation="Hurst data unavailable",
                details=details,
            )

        passed = value > self.threshold
        if value > self.threshold:
            signal = "GREEN"
            interp = f"Persistent trend - momentum favored (H={value:.3f})"
        elif value > 0.45:
            signal = "YELLOW"
            interp = f"Random walk - no clear trend (H={value:.3f})"
        else:
            signal = "RED"
            interp = f"Mean-reverting - contrarian favored (H={value:.3f})"

        if momentum_divergence:
            interp += f" | Momentum divergence: {momentum_divergence}"

        return CheckResult(
            check_number=3,
            name="Hurst",
            value=value,
            threshold=self.threshold,
            passed=passed,
            signal=signal,
            interpretation=interp,
            details=details,
        )

