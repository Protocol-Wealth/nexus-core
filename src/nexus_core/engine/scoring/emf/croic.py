# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF Check 1 — CROIC (Cash Return on Invested Capital).

Cash generation quality. Ported faithfully from the private pw-nexus engine
(``app/engine/data/enhanced_metrics.calculate_croic`` for the computation and
``app/engine/portfolio_engine._check_croic`` for the threshold / signal logic).

Methodology
-----------
``CROIC = Free Cash Flow / Invested Capital``

* Free Cash Flow ``FCF = Operating Cash Flow - |CapEx|`` (sign-convention safe:
  if CapEx is reported as a negative cash outflow it is added, otherwise the
  absolute value is subtracted).
* Invested Capital ``= Total Equity + Total Debt``. Cash is **not** subtracted
  (Jan 2026 fix in pw-nexus — subtracting cash overstated CROIC ~2x).

Threshold
---------
Baseline pass rule: ``CROIC > 0.08`` (8%). pw-nexus optionally scales this
threshold by a per-sector "competitive intensity" multiplier
(``SECTOR_QUALITY_MULTIPLIERS``). That sector-model layer is *upstream* and not
yet part of nexus-core's ``ScoringContext``; this check honours a precomputed
multiplier if one is supplied via ``ctx.extra["croic_sector_adjustment"]`` and
otherwise uses the unadjusted 8% baseline.

Source: Greenblatt / quality-investing tradition (see ``attribution.py``).
"""

from __future__ import annotations

from typing import Any

from ..checks import CheckResult, ScoringContext

#: Baseline CROIC pass threshold (8%). Mirrors pw-nexus
#: ``portfolio_engine._CROIC_BASELINE_THRESHOLD``.
BASELINE_THRESHOLD: float = 0.08

#: Field name aliases for raw-statement computation, matching the provider
#: key variants accepted by pw-nexus ``calculate_croic`` / data adapters.
_OCF_KEYS = (
    "operatingCashFlow",
    "totalCashFromOperatingActivities",
    "operating_cash_flow",
    "netCashProvidedByOperatingActivities",
    "cashFromOperations",
    "cashFlowFromOperatingActivities",
    "netCashFromOperations",
    "cashGeneratedFromOperations",
)
_CAPEX_KEYS = (
    "capitalExpenditures",
    "capitalExpenditure",
    "capex",
    "capital_expenditure",
    "purchaseOfPropertyPlantAndEquipment",
)
_EQUITY_KEYS = (
    "totalStockholdersEquity",
    "totalShareholderEquity",
    "totalEquity",
    "stockholdersEquity",
    "total_stockholders_equity",
    "total_equity",
    "equity",
)
_DEBT_KEYS = (
    "totalDebt",
    "total_debt",
    "longTermDebt",
    "long_term_debt",
    "shortLongTermDebt",
    "longTermDebtNoncurrent",
)


def _extract(record: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    """Return the first present numeric value among ``keys``.

    Unwraps ``{"raw": ...}`` provider envelopes. Returns ``None`` if no key is
    present or the value is non-numeric.
    """
    for key in keys:
        value = record.get(key)
        if isinstance(value, dict):
            value = value.get("raw")
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def compute_croic(
    cash_flow: dict[str, Any] | None,
    balance_sheet: dict[str, Any] | None,
) -> float | None:
    """Compute CROIC from a single-period cash-flow and balance-sheet dict.

    Faithful to pw-nexus ``enhanced_metrics.calculate_croic``:

    * ``FCF = OCF - |CapEx|`` with sign-convention handling.
    * ``Invested Capital = Total Equity + Total Debt`` (cash NOT subtracted).

    Returns ``None`` when inputs are missing or invested capital is non-positive.
    Pure, no I/O — never raises.
    """
    if not cash_flow or not balance_sheet:
        return None
    try:
        ocf = _extract(cash_flow, _OCF_KEYS)
        if ocf is None:
            return None

        capex_raw = _extract(cash_flow, _CAPEX_KEYS)
        if capex_raw is None:
            # No CapEx data — approximate FCF with OCF (pw-nexus fallback).
            fcf = ocf
        elif capex_raw < 0:
            # Already a cash outflow: FCF = OCF + capex (capex negative).
            fcf = ocf + capex_raw
        else:
            # Absolute magnitude: subtract it.
            fcf = ocf - capex_raw

        equity = _extract(balance_sheet, _EQUITY_KEYS)
        if equity is None or equity <= 0:
            return None
        debt = _extract(balance_sheet, _DEBT_KEYS) or 0.0

        invested_capital = equity + debt  # cash intentionally NOT subtracted
        if invested_capital <= 0:
            return None

        return round(fcf / invested_capital, 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


class CROICCheck:
    """EMF Check 1 — Cash Return on Invested Capital.

    Reads a precomputed ``ctx.fundamentals["croic"]`` if present; otherwise
    computes from raw ``cash_flows`` / ``balance_sheets`` statement lists
    (most-recent-first) via :func:`compute_croic`. Best-effort: when no value
    can be derived, returns ``passed=None`` with ``signal="insufficient_data"``.
    """

    def __init__(self, threshold: float = BASELINE_THRESHOLD) -> None:
        self.threshold = threshold

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        fundamentals = ctx.fundamentals
        details: dict[str, Any] = {}

        # 1. Prefer a precomputed value.
        value = fundamentals.get("croic")
        if value is not None:
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = None

        # 2. Otherwise compute from raw statements (most-recent first).
        if value is None:
            cash_flows = fundamentals.get("cash_flows") or []
            balance_sheets = fundamentals.get("balance_sheets") or []
            cf = cash_flows[0] if cash_flows else None
            bs = balance_sheets[0] if balance_sheets else None
            value = compute_croic(cf, bs)

        # 3. Insufficient data -> passed=None (never throw).
        if value is None:
            return CheckResult(
                check_number=1,
                name="CROIC",
                value=None,
                threshold=self.threshold,
                passed=None,
                signal="insufficient_data",
                interpretation="CROIC data unavailable",
                details=details,
            )

        # Optional upstream sector-intensity adjustment (default: unadjusted).
        adjustment = ctx.extra.get("croic_sector_adjustment")
        adjusted_threshold = self.threshold
        if isinstance(adjustment, (int, float)) and adjustment > 0:
            adjusted_threshold = self.threshold * float(adjustment)
            details["sector_adjusted"] = True
            details["sector_adjustment"] = float(adjustment)
            details["baseline_threshold"] = self.threshold
            details["adjusted_threshold"] = adjusted_threshold

        passed = value > adjusted_threshold

        if value > 0.15:
            signal = "strong"
            interpretation = f"Strong cash generation ({value:.1%})"
        elif value > adjusted_threshold:
            signal = "solid"
            interpretation = f"Solid cash generation ({value:.1%})"
        elif value > 0.0:
            signal = "weak"
            interpretation = f"Weak cash generation ({value:.1%})"
        else:
            signal = "negative"
            interpretation = f"Negative cash generation ({value:.1%})"

        return CheckResult(
            check_number=1,
            name="CROIC",
            value=value,
            threshold=adjusted_threshold,
            passed=passed,
            signal=signal,
            interpretation=interpretation,
            details=details,
        )


__all__ = ["BASELINE_THRESHOLD", "CROICCheck", "compute_croic"]
