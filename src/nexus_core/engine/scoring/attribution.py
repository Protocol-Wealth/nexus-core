# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Source attribution for scoring checks.

Attribution metadata lets scored output cite the academic or practitioner
source each check is derived from. This matters for two reasons:

    1. **Compliance** — under SEC Rule 206(4)-1 (Marketing Rule) "testimonials"
       and "third-party ratings" have specific disclosure requirements; citing
       the method's origin removes ambiguity about whether a score is a
       firm-specific opinion or a widely-used quantitative technique.

    2. **Academic integrity** — the techniques used in quantitative scoring
       (Piotroski F-Score, Hurst exponent, etc.) come from decades of
       published research. Citing the source preserves that lineage.

The metadata below covers the default 8-check framework distributed with
nexus-core. Extend or override when adding your own checks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckMetadata:
    """Academic / methodological source for a check."""

    method: str
    source: str
    explanation: str
    public_label: str | None = None
    """Optional display-friendly label for public-tier output."""


# ----------------------------------------------------------------------
# Default metadata for the 8-check framework shipped with nexus-core.
# Users can override these by merging their own dict into CHECK_METADATA
# or by passing a custom metadata dict to the formatter.
# ----------------------------------------------------------------------

CHECK_METADATA: dict[str, CheckMetadata] = {
    "CROIC": CheckMetadata(
        method="Cash Return on Invested Capital",
        source="Greenblatt / quality-investing tradition",
        explanation=(
            "How much cash the business generates relative to what has been invested in it."
        ),
        public_label="Cash Generation Quality",
    ),
    "F-Score": CheckMetadata(
        method="Piotroski F-Score",
        source="Piotroski, Journal of Accounting Research, 2000",
        explanation=(
            "Whether the company's financial position is improving or deteriorating — scored 0-9."
        ),
        public_label="Financial Health Score",
    ),
    "Hurst": CheckMetadata(
        method="Hurst Exponent",
        source="Hurst (1951) / Mandelbrot (1960s-70s)",
        explanation=(
            "Whether the asset's trend is likely to persist (H > 0.5) or mean-revert (H < 0.5)."
        ),
        public_label="Trend Persistence",
    ),
    "Lambda": CheckMetadata(
        method="Durability Decay Constant",
        source="Engineering depreciation + Buffett moats + Mauboussin CAP",
        explanation=("How quickly the asset's competitive advantage decays over time."),
        public_label="Durability Score",
    ),
    "Perez Phase": CheckMetadata(
        method="Technology Cycle Position",
        source=("Carlota Perez, Technological Revolutions and Financial Capital (2002)"),
        explanation=("Where the asset sits in the current technology adoption cycle."),
        public_label="Technology Cycle Position",
    ),
    "Regime Alignment": CheckMetadata(
        method="Regime Alignment",
        source="Hamilton (1989) + Dalio economic machine + Bridgewater All Weather",
        explanation=(
            "Whether the current economic environment favors this asset's durability layer."
        ),
        public_label="Environment Fit",
    ),
    "Sector Tailwind": CheckMetadata(
        method="Sector Momentum",
        source="Relative strength / sector rotation research",
        explanation=("Whether the asset's sector is currently outperforming the broad market."),
        public_label="Sector Momentum",
    ),
    "Structural Advantage": CheckMetadata(
        method="Structural Advantage Screen",
        source="Christensen disruption theory + sector-specific structural analysis",
        explanation=(
            "Structural advantages by sector: SaaS disruption risk, "
            "semiconductor design wins, financial ROE, healthcare pipelines, "
            "consumer brand premium, industrial efficiency, energy cost."
        ),
        public_label="Structural Advantage Screen",
    ),
}


def get_metadata(name: str) -> CheckMetadata | None:
    """Fetch metadata for a check by name. Returns None if unknown."""
    return CHECK_METADATA.get(name)


def register_metadata(name: str, meta: CheckMetadata) -> None:
    """Register or override metadata for a check.

    Intended for downstream users adding their own checks. The built-in
    metadata dict is global state, so updates are process-wide.
    """
    CHECK_METADATA[name] = meta


__all__ = ["CHECK_METADATA", "CheckMetadata", "get_metadata", "register_metadata"]
