# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Composite multi-year Roth-conversion analysis under the bracket + IRMAA ceilings.

The headline capability: size a Roth conversion for a ~60-something retiree across
several years when the **binding constraint is IRMAA, not the tax bracket**. For
each year it computes the conversion that fits under the bracket ceiling and under
the projected IRMAA cliff, takes the smaller, gates it by outside liquidity and
the IRA balance, and reports the all-in cost — federal (incl. the Social-Security
torpedo), the LTCG-stacking and NIIT interactions, state treatment, and the
IRMAA cliff cost if crossed. It also projects the do-nothing RMD drag (the reason
the gap-year window exists) and emits a snapshot of every injected assumption.

OBBBA (2025) made the 10/12/22/24/32/35/37 brackets permanent, so the rationale is
*not* a TCJA sunset — it is the pre-RMD, pre-survivor-compression gap-year window.

All tax/IRMAA figures are **injected** (:mod:`.tables`); the engine reads no
built-in dollar amount. Pure + deterministic; no I/O. Educational scenario
analysis only — not investment, tax, or legal advice.
"""

from __future__ import annotations

from collections.abc import Callable
from math import ceil

from ...disclaimers import MC_DISCLAIMER
from .aca import aca_cliff_estimate
from .analysis import (
    AcaInteraction,
    ConversionOption,
    DoNothingProjection,
    LiquidityGate,
    LtcgStacking,
    NiitInteraction,
    ProRata,
    RothConversionAnalysis,
    SequenceSummary,
    SnapshotMetadata,
    StateTax,
    YearAnalysis,
)
from .case import PLANNING_CONTRACT_VERSION, PlanningContract
from .income_model import FederalPicture, federal_picture, marginal_ordinary_rate
from .irmaa import irmaa_headroom
from .rmd import rmd
from .tables import AcaSituation, BracketTable, IrmaaTable, StateConversionRule
from .tax import FilingStatus, rmd_start_age

_CONV_TOL = 1.0  # dollar tolerance for the conversion-ceiling solver


def _engine_version() -> str:
    from nexus_core import __version__  # lazy: avoid an import cycle at module load

    return __version__


def _largest_conversion(holds: Callable[[float], bool], hi: float) -> float:
    """Largest conversion in ``[0, hi]`` for which the monotonic ``holds`` is True."""
    if hi <= 0.0 or not holds(0.0):
        return 0.0
    if holds(hi):
        return hi
    lo, high = 0.0, hi
    while high - lo > _CONV_TOL:
        mid = (lo + high) / 2.0
        if holds(mid):
            lo = mid
        else:
            high = mid
    return lo


def _fill_ceiling_taxable(brackets: list[tuple[float, float]], rate: float) -> float | None:
    """Taxable-income ceiling for filling up to ``rate``.

    ``None`` when ``rate`` is below the lowest bracket (no room); ``inf`` when the
    top bracket already satisfies ``rate`` (bracket non-binding).
    """
    ceiling: float | None = None
    for upper, r in brackets:
        if r <= rate:
            ceiling = upper
    return ceiling


def _round(x: float) -> float:
    return round(x, 2)


def analyze_roth_conversion(
    contract: PlanningContract,
    *,
    irmaa_table: IrmaaTable,
    bracket_table: BracketTable,
    state_rule: StateConversionRule | None = None,
    aca: AcaSituation | None = None,
    irmaa_inflation: float = 0.03,
    irmaa_buffer: float = 5_000.0,
    growth_rate: float = 0.05,
    bracket_table_source: str = "caller_provided",
    irmaa_table_source: str = "caller_provided",
    state_rule_source: str = "caller_provided",
) -> RothConversionAnalysis:
    """Analyse a multi-year Roth-conversion plan under the bracket + IRMAA ceilings.

    Args:
        contract: The PII-free planning case.
        irmaa_table: Injected IRMAA tiers for the contract's filing status.
        bracket_table: Injected federal income-tax basis.
        state_rule: Injected state treatment; ``None`` ⇒ state tax left unmodeled.
        aca: Injected ACA-marketplace situation; ``None`` ⇒ the ACA premium-tax-credit
            cliff is left as a qualitative note. When given (and someone is under 65 +
            marketplace-enrolled) the year note quantifies the estimated PTC erosion.
            Not a PlanningContract field — an injected parameter, like ``state_rule``.
        irmaa_inflation: Annual assumption to project IRMAA floors to year N+2.
        irmaa_buffer: Dollars held below each projected IRMAA floor as a margin.
        growth_rate: Annual growth assumption for the inter-year IRA balance + the
            do-nothing RMD projection.
        *_source: Provenance tags recorded in the snapshot (``caller_provided`` or
            ``engine_reference``); the public demo passes ``engine_reference``.

    Returns:
        A fully-populated, serializable, identity-free :class:`RothConversionAnalysis`.
    """
    years, summary = _run_sequence(
        contract,
        irmaa_table=irmaa_table,
        bracket_table=bracket_table,
        state_rule=state_rule,
        aca=aca,
        irmaa_inflation=irmaa_inflation,
        irmaa_buffer=irmaa_buffer,
        growth_rate=growth_rate,
    )
    do_nothing = _do_nothing(contract, bracket_table, growth_rate=growth_rate)
    snapshot = SnapshotMetadata(
        engine_version=_engine_version(),
        contract_version=PLANNING_CONTRACT_VERSION,
        bracket_table_year=bracket_table.year,
        bracket_table_source=bracket_table_source,
        bracket_table_version=bracket_table.table_version,
        bracket_table_reference_source=bracket_table.source,
        bracket_table_last_verified=bracket_table.last_verified,
        irmaa_tiers_source_year=irmaa_table.source_year,
        irmaa_inflation_assumption=irmaa_inflation,
        irmaa_buffer=irmaa_buffer,
        irmaa_table_source=irmaa_table_source,
        irmaa_table_version=irmaa_table.table_version,
        irmaa_table_reference_source=irmaa_table.source,
        irmaa_table_last_verified=irmaa_table.last_verified,
        state_rule_source=("none" if state_rule is None else state_rule_source),
        state_rule_table_version=None if state_rule is None else state_rule.table_version,
        state_rule_reference_source=None if state_rule is None else state_rule.source,
        state_rule_last_verified=None if state_rule is None else state_rule.last_verified,
    )
    return RothConversionAnalysis(
        contract_version=PLANNING_CONTRACT_VERSION,
        engine_version=_engine_version(),
        case_id=contract.case_id,
        filing_status=contract.filing_status,
        years=tuple(years),
        sequence=summary,
        do_nothing=do_nothing,
        snapshot=snapshot,
        assumptions=_ASSUMPTIONS
        + (
            f"Federal tax table version: {bracket_table.table_version}.",
            f"Federal tax table source: {bracket_table.source}; last verified "
            f"{bracket_table.last_verified or 'caller-provided'}.",
            f"IRMAA table version: {irmaa_table.table_version}.",
            f"IRMAA table source: {irmaa_table.source}; last verified "
            f"{irmaa_table.last_verified or 'caller-provided'}.",
        ),
        disclaimer=MC_DISCLAIMER,
    )


def sequence_conversions(
    contract: PlanningContract,
    *,
    irmaa_table: IrmaaTable,
    bracket_table: BracketTable,
    state_rule: StateConversionRule | None = None,
    aca: AcaSituation | None = None,
    irmaa_inflation: float = 0.03,
    irmaa_buffer: float = 5_000.0,
    growth_rate: float = 0.05,
) -> SequenceSummary:
    """The multi-year roll-up only: split the conversion across the intent years.

    Each year is filled to its own binding ceiling (the smaller of the bracket and
    projected-IRMAA ceilings) against the running IRA balance — under cliff
    constraints, "fill each year to just under its ceiling" is the optimum; you
    cannot do better without crossing a cliff. Returns the per-year amounts +
    totals; :func:`analyze_roth_conversion` returns the same split with full
    per-year detail.
    """
    _years, summary = _run_sequence(
        contract,
        irmaa_table=irmaa_table,
        bracket_table=bracket_table,
        state_rule=state_rule,
        aca=aca,
        irmaa_inflation=irmaa_inflation,
        irmaa_buffer=irmaa_buffer,
        growth_rate=growth_rate,
    )
    return summary


def _run_sequence(
    contract: PlanningContract,
    *,
    irmaa_table: IrmaaTable,
    bracket_table: BracketTable,
    state_rule: StateConversionRule | None,
    aca: AcaSituation | None,
    irmaa_inflation: float,
    irmaa_buffer: float,
    growth_rate: float,
) -> tuple[list[YearAnalysis], SequenceSummary]:
    fs = contract.engine_filing_status
    remaining_trad = contract.accounts.trad_ira_aggregate
    basis = contract.accounts.nondeductible_basis
    year_results: list[YearAnalysis] = []
    total_recommended = 0.0
    total_tax = 0.0

    for year in sorted(contract.intent.years):
        ya = _analyze_year(
            contract,
            year=year,
            fs=fs,
            remaining_trad=remaining_trad,
            remaining_basis=basis,
            irmaa_table=irmaa_table,
            bracket_table=bracket_table,
            state_rule=state_rule,
            aca=aca,
            irmaa_inflation=irmaa_inflation,
            irmaa_buffer=irmaa_buffer,
        )
        year_results.append(ya)
        total_recommended += ya.recommended_amount
        total_tax += (
            ya.incremental_federal_tax
            + ya.state_tax.incremental_state_tax
            + ya.niit.incremental_niit
            + ya.ltcg.incremental_ltcg_tax
        )
        # The whole conversion (taxable + basis) leaves the Traditional IRA;
        # basis is consumed pro-rata. Remaining balance grows to the next year.
        if remaining_trad > 0.0:
            basis = max(0.0, basis - ya.recommended_amount * (basis / remaining_trad))
        remaining_trad = max(0.0, remaining_trad - ya.recommended_amount) * (1.0 + growth_rate)

    summary = SequenceSummary(
        years=tuple(sorted(contract.intent.years)),
        recommended_by_year=tuple(_round(ya.recommended_amount) for ya in year_results),
        total_recommended=_round(total_recommended),
        total_incremental_tax=_round(total_tax),
        residual_trad_balance=_round(remaining_trad),
        note=(
            "Each year is filled to its binding ceiling (min of bracket + projected "
            "IRMAA) against the running IRA balance; the balance grows at the "
            f"{growth_rate:.0%} assumption between years."
        ),
    )
    return year_results, summary


def _analyze_year(
    contract: PlanningContract,
    *,
    year: int,
    fs: FilingStatus,
    remaining_trad: float,
    remaining_basis: float,
    irmaa_table: IrmaaTable,
    bracket_table: BracketTable,
    state_rule: StateConversionRule | None,
    aca: AcaSituation | None,
    irmaa_inflation: float,
    irmaa_buffer: float,
) -> YearAnalysis:
    income = contract.income_ex_conversion
    ages = contract.ages_in(year)
    target_premium_year = year + 2
    n_seniors = sum(1 for by in contract.birth_years if year - by >= bracket_table.senior_age)
    per_person = max(
        contract.medicare_enrolled,
        sum(1 for by in contract.birth_years if target_premium_year - by >= 65),
    )
    taxable_fraction = (
        (remaining_trad - remaining_basis) / remaining_trad if remaining_trad > 0.0 else 1.0
    )
    basis_fraction = 1.0 - taxable_fraction

    def pic(conversion_gross: float) -> FederalPicture:
        return federal_picture(
            income,
            fs,
            bracket_table,
            n_seniors=n_seniors,
            conversion_taxable=conversion_gross * taxable_fraction,
        )

    base = pic(0.0)

    irmaa = irmaa_headroom(
        table=irmaa_table,
        target_premium_year=target_premium_year,
        magi_ex_conversion=base.magi_irmaa,
        per_person=per_person,
        inflation=irmaa_inflation,
        buffer=irmaa_buffer,
    )

    brackets = bracket_table.brackets_for(fs)

    def bracket_ceiling_for(rate: float | None) -> float | None:
        if rate is None:
            return None
        fc = _fill_ceiling_taxable(brackets, rate)
        if fc is None:
            return 0.0
        if fc == float("inf"):
            return None  # rate at/above the top bracket → bracket non-binding
        return _largest_conversion(lambda c: pic(c).ordinary_taxable <= fc, remaining_trad)

    def irmaa_ceiling() -> float | None:
        if per_person == 0 or irmaa.projected_next_floor is None:
            # Nobody on Medicare in the target year, or already in the top tier →
            # IRMAA does not bind this year.
            return None
        safe_magi = irmaa.projected_next_floor - irmaa_buffer
        return _largest_conversion(lambda c: pic(c).magi_irmaa <= safe_magi, remaining_trad)

    intent = contract.intent
    bracket_ceiling = bracket_ceiling_for(intent.target_rate)
    irmaa_c = irmaa_ceiling()

    # Standard option menu for the UI, regardless of the chosen rule.
    options = _build_options(
        pic, bracket_ceiling_for, irmaa_c, irmaa, remaining_trad, intent.target_rate
    )

    requested, binding_ceiling, constraint = _size_conversion(
        intent.target_rule, intent.fixed_amount, bracket_ceiling, irmaa_c, remaining_trad
    )

    # Liquidity gate: tax must be payable from OUTSIDE the IRA.
    liquidity = contract.accounts.taxable_liquidity

    def tax_due(conversion_gross: float) -> float:
        p = pic(conversion_gross)
        state = _state_tax_amount(state_rule, conversion_gross * taxable_fraction, ages[0])
        return (p.total_tax - base.total_tax) + state

    recommended = requested
    gated = False
    if requested > 0.0 and tax_due(requested) > liquidity:
        gated = True
        recommended = _largest_conversion(lambda c: tax_due(c) <= liquidity, requested)
        constraint = "liquidity"

    rec_taxable = recommended * taxable_fraction
    rec_pic = pic(recommended)

    inc_fed = _round(rec_pic.ordinary_tax - base.ordinary_tax)
    inc_ltcg = _round(rec_pic.ltcg_tax - base.ltcg_tax)
    inc_niit = _round(rec_pic.niit - base.niit)
    state_amt = _state_tax_amount(state_rule, rec_taxable, ages[0])
    # The conversion's true marginal cost includes the interactions it triggers,
    # not just the ordinary-income tax: the effective rate is all-in (federal
    # ordinary + LTCG-stacking + NIIT + state) on the taxable portion, and the
    # breakeven is the FEDERAL all-in rate (compared against a future federal
    # marginal rate). incremental_federal_tax stays the ordinary-tax line; the
    # LTCG/NIIT/state pieces are reported separately below.
    federal_all_in = inc_fed + inc_ltcg + inc_niit
    total_incremental = federal_all_in + state_amt
    eff_rate = round(total_incremental / rec_taxable, 4) if rec_taxable > 0.0 else 0.0
    breakeven = round(federal_all_in / rec_taxable, 4) if rec_taxable > 0.0 else 0.0

    aca_struct, aca_note = _aca(aca, ages, base.magi_irmaa, rec_pic.magi_irmaa)
    notes = _year_notes(
        contract, year, ages, per_person, taxable_fraction, irmaa, recommended, aca_note
    )

    return YearAnalysis(
        year=year,
        ages=ages,
        target_premium_year=target_premium_year,
        magi_ex_conversion=_round(base.magi_irmaa),
        ordinary_taxable_ex_conversion=_round(base.ordinary_taxable),
        bracket_ceiling=None if bracket_ceiling is None else _round(bracket_ceiling),
        irmaa_ceiling=None if irmaa_c is None else _round(irmaa_c),
        binding_ceiling=_round(binding_ceiling),
        binding_constraint=constraint,
        recommended_amount=_round(recommended),
        incremental_federal_tax=inc_fed,
        effective_conversion_rate=eff_rate,
        breakeven_retirement_rate=breakeven,
        options=options,
        irmaa=irmaa,
        niit=NiitInteraction(
            threshold=bracket_table.niit_threshold[fs],
            net_investment_income=_round(base.net_investment_income),
            magi_before=_round(base.magi_niit),
            magi_after=_round(rec_pic.magi_niit),
            niit_before=_round(base.niit),
            niit_after=_round(rec_pic.niit),
            incremental_niit=inc_niit,
        ),
        ltcg=LtcgStacking(
            preferential_income=_round(base.preferential_income),
            ltcg_rate_before=base.marginal_ltcg_rate,
            ltcg_rate_after=rec_pic.marginal_ltcg_rate,
            ltcg_tax_before=_round(base.ltcg_tax),
            ltcg_tax_after=_round(rec_pic.ltcg_tax),
            incremental_ltcg_tax=inc_ltcg,
        ),
        pro_rata=ProRata(
            applies=remaining_basis > 0.0,
            nondeductible_basis=_round(remaining_basis),
            trad_ira_aggregate=_round(remaining_trad),
            basis_fraction=round(basis_fraction, 4),
            taxable_fraction=round(taxable_fraction, 4),
            taxable_portion=_round(rec_taxable),
            basis_recovered=_round(recommended * basis_fraction),
        ),
        state_tax=_state_tax(state_rule, state_amt, contract.state_code),
        liquidity=LiquidityGate(
            taxable_liquidity=_round(liquidity),
            total_tax_due=_round(tax_due(recommended)),
            gated=gated,
            liquidity_limited_amount=_round(recommended),
            note=(
                "Conversion tax is paid from outside funds; paying it from the IRA "
                "is value-destructive (and, before 59½, adds a 10% penalty)."
            ),
        ),
        notes=notes,
        aca=aca_struct,
    )


def _size_conversion(
    rule: str,
    fixed_amount: float | None,
    bracket_ceiling: float | None,
    irmaa_ceiling: float | None,
    trad: float,
) -> tuple[float, float, str]:
    """Return ``(requested, binding_ceiling, constraint)`` for the chosen rule."""
    inf = float("inf")
    b = inf if bracket_ceiling is None else bracket_ceiling
    i = inf if irmaa_ceiling is None else irmaa_ceiling
    ceilings: dict[str, float] = {"bracket": b, "irmaa": i, "trad_balance": trad}
    binding_constraint = min(ceilings, key=lambda k: ceilings[k])
    binding_ceiling = ceilings[binding_constraint]

    if rule == "fixed_amount":
        requested = min(fixed_amount or 0.0, trad)
        # A fixed amount that overshoots a ceiling stays as requested, but the
        # binding constraint surfaces what it crosses.
        if requested <= binding_ceiling + _CONV_TOL:
            return requested, binding_ceiling, "fixed_amount"
        return requested, binding_ceiling, binding_constraint
    return binding_ceiling, binding_ceiling, binding_constraint


def _build_options(
    pic: Callable[[float], FederalPicture],
    bracket_ceiling_for: Callable[[float | None], float | None],
    irmaa_ceiling: float | None,
    irmaa: object,
    trad: float,
    target_rate: float | None,
) -> tuple[ConversionOption, ...]:
    safe_magi = getattr(irmaa, "projected_next_floor", None)
    buffer = getattr(irmaa, "buffer", 0.0)
    threshold = None if safe_magi is None else safe_magi - buffer

    def crosses(amount: float) -> bool:
        return threshold is not None and pic(amount).magi_irmaa > threshold + _CONV_TOL

    def opt(key: str, label: str, amount: float | None) -> ConversionOption | None:
        if amount is None:
            return None
        amt = min(amount, trad)
        return ConversionOption(
            key=key,
            label=label,
            amount=_round(amt),
            marginal_rate_after=pic(amt).marginal_ordinary_rate,
            crosses_irmaa_cliff=crosses(amt),
        )

    raw = [
        opt("fill_to_22", "Fill to 22% bracket", bracket_ceiling_for(0.22)),
        opt("fill_to_24", "Fill to 24% bracket", bracket_ceiling_for(0.24)),
        opt("just_under_irmaa", "Just under the next IRMAA tier", irmaa_ceiling),
    ]
    return tuple(o for o in raw if o is not None)


def _state_tax_amount(
    rule: StateConversionRule | None, taxable_conversion: float, owner_age: int
) -> float:
    if rule is None or taxable_conversion <= 0.0:
        return 0.0
    if rule.treatment == "none":
        return 0.0
    if rule.treatment == "exempt_retirement" and owner_age >= rule.retirement_exempt_age:
        return 0.0
    return taxable_conversion * rule.rate


def _state_tax(rule: StateConversionRule | None, amount: float, state_code: str) -> StateTax:
    if rule is None:
        return StateTax(
            state_code=state_code,
            modeled=False,
            treatment="unmodeled",
            rate=0.0,
            incremental_state_tax=0.0,
            note=(
                f"No state rule was injected for {state_code}; state tax is NOT modeled. "
                "Inject a StateConversionRule for the all-in cost."
            ),
        )
    note = {
        "none": "No state income tax on the conversion (or retirement income exempt).",
        "flat": f"Flat state rate of {rule.rate:.2%} on the taxable conversion.",
        "exempt_retirement": (
            f"{state_code} exempts IRA→Roth conversions past age {rule.retirement_exempt_age}."
        ),
    }[rule.treatment]
    return StateTax(
        state_code=state_code,
        modeled=True,
        treatment=rule.treatment,
        rate=rule.rate,
        incremental_state_tax=_round(amount),
        note=note,
    )


def _aca(
    aca: AcaSituation | None, ages: tuple[int, ...], magi_before: float, magi_after: float
) -> tuple[AcaInteraction | None, str | None]:
    """Structured ACA PTC interaction + a quantified note when a situation is
    injected (and someone is under 65 + marketplace-enrolled); else ``(None, None)``
    so the caller falls back to the generic qualitative flag."""
    if aca is None or not aca.marketplace_enrolled or not any(a < 65 for a in ages):
        return None, None
    est = aca_cliff_estimate(magi_before, magi_after, aca)
    struct = AcaInteraction(
        cliff_mode=aca.cliff_mode,
        magi_pct_fpl_before=round(est.pct_fpl_before, 4),
        magi_pct_fpl_after=round(est.pct_fpl_after, 4),
        ptc_before=_round(est.ptc_before),
        ptc_after=_round(est.ptc_after),
        incremental_ptc_loss=_round(est.incremental_ptc_loss),
        crosses_hard_cliff=est.crosses_hard_cliff,
    )
    before_pct = f"{est.pct_fpl_before * 100:.0f}%"
    after_pct = f"{est.pct_fpl_after * 100:.0f}%"
    if est.crosses_hard_cliff:
        note = (
            f"ACA cliff CROSSED: the conversion lifts MAGI from {before_pct} to {after_pct} of "
            f"FPL, past the 400% hard cliff — estimated premium-tax-credit loss "
            f"~${est.incremental_ptc_loss:,.0f}/yr (the whole benchmark credit). "
            "Flag-with-magnitude estimate, not a precise PTC determination."
        )
    elif est.incremental_ptc_loss > 0.0:
        note = (
            f"ACA: the conversion lifts MAGI from {before_pct} to {after_pct} of FPL, eroding the "
            f"premium tax credit by ~${est.incremental_ptc_loss:,.0f}/yr (estimate)."
        )
    else:
        note = (
            f"ACA: MAGI is {after_pct} of FPL after the conversion; no premium-tax-credit erosion "
            "estimated (already above the credit range, or no credit at this income)."
        )
    return struct, note


def _year_notes(
    contract: PlanningContract,
    year: int,
    ages: tuple[int, ...],
    per_person: int,
    taxable_fraction: float,
    irmaa: object,
    recommended: float,
    aca_note: str | None = None,
) -> tuple[str, ...]:
    notes: list[str] = []
    if min(ages) < 60:  # 59½ rounded; conversions are penalty-free but tax must be external
        notes.append(
            "Owner is under 59½ — the conversion itself is penalty-free, but paying "
            "the tax from IRA funds would trigger the 10% early-withdrawal penalty."
        )
    if any(a < 65 for a in ages):
        notes.append(
            aca_note
            if aca_note is not None
            else (
                "Someone is under 65 — if on an ACA marketplace plan, conversion income "
                "can vaporize premium tax credits (a separate cliff, not modeled here)."
            )
        )
    if per_person == 0:
        notes.append(
            "No one is projected to be a Medicare beneficiary in the target premium "
            f"year ({year + 2}); IRMAA does not bind for this year."
        )
    if taxable_fraction < 1.0:
        notes.append(
            "Pro-rata applies: the conversion is partly a non-taxable return of "
            "after-tax basis (IRC §72); basis cannot be cherry-picked."
        )
    if getattr(irmaa, "in_top_tier", False):
        notes.append("MAGI is already in the top IRMAA tier — the surcharge cannot rise further.")
    if recommended <= 0.0:
        notes.append("No conversion is recommended this year under the binding constraint.")
    if contract.intent.purpose == "legacy":
        notes.append(
            "Legacy framing: SECURE-Act 10-year drain means high-bracket heirs would "
            "pay more later — converting at the owner's rate can be tax arbitrage."
        )
    return tuple(notes)


def _do_nothing(
    contract: PlanningContract, bracket_table: BracketTable, *, growth_rate: float
) -> DoNothingProjection:
    self_birth = contract.birth_years[0]
    start_age = rmd_start_age(self_birth)
    first_rmd_age = ceil(start_age)
    first_rmd_year = self_birth + first_rmd_age
    years_until = max(0, first_rmd_year - contract.tax_year)
    # The RMD-drag pool is the whole pre-tax balance subject to future RMDs: the
    # Traditional IRA + employer-plan (401k/403b) money (the latter added in v1.1.0).
    employer_plan = contract.accounts.employer_plan_aggregate
    pretax_pool = contract.accounts.trad_ira_aggregate + employer_plan
    projected = pretax_pool * (1.0 + growth_rate) ** years_until
    first_rmd = rmd(age=first_rmd_age, balance=projected, birth_year=self_birth)
    fs = contract.engine_filing_status
    base = federal_picture(
        contract.income_ex_conversion,
        fs,
        bracket_table,
        n_seniors=sum(
            1 for by in contract.birth_years if first_rmd_year - by >= bracket_table.senior_age
        ),
        conversion_taxable=0.0,
    )
    rmd_amount = first_rmd["rmdAmount"]
    rate = marginal_ordinary_rate(
        base.ordinary_taxable + rmd_amount, bracket_table.brackets_for(fs)
    )
    # Survivor compression: for a married-joint plan, the surviving spouse files
    # single — the same RMD lands in the ~half-width single brackets.
    survivor_rate: float | None = None
    if fs == "married_joint":
        survivor_rate = marginal_ordinary_rate(
            base.ordinary_taxable + rmd_amount, bracket_table.brackets_for("single")
        )
    plan_clause = (
        f" (Traditional IRA + ${employer_plan:,.0f} employer-plan)" if employer_plan > 0 else ""
    )
    survivor_clause = (
        f" If the surviving spouse later files single, that RMD lands near the "
        f"{survivor_rate:.0%} bracket — the joint→single compression."
        if survivor_rate is not None and survivor_rate > rate
        else ""
    )
    return DoNothingProjection(
        rmd_start_age=float(start_age),
        first_rmd_year=first_rmd_year,
        years_until_rmd=years_until,
        growth_rate_assumption=growth_rate,
        projected_trad_balance_at_rmd=_round(projected),
        first_year_rmd=_round(rmd_amount),
        first_year_rmd_marginal_rate=rate,
        note=(
            f"If nothing is converted, the pre-tax balance{plan_clause} grows to about "
            f"${projected:,.0f} by {first_rmd_year}, forcing a first-year RMD of "
            f"~${rmd_amount:,.0f} taxed near the {rate:.0%} marginal rate — the drag "
            f"the conversion window is meant to relieve.{survivor_clause}"
        ),
        employer_plan_aggregate=_round(employer_plan),
        survivor_first_year_rmd_marginal_rate=survivor_rate,
    )


_ASSUMPTIONS: tuple[str, ...] = (
    "US federal tax only; tax/IRMAA tables are injected (snapshot them for retention).",
    "IRMAA target-year (N+2) tier floors are PROJECTED from the source-year tiers at "
    "the inflation assumption and rounded to $1,000, with a buffer held below each "
    "projected floor — the floors are an estimate until CMS publishes them.",
    "OBBBA (2025) made the 10/12/22/24/32/35/37 brackets permanent; the rationale is "
    "the pre-RMD / pre-survivor-compression gap-year window, NOT a TCJA sunset.",
    "Conversion income enters provisional income (Social-Security 'tax torpedo') and "
    "stacks under preferential income (LTCG/qualified dividends 0%→15%→20%); both are "
    "modeled. Capital losses offset AGI up to $3,000/yr with no carryover.",
    "Conversion tax is assumed paid from outside (taxable) funds; the plan is gated by "
    "taxable_liquidity. Pro-rata (IRC §72) applies across all pre-tax + after-tax IRA "
    "dollars when nondeductible basis is present.",
    "Inter-year IRA balance and the do-nothing RMD projection grow at the growth-rate "
    "assumption; later-year income is held at the tax_year level (not re-projected).",
)


__all__ = ["analyze_roth_conversion", "sequence_conversions"]
