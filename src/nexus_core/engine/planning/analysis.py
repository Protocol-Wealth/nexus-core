# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""RothConversionAnalysis — the PII-free output shape of the composite engine.

The serializable result of :func:`nexus_core.engine.planning.analyze_roth_conversion`
and :func:`sequence_conversions`. Versioned with the input
:class:`~nexus_core.engine.planning.case.PlanningContract` (same
:data:`~nexus_core.engine.planning.case.PLANNING_CONTRACT_VERSION`).

Pure data — no logic, no I/O, no identity. Every dollar is rounded to whole
dollars and every rate to four decimals by the producer. ``None`` is used for
"unbounded / not applicable" (e.g. IRMAA headroom in the top tier) so the shape
stays JSON-serializable (no ``Infinity``). Convert to a plain dict with
:func:`dataclasses.asdict`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

#: Which ceiling (or gate) determined a year's recommended conversion amount.
BindingConstraint = Literal[
    "bracket", "irmaa", "liquidity", "trad_balance", "fixed_amount", "none"
]


@dataclass(frozen=True, slots=True)
class IrmaaHeadroom:
    """Result of :func:`irmaa_headroom` for a single conversion year.

    All floors/headroom are in the conversion year's MAGI dollars, measured
    against the **projected** target-year (year+2) tiers. A tier is a cliff: one
    dollar over a floor adds the whole tier's surcharge for the year, per person.
    """

    target_premium_year: int
    tiers_source_year: int
    inflation_assumption: float
    buffer: float
    per_person: int
    current_tier_index: int
    in_top_tier: bool
    #: Projected (inflation-adjusted, $1k-rounded) floor of the current tier.
    projected_current_floor: float
    #: Projected floor of the next tier up; ``None`` when already in the top tier.
    projected_next_floor: float | None
    #: ``projected_next_floor - buffer - magi`` (room before the next cliff, net of
    #: the safety buffer). ``None`` when in the top tier (IRMAA no longer binds);
    #: clamped at 0 when the MAGI is already within ``buffer`` of the next floor.
    irmaa_safe_headroom: float | None
    #: Annual IRMAA surcharge already being paid at the current tier (× per_person).
    current_annual_surcharge: float
    #: Incremental annual surcharge of crossing into the next tier (× per_person);
    #: ``None`` when there is no higher tier.
    cliff_cost_if_crossed: float | None


@dataclass(frozen=True, slots=True)
class NiitInteraction:
    """3.8% Net Investment Income Tax interaction with the conversion.

    A Roth conversion is **not** itself net investment income, but it raises MAGI,
    which can pull more of the existing NII over the threshold.
    """

    threshold: float
    net_investment_income: float
    magi_before: float
    magi_after: float
    niit_before: float
    niit_after: float
    incremental_niit: float


@dataclass(frozen=True, slots=True)
class LtcgStacking:
    """How the conversion pushes preferential income (LTCG + qualified dividends).

    Ordinary income from the conversion stacks **under** the preferential stack,
    so it can lift long-term gains / qualified dividends from the 0% band into 15%
    or 20%.
    """

    preferential_income: float
    ltcg_rate_before: float
    ltcg_rate_after: float
    ltcg_tax_before: float
    ltcg_tax_after: float
    incremental_ltcg_tax: float


@dataclass(frozen=True, slots=True)
class ProRata:
    """IRC §72 pro-rata (cream-in-the-coffee) treatment of after-tax basis.

    When ``nondeductible_basis > 0`` a conversion is taxed across all pre-tax and
    after-tax dollars in the aggregated Traditional IRA; basis cannot be
    cherry-picked.
    """

    applies: bool
    nondeductible_basis: float
    trad_ira_aggregate: float
    #: Fraction of any conversion that is a non-taxable return of basis.
    basis_fraction: float
    #: Fraction that is taxable (``1 - basis_fraction``).
    taxable_fraction: float
    #: Dollar amount of the recommended conversion that is taxable.
    taxable_portion: float
    #: Dollar amount that is a non-taxable return of basis.
    basis_recovered: float


@dataclass(frozen=True, slots=True)
class LiquidityGate:
    """Whether outside cash can pay the conversion tax (paying from the IRA is
    value-destructive and, under 59½, triggers a 10% penalty)."""

    taxable_liquidity: float
    total_tax_due: float
    gated: bool
    #: Conversion the liquidity supports if gated; equals the requested amount
    #: when not gated.
    liquidity_limited_amount: float
    note: str


@dataclass(frozen=True, slots=True)
class StateTax:
    """State income-tax treatment of the conversion."""

    state_code: str
    modeled: bool
    treatment: str
    rate: float
    incremental_state_tax: float
    note: str


@dataclass(frozen=True, slots=True)
class ConversionOption:
    """One named sizing of a year's conversion, for side-by-side display.

    The engine always reports the standard menu (fill-to-22%, fill-to-24%,
    just-under-the-IRMAA-tier) plus the caller's ``recommended`` option, so the
    UI can show the trade-offs regardless of the chosen ``target_rule``.
    """

    key: str
    label: str
    #: Gross conversion amount this option converts (before pro-rata split).
    amount: float
    #: Marginal ordinary rate the top of the conversion lands in.
    marginal_rate_after: float
    #: True if this option would cross the projected IRMAA cliff.
    crosses_irmaa_cliff: bool


@dataclass(frozen=True, slots=True)
class YearAnalysis:
    """Per-year conversion analysis."""

    year: int
    ages: tuple[int, ...]
    target_premium_year: int
    magi_ex_conversion: float
    ordinary_taxable_ex_conversion: float
    #: Max conversion staying within the bracket target; ``None`` = bracket not
    #: binding (no target rate, top of schedule).
    bracket_ceiling: float | None
    #: Max conversion staying under the projected IRMAA cliff (net of buffer);
    #: ``None`` = IRMAA not binding (already in the top tier).
    irmaa_ceiling: float | None
    #: ``min(bracket_ceiling, irmaa_ceiling, trad_balance)`` before the liquidity gate.
    binding_ceiling: float
    binding_constraint: str
    #: Final recommended gross conversion for the year (after the liquidity gate).
    recommended_amount: float
    #: Incremental ordinary federal income tax on the conversion (the SS torpedo is
    #: included; the LTCG-stacking and NIIT pieces are reported separately below).
    incremental_federal_tax: float
    #: All-in marginal cost of converting, on the taxable portion: ordinary federal
    #: + LTCG-stacking + NIIT + state.
    effective_conversion_rate: float
    #: FEDERAL all-in rate (ordinary + LTCG-stacking + NIIT), to compare against the
    #: retirement marginal rate the dollars would otherwise face.
    breakeven_retirement_rate: float
    options: tuple[ConversionOption, ...]
    irmaa: IrmaaHeadroom
    niit: NiitInteraction
    ltcg: LtcgStacking
    pro_rata: ProRata
    state_tax: StateTax
    liquidity: LiquidityGate
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DoNothingProjection:
    """The cost of *not* converting: the future RMD drag on the Traditional IRA.

    The conversion window matters because once RMDs begin (and once a surviving
    spouse files single) the same dollars are forced out at compressed rates.
    """

    rmd_start_age: int
    first_rmd_year: int
    years_until_rmd: int
    growth_rate_assumption: float
    projected_trad_balance_at_rmd: float
    first_year_rmd: float
    first_year_rmd_marginal_rate: float
    note: str


@dataclass(frozen=True, slots=True)
class SequenceSummary:
    """Multi-year roll-up of the recommended conversion sequence."""

    years: tuple[int, ...]
    recommended_by_year: tuple[float, ...]
    total_recommended: float
    total_incremental_tax: float
    residual_trad_balance: float
    note: str


@dataclass(frozen=True, slots=True)
class SnapshotMetadata:
    """Everything the caller must persist to reproduce + defend the analysis.

    The tax/IRMAA figures are *injected*; recording their provenance here is what
    lets a signed retention record show exactly which tables were used.
    """

    engine_version: str
    contract_version: str
    bracket_table_year: int
    bracket_table_source: str
    irmaa_tiers_source_year: int
    irmaa_inflation_assumption: float
    irmaa_buffer: float
    irmaa_table_source: str
    state_rule_source: str


@dataclass(frozen=True, slots=True)
class RothConversionAnalysis:
    """The complete, PII-free result of the composite Roth-conversion analysis."""

    contract_version: str
    engine_version: str
    case_id: str
    filing_status: str
    years: tuple[YearAnalysis, ...]
    sequence: SequenceSummary
    do_nothing: DoNothingProjection
    snapshot: SnapshotMetadata
    assumptions: tuple[str, ...]
    disclaimer: str


__all__ = [
    "BindingConstraint",
    "ConversionOption",
    "DoNothingProjection",
    "IrmaaHeadroom",
    "LiquidityGate",
    "LtcgStacking",
    "NiitInteraction",
    "ProRata",
    "RothConversionAnalysis",
    "SequenceSummary",
    "SnapshotMetadata",
    "StateTax",
    "YearAnalysis",
]
