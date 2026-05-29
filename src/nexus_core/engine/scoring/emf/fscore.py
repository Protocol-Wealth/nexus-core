# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF Check #2 — Piotroski F-Score (financial-health screen).

Faithful port of the pw-nexus canonical scoring path. The F-Score is a
0-9 integer tally of nine binary fundamental signals (Piotroski, *Value
Investing: The Use of Historical Financial Statement Information to
Separate Winners from Losers*, Journal of Accounting Research, 2000).

A ticker passes when the score is **>= 6**.

Computation mirrors ``PortfolioScorer._compute_fscore_from_fundamentals``
in pw-nexus ``app/engine/portfolio_engine.py`` (the path actually wired
into live scoring), not the tolerance-augmented standalone calculator.
The nine signals:

  Profitability (4)
    1. ROA positive ........... net income > 0
    2. Operating CF positive .. operating cash flow > 0
    3. ROA improving .......... ROA(t) > ROA(t-1)
    4. Accrual quality ........ operating CF > net income
  Leverage / Liquidity / Source of funds (3)
    5. Leverage decreasing .... long-term debt / assets falling (here: LTD falling)
    6. Current ratio improving  CR(t) > CR(t-1)
    7. No dilution ............ shares(t) <= shares(t-1)
  Operating efficiency (2)
    8. Gross margin improving . GM(t) > GM(t-1)
    9. Asset turnover improving turnover(t) > turnover(t-1)

The check first reads a precomputed value from ``ctx.fundamentals``
(keys ``f_score`` / ``fscore``); failing that it computes the score from
raw statement lists via :func:`compute_fscore`.
"""

from __future__ import annotations

from typing import Any

from ..checks import CheckResult, ScoringContext

THRESHOLD = 6
"""Pass when F-Score >= 6 (Piotroski; pw-nexus canonical threshold)."""


def _num(d: dict[str, Any], *keys: str) -> float:
    """Pull the first present numeric field from a statement row.

    Handles the pw-nexus convention where a value may be wrapped as
    ``{"raw": <number>}`` (FMP/provider envelope). Returns ``0.0`` when no
    key is present or convertible, matching the upstream ``_v`` helper.
    """
    for k in keys:
        v = d.get(k)
        if isinstance(v, dict):
            v = v.get("raw")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def compute_fscore(
    income_statements: list[dict[str, Any]] | None,
    balance_sheets: list[dict[str, Any]] | None,
    cash_flows: list[dict[str, Any]] | None,
) -> int | None:
    """Compute the Piotroski 9-point F-Score from raw statement lists.

    Each list is most-recent-first (index 0 = current FY, index 1 = prior FY).
    Returns the integer score 0-9, or ``None`` when there is insufficient
    history (fewer than two income statements or balance sheets).

    Mirrors ``_compute_fscore_from_fundamentals`` in pw-nexus
    ``portfolio_engine.py``. Cash-flow history is optional; an absent cash
    flow row simply fails the two CF-dependent signals.
    """
    incs = income_statements or []
    bss = balance_sheets or []
    cfs = cash_flows or []
    if len(incs) < 2 or len(bss) < 2:
        return None

    try:
        inc_curr, inc_prev = incs[0], incs[1]
        bs_curr, bs_prev = bss[0], bss[1]
        cf = cfs[0] if cfs else {}

        net_income = _num(inc_curr, "netIncome", "net_income")
        net_income_prev = _num(inc_prev, "netIncome", "net_income")
        assets_curr = _num(bs_curr, "totalAssets", "total_assets")
        assets_prev = _num(bs_prev, "totalAssets", "total_assets")
        avg_assets = (
            (assets_curr + assets_prev) / 2 if (assets_curr + assets_prev) > 0 else 1.0
        )
        ocf = _num(
            cf,
            "operatingCashFlow",
            "operating_cash_flow",
            "netCashProvidedByOperatingActivities",
        )
        revenue_curr = _num(inc_curr, "revenue", "totalRevenue")
        revenue_prev = _num(inc_prev, "revenue", "totalRevenue")
        gp_curr = _num(inc_curr, "grossProfit", "gross_profit")
        gp_prev = _num(inc_prev, "grossProfit", "gross_profit")
        ltd_curr = _num(bs_curr, "longTermDebt", "long_term_debt")
        ltd_prev = _num(bs_prev, "longTermDebt", "long_term_debt")
        cl_curr = _num(bs_curr, "totalCurrentLiabilities", "total_current_liabilities")
        cl_prev = _num(bs_prev, "totalCurrentLiabilities", "total_current_liabilities")
        ca_curr = _num(bs_curr, "totalCurrentAssets", "total_current_assets")
        ca_prev = _num(bs_prev, "totalCurrentAssets", "total_current_assets")
        shares_curr = _num(bs_curr, "commonStockSharesOutstanding", "shares_outstanding")
        shares_prev = _num(bs_prev, "commonStockSharesOutstanding", "shares_outstanding")

        score = 0
        # 1. ROA positive (net income > 0)
        if net_income > 0:
            score += 1
        # 2. Operating cash flow positive
        if ocf > 0:
            score += 1
        # 3. ROA increasing
        roa_curr = net_income / avg_assets if avg_assets else 0.0
        roa_prev = net_income_prev / assets_prev if assets_prev else 0.0
        if roa_curr > roa_prev:
            score += 1
        # 4. Cash flow > net income (accrual quality)
        if ocf > net_income:
            score += 1
        # 5. Long-term debt decreasing
        if ltd_curr < ltd_prev:
            score += 1
        # 6. Current ratio improving
        cr_curr = ca_curr / cl_curr if cl_curr else 999.0
        cr_prev = ca_prev / cl_prev if cl_prev else 999.0
        if cr_curr > cr_prev:
            score += 1
        # 7. No dilution
        if shares_curr <= shares_prev or shares_prev == 0:
            score += 1
        # 8. Gross margin improving
        gm_curr = gp_curr / revenue_curr if revenue_curr else 0.0
        gm_prev = gp_prev / revenue_prev if revenue_prev else 0.0
        if gm_curr > gm_prev:
            score += 1
        # 9. Asset turnover improving
        at_curr = revenue_curr / avg_assets if avg_assets else 0.0
        at_prev = revenue_prev / assets_prev if assets_prev else 0.0
        if at_curr > at_prev:
            score += 1

        return score
    except Exception:  # pragma: no cover - defensive, mirrors upstream
        return None


class FScoreCheck:
    """EMF Check #2 — Piotroski F-Score >= 6.

    Resolution order for the score:
      1. ``ctx.fundamentals["f_score"]`` (or ``"fscore"``) if present.
      2. :func:`compute_fscore` over ``income_statements`` /
         ``balance_sheets`` / ``cash_flows`` in ``ctx.fundamentals``.

    Degrades to ``passed=None`` / ``signal="insufficient_data"`` when
    neither a precomputed value nor at least two periods of income and
    balance-sheet data are available. (pw-nexus marks the missing case
    ``passed=False``; the nexus-core contract requires ``passed=None`` for
    missing data, so this port follows the nexus-core contract.)
    """

    def __init__(self, threshold: int = THRESHOLD) -> None:
        self.threshold = threshold

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        fund = ctx.fundamentals
        raw = fund.get("f_score", fund.get("fscore"))

        score: int | None
        if raw is not None:
            try:
                score = int(raw)
            except (TypeError, ValueError):
                score = None
        else:
            score = compute_fscore(
                fund.get("income_statements"),
                fund.get("balance_sheets"),
                fund.get("cash_flows"),
            )

        if score is None:
            return CheckResult(
                check_number=2,
                name="F-Score",
                value=None,
                threshold=float(self.threshold),
                passed=None,
                signal="insufficient_data",
                interpretation="F-Score data unavailable",
            )

        passed = score >= self.threshold
        if score >= 7:
            signal = "strong"
            interp = f"Strong fundamentals ({score}/9)"
        elif score >= 5:
            signal = "average"
            interp = f"Average fundamentals ({score}/9)"
        else:
            signal = "weak"
            interp = f"Weak fundamentals ({score}/9)"

        return CheckResult(
            check_number=2,
            name="F-Score",
            value=float(score),
            threshold=float(self.threshold),
            passed=passed,
            signal=signal,
            interpretation=interp,
            details={"score": score, "max": 9},
        )


__all__ = ["FScoreCheck", "compute_fscore", "THRESHOLD"]
