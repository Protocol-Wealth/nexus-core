# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF Check 8 — ASAN Screen (Structural Advantage).

The Adaptive Structural Advantage Number (ASAN) screen evaluates whether an
asset has a durable structural moat — and, for software, whether it is
resilient to AI disruption.

Two scoring paths, faithfully ported from the pw-nexus reference engine:

- **SaaS / software** uses the original *ASAN Trinity*: three vulnerability
  markers (low connectivity, seat-based pricing, discretionary spend). A
  ``vulnerability_score`` of 0-3 is computed; ``< 2`` markers passes ("SAFE").
- **Non-SaaS sectors** use a sector-specific *structural advantage* score:
  three factors per sector, ``0-3`` points, ``>= 2`` passes.
- **Unclassified sectors** auto-pass (the check is not applicable).

The numeric ``threshold`` on the returned ``CheckResult`` is the structural
gate ``2.0`` (out of a max of 3). The original descriptive threshold string
(e.g. ``"semiconductor: >=2/3 structural advantage"``) is preserved in
``details["threshold_desc"]`` since the nexus-core ``CheckResult.threshold``
field is numeric.

Reference: ``app/engine/asan_models.py`` and
``PortfolioEngine._check_asan_screen`` / ``check_asan_trinity`` in pw-nexus.
Lineage: Christensen disruption theory + sector-specific structural analysis.
"""

from __future__ import annotations

import math
from typing import Any

from ..checks import CheckResult, ScoringContext

# --- SaaS / ASAN Trinity ticker lists (ported from pw-nexus) ---------------

# Known low-connectivity SaaS (CRUD apps, shallow integrations).
ASAN_TRINITY_TICKERS: frozenset[str] = frozenset(
    {"ASAN", "MNDY", "SMAR", "ZM", "DOCU", "BOX", "FROG"}
)
# Seat-based pricing (vulnerable to AI headcount reduction).
SEAT_BASED_TICKERS: frozenset[str] = frozenset({"ASAN", "MNDY", "SMAR", "ZM", "DOCU"})
# Discretionary spend (first cut in a downturn).
DISCRETIONARY_TICKERS: frozenset[str] = frozenset({"ASAN", "MNDY", "SMAR", "BOX", "FROG"})

# SaaS detection keywords (industry field).
_SAAS_KEYWORDS: tuple[str, ...] = (
    "software",
    "saas",
    "application",
    "cloud",
    "information technology services",
    "cybersecurity",
    "internet content",
    "data processing",
)
_SAAS_TRINITY_INDUSTRY_KEYWORDS: tuple[str, ...] = (
    "collaboration",
    "project management",
    "productivity",
)

# --- Sector classification maps (ported from pw-nexus) ---------------------

SECTOR_SCORING_MAP: dict[str, str] = {
    "semiconductors": "semiconductor",
    "semiconductor equipment": "semiconductor",
    "semiconductor memory": "semiconductor",
    "electronic components": "semiconductor",
    "computer hardware": "semiconductor",
    "scientific & technical instruments": "semiconductor",
    "banks": "financial",
    "insurance": "financial",
    "diversified financial": "financial",
    "asset management": "financial",
    "capital markets": "financial",
    "credit services": "financial",
    "financial data": "financial",
    "financial exchanges": "financial",
    "financial conglomerates": "financial",
    "mortgage finance": "financial",
    "drug manufacturers": "healthcare",
    "biotechnology": "healthcare",
    "medical devices": "healthcare",
    "medical instruments": "healthcare",
    "health information": "healthcare",
    "diagnostics & research": "healthcare",
    "healthcare plans": "healthcare",
    "pharmaceutical": "healthcare",
    "medical care": "healthcare",
    "retail": "consumer",
    "restaurants": "consumer",
    "apparel": "consumer",
    "home improvement": "consumer",
    "specialty retail": "consumer",
    "discount stores": "consumer",
    "department stores": "consumer",
    "grocery": "consumer",
    "beverages": "consumer",
    "household products": "consumer",
    "packaged foods": "consumer",
    "personal products": "consumer",
    "confectioners": "consumer",
    "tobacco": "consumer",
    "aerospace & defense": "industrial",
    "industrial distribution": "industrial",
    "electrical equipment": "industrial",
    "machinery": "industrial",
    "farm & heavy construction": "industrial",
    "conglomerates": "industrial",
    "specialty industrial": "industrial",
    "building products": "industrial",
    "tools & accessories": "industrial",
    "auto manufacturers": "industrial",
    "auto parts": "industrial",
    "railroads": "industrial",
    "trucking": "industrial",
    "marine shipping": "industrial",
    "airlines": "industrial",
    "oil & gas": "energy",
    "oil & gas integrated": "energy",
    "oil & gas e&p": "energy",
    "oil & gas midstream": "energy",
    "oil & gas refining": "energy",
    "oil & gas equipment": "energy",
    "uranium": "energy",
    "solar": "energy",
    "renewable": "energy",
    "thermal coal": "energy",
}

SECTOR_FIELD_MAP: dict[str, str] = {
    "financial services": "financial",
    "financials": "financial",
    "healthcare": "healthcare",
    "consumer cyclical": "consumer",
    "consumer defensive": "consumer",
    "consumer discretionary": "consumer",
    "consumer staples": "consumer",
    "industrials": "industrial",
    "energy": "energy",
}

STRUCTURAL_THRESHOLD: int = 2  # >= 2 of 3 factors passes
MAX_STRUCTURAL_SCORE: int = 3


# --- Pure helpers ----------------------------------------------------------


def _safe_float(val: Any) -> float | None:
    """Coerce to float, rejecting None/NaN/Inf and non-numerics."""
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def classify_sector(sector: str | None, industry: str | None) -> str:
    """Classify into a scoring type.

    Returns one of: ``saas``, ``semiconductor``, ``financial``, ``healthcare``,
    ``consumer``, ``industrial``, ``energy`` or ``unknown``.
    """
    industry_lower = (industry or "").lower()
    sector_lower = (sector or "").lower()

    if any(kw in industry_lower for kw in _SAAS_KEYWORDS):
        return "saas"
    for keyword, stype in SECTOR_SCORING_MAP.items():
        if keyword in industry_lower:
            return stype
    for keyword, stype in SECTOR_FIELD_MAP.items():
        if keyword in sector_lower:
            return stype
    return "unknown"


def _rd_intensity(fundamentals: dict[str, Any]) -> float | None:
    """R&D / revenue from the most recent income statement, if present."""
    explicit = _safe_float(fundamentals.get("rd_intensity"))
    if explicit is not None:
        return explicit
    stmts = fundamentals.get("income_statements")
    if not isinstance(stmts, list) or not stmts:
        return None
    stmt = stmts[0]
    if not isinstance(stmt, dict):
        return None
    rd = (
        stmt.get("researchAndDevelopmentExpenses")
        or stmt.get("researchDevelopment")
        or stmt.get("rd")
    )
    rev = stmt.get("revenue") or stmt.get("totalRevenue")
    rd_f, rev_f = _safe_float(rd), _safe_float(rev)
    if rd_f is None or rev_f is None or rev_f <= 0:
        return None
    return rd_f / rev_f


def _trinity_score(ticker: str, industry: str) -> int:
    """ASAN Trinity vulnerability score (0-3) for SaaS. Higher = worse."""
    t = ticker.upper()
    industry_lower = industry.lower()
    low_connectivity = t in ASAN_TRINITY_TICKERS
    seat_based = t in SEAT_BASED_TICKERS
    discretionary = t in DISCRETIONARY_TICKERS
    if any(kw in industry_lower for kw in _SAAS_TRINITY_INDUSTRY_KEYWORDS):
        low_connectivity = True
        discretionary = True
    return int(low_connectivity) + int(seat_based) + int(discretionary)


# Per-sector factor gates: (key, threshold, comparator-is-greater-than).
# Each sector scores 1 point per satisfied factor; >= 2 passes.
def _structural_score(sector_type: str, fundamentals: dict[str, Any]) -> int:
    """Sector-specific structural advantage score (0-3). Higher = stronger."""
    gm = _safe_float(fundamentals.get("gross_margin"))
    rev_growth = _safe_float(fundamentals.get("revenue_growth"))
    market_cap = _safe_float(fundamentals.get("market_cap"))
    roe = _safe_float(fundamentals.get("roe"))
    op_margin = _safe_float(fundamentals.get("operating_margin"))
    earnings_growth = _safe_float(fundamentals.get("earnings_growth"))
    rd = _rd_intensity(fundamentals)
    score = 0

    if sector_type == "semiconductor":
        if gm is not None and gm > 0.50:
            score += 1
        if rev_growth is not None and rev_growth > 0.10 and rd is not None and rd > 0.15:
            score += 1
        if market_cap is not None and market_cap > 50_000_000_000:
            score += 1
    elif sector_type == "financial":
        if roe is not None and roe > 0.12:
            score += 1
        if op_margin is not None and op_margin > 0.30:
            score += 1
        if (
            market_cap is not None
            and market_cap > 20_000_000_000
            and earnings_growth is not None
            and earnings_growth > 0
        ):
            score += 1
    elif sector_type == "healthcare":
        if rd is not None and rd > 0.15:
            score += 1
        if rev_growth is not None and rev_growth > 0:
            score += 1
        if market_cap is not None and market_cap > 30_000_000_000:
            score += 1
    elif sector_type == "consumer":
        if rev_growth is not None and rev_growth > 0.03:
            score += 1
        if gm is not None and gm > 0.40:
            score += 1
        if market_cap is not None and market_cap > 20_000_000_000:
            score += 1
    elif sector_type == "industrial":
        if op_margin is not None and op_margin > 0.12:
            score += 1
        if rev_growth is not None and rev_growth > 0.05:
            score += 1
        if (
            market_cap is not None
            and market_cap > 30_000_000_000
            and rd is not None
            and rd > 0.03
        ):
            score += 1
    elif sector_type == "energy":
        if rev_growth is not None and rev_growth > 0:
            score += 1
        if op_margin is not None and op_margin > 0.15:
            score += 1
        if market_cap is not None and market_cap > 30_000_000_000:
            score += 1

    return score


class ASANScreenCheck:
    """EMF Check 8 — ASAN Screen (structural advantage / AI resilience).

    SaaS path: ASAN Trinity vulnerability (pass when ``< 2`` of 3 markers).
    Non-SaaS path: sector structural advantage (pass when ``>= 2`` of 3).
    Unclassified sectors auto-pass. Degrades to ``passed=None`` when neither
    a precomputed score nor any sector/industry classification data exists.
    """

    def __init__(self, threshold: int = STRUCTURAL_THRESHOLD) -> None:
        self.threshold = threshold

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        fundamentals = ctx.fundamentals or {}

        # Precomputed override (e.g. produced upstream by the full engine).
        pre = ctx.extra.get("asan_screen") if isinstance(ctx.extra, dict) else None
        if isinstance(pre, dict) and "passed" in pre:
            return self._from_precomputed(pre)

        sector = fundamentals.get("sector")
        industry = fundamentals.get("industry")

        # No classification data at all → can't evaluate (best-effort).
        if not sector and not industry:
            return CheckResult(
                check_number=8,
                name="ASAN Screen",
                value=None,
                threshold=float(self.threshold),
                passed=None,
                signal="insufficient_data",
                interpretation="No sector/industry data — ASAN Screen could not be evaluated.",
                details={"threshold_desc": "sector/industry required to classify"},
            )

        sector_type = classify_sector(sector, industry)
        ticker = ctx.ticker.upper()

        # SaaS may also be flagged by the explicit classification override list.
        is_saas = sector_type == "saas"
        explicit_saas = ctx.extra.get("asan_saas_override") if isinstance(ctx.extra, dict) else None
        if not is_saas and explicit_saas:
            is_saas = True

        if is_saas:
            return self._saas_result(ticker, str(industry or ""))
        if sector_type == "unknown":
            return self._auto_pass(sector_type)
        return self._sector_result(sector_type, fundamentals)

    # --- result builders ---------------------------------------------------

    def _saas_result(self, ticker: str, industry: str) -> CheckResult:
        vuln = _trinity_score(ticker, industry)
        passed = vuln < 2  # SAFE when fewer than 2 of 3 markers present
        if passed:
            signal, interp = "GREEN", f"Defensible against AI disruption ({vuln}/3 ASAN markers)"
        elif vuln == 2:
            signal, interp = "YELLOW", f"Moderate AI vulnerability ({vuln}/3 ASAN markers)"
        else:
            signal, interp = "RED", f"High AI disruption risk ({vuln}/3 ASAN markers)"
        return CheckResult(
            check_number=8,
            name="ASAN Screen",
            value=float(vuln),
            threshold=float(self.threshold),
            passed=passed,
            signal=signal,
            interpretation=interp,
            details={
                "applicable": True,
                "sector_type": "saas",
                "vulnerability_score": vuln,
                "max_score": MAX_STRUCTURAL_SCORE,
                "threshold_desc": "SaaS: <2/3 ASAN markers",
            },
        )

    def _sector_result(self, sector_type: str, fundamentals: dict[str, Any]) -> CheckResult:
        score = _structural_score(sector_type, fundamentals)
        passed = score >= self.threshold
        if passed:
            signal = "GREEN"
        elif score >= 1:
            signal = "YELLOW"
        else:
            signal = "RED"
        interp = (
            f"{sector_type.capitalize()} structural advantage: {score}/{MAX_STRUCTURAL_SCORE}"
            + (" — strong positioning" if passed else " — limited structural moat")
        )
        return CheckResult(
            check_number=8,
            name="ASAN Screen",
            value=float(score),
            threshold=float(self.threshold),
            passed=passed,
            signal=signal,
            interpretation=interp,
            details={
                "applicable": True,
                "sector_type": sector_type,
                "structural_score": score,
                "max_score": MAX_STRUCTURAL_SCORE,
                "threshold_desc": f"{sector_type}: >=2/3 structural advantage",
            },
        )

    def _auto_pass(self, sector_type: str) -> CheckResult:
        return CheckResult(
            check_number=8,
            name="ASAN Screen",
            value=None,
            threshold=float(self.threshold),
            passed=True,  # auto-pass for unclassified sectors
            signal="GREEN",
            interpretation=f"N/A — {sector_type} sector, auto-pass",
            details={
                "applicable": False,
                "sector_type": sector_type,
                "threshold_desc": "Sector-specific structural advantage",
            },
        )

    def _from_precomputed(self, pre: dict[str, Any]) -> CheckResult:
        passed = pre.get("passed")
        value = _safe_float(pre.get("value"))
        sector_type = str(pre.get("sector_type", ""))
        return CheckResult(
            check_number=8,
            name="ASAN Screen",
            value=value,
            threshold=float(self.threshold),
            passed=passed if isinstance(passed, bool) else None,
            signal=str(pre.get("signal", "GREEN" if passed else "RED")),
            interpretation=str(pre.get("interpretation", "")),
            details={
                "applicable": pre.get("applicable", True),
                "sector_type": sector_type,
                "structural_score": pre.get("structural_score"),
                "max_score": pre.get("max_score", MAX_STRUCTURAL_SCORE),
                "threshold_desc": str(pre.get("threshold_desc", "")),
                "precomputed": True,
            },
        )


__all__ = [
    "ASANScreenCheck",
    "classify_sector",
    "STRUCTURAL_THRESHOLD",
    "MAX_STRUCTURAL_SCORE",
]
