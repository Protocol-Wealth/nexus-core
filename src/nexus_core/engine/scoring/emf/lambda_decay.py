# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF Check 4 — Lambda (λ): entropic durability / decay constant.

Estimates how quickly an asset's competitive advantage decays. A low λ means
a long useful economic life (nuclear plants, regulated utilities); a high λ
means rapid obsolescence (consumer apps, disruptive tech). The check passes
when the estimated decay constant is below a *layer-adjusted* threshold.

Methodology (porting ``estimate_decay_constant`` from the private engine):
sector base decay rate + industry/ticker overrides + structural adjustments
(physical assets, developer lock-in, mission-critical, SaaS vulnerability),
clamped to ``[0.01, 0.50]``. The pass threshold is the asset's durability
layer ceiling from ``LAYER_DECAY_THRESHOLDS`` (default ``0.20``).

Lineage: engineering depreciation + Buffett moats + Mauboussin CAP. The
canonical headline rule is "λ < 0.15", but the live threshold is the
per-layer ceiling below.
"""

from __future__ import annotations

from typing import Any

from ..checks import CheckResult, ScoringContext

# ---------------------------------------------------------------------------
# Decay constants by sector (λ) — higher = faster obsolescence.
# Ported verbatim from portfolio_engine.SECTOR_DECAY_CONSTANTS.
# ---------------------------------------------------------------------------
SECTOR_DECAY_CONSTANTS: dict[str, float] = {
    # L1 Foundation — very low decay
    "Nuclear Power": 0.02,
    "Electrical Grid": 0.03,
    "Bitcoin/Monetary": 0.01,
    "Commodities": 0.02,
    # L2 Backbone — low decay
    "Regulated Utilities": 0.04,
    "Data Centers": 0.05,
    "Water Infrastructure": 0.03,
    "Pipelines": 0.04,
    "Telecom Infrastructure": 0.06,
    # L3 Engine — medium decay
    "Semiconductors": 0.15,
    "AI/GPU": 0.12,
    "Memory": 0.18,
    "Cloud Infrastructure": 0.10,
    # L4 DataToll — medium decay
    "Cybersecurity": 0.10,
    "Defense Tech": 0.08,
    "Data Platforms": 0.12,
    "Government IT": 0.08,
    # L5 Interface — high decay
    "Enterprise SaaS": 0.22,
    "Consumer Apps": 0.28,
    "Productivity Software": 0.25,
    "E-commerce": 0.20,
    # L6 Frontier — very high decay
    "Space/Aerospace": 0.35,
    "Biotech": 0.40,
    "Disruptive Tech": 0.45,
    "Quantum Computing": 0.50,
    # Mining / Metals (L1-L2 range — physical commodity production)
    "Copper": 0.04,
    "Mining": 0.05,
    "Gold Mining": 0.04,
    "Industrial Metals & Mining": 0.05,
    "Steel": 0.06,
    # GICS sector defaults (fallback when industry doesn't match above)
    "Technology": 0.20,
    "Information Technology": 0.20,
    "Healthcare": 0.15,
    "Health Care": 0.15,
    "Financials": 0.12,
    "Financial Services": 0.12,
    "Consumer Cyclical": 0.18,
    "Consumer Defensive": 0.12,
    "Consumer Discretionary": 0.18,
    "Consumer Staples": 0.12,
    "Industrials": 0.10,
    "Energy": 0.05,
    "Utilities": 0.04,
    "Real Estate": 0.08,
    "Materials": 0.06,
    "Basic Materials": 0.06,
    "Communication Services": 0.15,
    "Unknown": 0.20,
}

# Per-layer pass ceiling for λ. Ported from LAYER_DECAY_THRESHOLDS.
LAYER_DECAY_THRESHOLDS: dict[str, float] = {
    "L1": 0.05,  # Foundation
    "L2": 0.08,  # Backbone
    "L3": 0.20,  # Engine
    "L4": 0.15,  # DataToll
    "L5": 0.30,  # Interface
    "L6": 0.50,  # Frontier (variable — no hard threshold)
    "L7": 0.50,  # Catalyst (variable)
}
DEFAULT_LAYER_THRESHOLD = 0.20

# Known-ticker base-decay overrides + SaaS vulnerability cohorts (ported verbatim).
TICKER_DECAY_OVERRIDES: dict[str, float] = {
    "CEG": 0.02, "VST": 0.03, "NRG": 0.03, "IBIT": 0.01, "GLD": 0.01,
    "NEE": 0.04, "DUK": 0.04, "EQIX": 0.05, "AWK": 0.03,
    "NVDA": 0.12, "AMD": 0.15, "TSM": 0.10, "ASML": 0.08,
    "CRWD": 0.10, "PANW": 0.10, "PLTR": 0.08,
    "CRM": 0.22, "NOW": 0.20, "ASAN": 0.30,
}
ASAN_TRINITY_TICKERS = ("ASAN", "MNDY", "SMAR", "ZM", "DOCU", "BOX", "FROG")
LOW_VULN_SAAS = ("SNOW", "MDB", "DDOG", "CRWD", "PANW", "ZS", "NET", "CFLT")


def compute_lambda(
    *,
    sector: str | None,
    industry: str | None,
    ticker: str | None = None,
) -> float:
    """Estimate the decay constant λ from sector + industry + ticker.

    Faithful port of ``PortfolioEngine.estimate_decay_constant``. Returns a
    value clamped to ``[0.01, 0.50]``.
    """
    tkr = (ticker or "").upper()
    sec = sector or "Unknown"
    ind = industry or ""

    # Sector base decay.
    base_decay = SECTOR_DECAY_CONSTANTS.get(sec, DEFAULT_LAYER_THRESHOLD)

    # More-specific industry substring match overrides the sector base.
    industry_lower = ind.lower()
    for ind_key, ind_decay in SECTOR_DECAY_CONSTANTS.items():
        if ind_key.lower() in industry_lower:
            base_decay = ind_decay
            break

    # Known-ticker override wins over both.
    if tkr in TICKER_DECAY_OVERRIDES:
        base_decay = TICKER_DECAY_OVERRIDES[tkr]

    estimated = base_decay

    # Physical infrastructure adjustment.
    if any(kw in industry_lower for kw in ("nuclear", "utility", "pipeline", "grid")):
        estimated -= 0.03
    # Developer platform adjustment.
    if any(kw in industry_lower for kw in ("developer", "api", "infrastructure", "platform")):
        estimated -= 0.03
    # Mission-critical adjustment.
    if any(kw in industry_lower for kw in ("security", "cyber", "defense")):
        estimated -= 0.02
    # SaaS vulnerability adjustment.
    if any(kw in industry_lower for kw in ("saas", "software", "application")):
        if tkr in ASAN_TRINITY_TICKERS:
            estimated += 0.08
        elif tkr not in LOW_VULN_SAAS:
            estimated += 0.03

    # Clamp to reasonable range.
    estimated = max(0.01, min(0.50, estimated))
    return round(estimated, 3)


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class LambdaCheck:
    """EMF Check 4 — Lambda (λ) entropic durability.

    Resolution order for λ:
      1. Precomputed ``ctx.fundamentals["lambda"]`` (or ``decay_constant``).
      2. Computed from ``sector`` / ``industry`` / ticker via ``compute_lambda``.

    The pass threshold is the layer ceiling: ``ctx.extra["layer"]`` (or
    ``ctx.fundamentals["layer"]``) looked up in ``LAYER_DECAY_THRESHOLDS``,
    defaulting to ``0.20`` when the layer is absent/unknown.

    Degrades to ``passed=None`` / ``signal="insufficient_data"`` when no λ can
    be resolved (no precomputed value and no sector/industry/ticker hints).
    """

    def __init__(self, default_threshold: float = DEFAULT_LAYER_THRESHOLD) -> None:
        self.default_threshold = default_threshold

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        fundamentals = ctx.fundamentals or {}

        # Resolve the durability layer (drives the threshold).
        layer = ctx.extra.get("layer") or fundamentals.get("layer")
        layer = str(layer).upper() if layer else None
        threshold = LAYER_DECAY_THRESHOLDS.get(layer or "", self.default_threshold)

        # 1. Precomputed λ.
        value = _coerce_float(
            fundamentals.get("lambda", fundamentals.get("decay_constant"))
        )

        computed = False
        if value is None:
            # 2. Compute from sector / industry / ticker.
            sector = fundamentals.get("sector")
            industry = fundamentals.get("industry")
            if sector or industry or ctx.ticker:
                value = compute_lambda(
                    sector=sector, industry=industry, ticker=ctx.ticker
                )
                computed = True

        if value is None:
            return CheckResult(
                check_number=4,
                name="Lambda (λ)",
                value=None,
                threshold=threshold,
                passed=None,
                signal="insufficient_data",
                interpretation=(
                    "No decay constant available — supply fundamentals['lambda'] "
                    "or a sector/industry to estimate λ."
                ),
                details={
                    "layer": layer,
                    "layer_thresholds": LAYER_DECAY_THRESHOLDS,
                },
            )

        passed = bool(value < threshold)
        layer_label = layer or "default"

        if passed:
            signal = "GREEN"
            interp = f"Low decay for {layer_label} (λ={value:.3f} < {threshold})"
        elif value < threshold * 1.5:
            signal = "YELLOW"
            interp = f"Moderate decay for {layer_label} (λ={value:.3f})"
        else:
            signal = "RED"
            interp = f"High decay for {layer_label} (λ={value:.3f} > {threshold})"

        return CheckResult(
            check_number=4,
            name="Lambda (λ)",
            value=value,
            threshold=threshold,
            passed=passed,
            signal=signal,
            interpretation=interp,
            details={
                "layer": layer,
                "layer_thresholds": LAYER_DECAY_THRESHOLDS,
                "computed": computed,
                "useful_life": _useful_life(value),
                "decay_category": _decay_category(value),
            },
        )


def _decay_category(value: float) -> str:
    """Bucket λ into a durability category (ported from estimate_decay_constant)."""
    if value <= 0.05:
        return "Very Low"
    if value <= 0.10:
        return "Low"
    if value <= 0.20:
        return "Medium"
    if value <= 0.35:
        return "High"
    return "Very High"


def _useful_life(value: float) -> str:
    """Map λ to an estimated useful-life band (ported from estimate_decay_constant)."""
    if value <= 0.05:
        return "30-60 years"
    if value <= 0.10:
        return "15-30 years"
    if value <= 0.20:
        return "5-15 years"
    if value <= 0.35:
        return "2-5 years"
    return "1-3 years"


__all__ = [
    "LambdaCheck",
    "compute_lambda",
    "SECTOR_DECAY_CONSTANTS",
    "LAYER_DECAY_THRESHOLDS",
    "DEFAULT_LAYER_THRESHOLD",
]
