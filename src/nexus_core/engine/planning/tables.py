# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Injected tax + IRMAA tables for the composite Roth-conversion analysis.

The engine math takes these tables **as arguments** — it never reads a built-in
dollar figure for a real analysis. That is the design that lets the caller
(pw-api) snapshot the exact bracket/tier figures used into its Rule 204-2
retention record, and lets an open-source adopter substitute their own basis.

This module also ships ``reference_*`` factories: an **illustrative current-basis**
table set for examples, tests, and the keyless public demo. They are clearly
labelled illustrative — a production caller injects an authoritative, snapshotted
table instead. Verify all figures against the current IRS / CMS publications.

Pure data — no I/O. Educational scenario analysis only, not tax advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from .tax import FilingStatus, ordinary_brackets, standard_deduction

_INF = float("inf")
_FILING_STATUSES: tuple[FilingStatus, ...] = (
    "single",
    "married_joint",
    "married_separate",
    "head_of_household",
)


class TableError(ValueError):
    """A malformed injected table."""


def _fs_float_map(raw: Any, where: str) -> dict[FilingStatus, float]:
    if not isinstance(raw, dict):
        raise TableError(f"{where} must be an object keyed by filing status")
    out: dict[FilingStatus, float] = {}
    for fs in _FILING_STATUSES:
        if fs not in raw:
            raise TableError(f"{where} missing filing status '{fs}'")
        out[fs] = float(raw[fs])
    return out


def _fs_pair_map(raw: Any, where: str) -> dict[FilingStatus, tuple[float, float]]:
    if not isinstance(raw, dict):
        raise TableError(f"{where} must be an object keyed by filing status")
    out: dict[FilingStatus, tuple[float, float]] = {}
    for fs in _FILING_STATUSES:
        pair = raw.get(fs)
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise TableError(f"{where}[{fs}] must be a [a, b] pair")
        out[fs] = (float(pair[0]), float(pair[1]))
    return out


# --- federal income-tax basis ---------------------------------------------


@dataclass(frozen=True, slots=True)
class BracketTable:
    """A complete federal income-tax basis for one tax year.

    Every dollar figure the ordinary/preferential/NIIT/Social-Security math needs,
    keyed by filing status. Inject a snapshotted instance; the engine reads
    nothing else.
    """

    year: int
    #: filing status → ascending ``(upper_bound, marginal_rate)``; last is open-ended (inf).
    ordinary_brackets: dict[FilingStatus, list[tuple[float, float]]]
    #: filing status → standard deduction.
    standard_deduction: dict[FilingStatus, float]
    #: filing status → the *additional* standard deduction per person age 65+.
    additional_std_deduction_per_senior: dict[FilingStatus, float]
    #: OBBBA bonus deduction per person age 65+ (2025–2028); available whether or
    #: not the filer itemizes. Phases out above the MAGI thresholds below.
    senior_bonus_deduction_per_senior: float
    #: filing status → (MAGI phaseout threshold, phaseout rate) for the bonus.
    senior_bonus_phaseout: dict[FilingStatus, tuple[float, float]]
    #: filing status → (0%-rate upper bound, 15%-rate upper bound); above ⇒ 20%.
    ltcg_breakpoints: dict[FilingStatus, tuple[float, float]]
    #: filing status → Net Investment Income Tax MAGI threshold (3.8% above it).
    niit_threshold: dict[FilingStatus, float]
    #: filing status → Social-Security taxability (base, additional) provisional-income
    #: thresholds (statutory, not inflation-indexed).
    ss_provisional_thresholds: dict[FilingStatus, tuple[float, float]]
    niit_rate: float = 0.038
    senior_age: int = 65

    def __post_init__(self) -> None:
        for name in (
            "ordinary_brackets", "standard_deduction", "additional_std_deduction_per_senior",
            "senior_bonus_phaseout", "ltcg_breakpoints", "niit_threshold",
            "ss_provisional_thresholds",
        ):
            mapping = getattr(self, name)
            missing = set(_FILING_STATUSES) - set(mapping)
            if missing:
                raise TableError(f"BracketTable.{name} missing filing status(es): {sorted(missing)}")
        for fs, brk in self.ordinary_brackets.items():
            if not brk or brk[-1][0] != _INF:
                raise TableError(f"ordinary_brackets[{fs}] must be non-empty and end at infinity")
            uppers = [u for u, _ in brk]
            if uppers != sorted(uppers):
                raise TableError(f"ordinary_brackets[{fs}] must be ascending by upper bound")

    def brackets_for(self, fs: FilingStatus) -> list[tuple[float, float]]:
        return self.ordinary_brackets[fs]

    @classmethod
    def from_dict(cls, d: Any) -> BracketTable:
        """Parse a wire-form BracketTable (a ``null`` bracket upper bound = ∞)."""
        if not isinstance(d, dict):
            raise TableError("bracket_table must be an object")
        raw_brackets = d.get("ordinary_brackets")
        if not isinstance(raw_brackets, dict):
            raise TableError("bracket_table.ordinary_brackets must be an object")
        brackets: dict[FilingStatus, list[tuple[float, float]]] = {}
        for fs in _FILING_STATUSES:
            rows = raw_brackets.get(fs)
            if not isinstance(rows, list) or not rows:
                raise TableError(f"ordinary_brackets[{fs}] must be a non-empty list")
            brackets[fs] = [
                (_INF if row[0] is None else float(row[0]), float(row[1])) for row in rows
            ]
        return cls(
            year=int(d["year"]),
            ordinary_brackets=brackets,
            standard_deduction=_fs_float_map(d.get("standard_deduction"), "standard_deduction"),
            additional_std_deduction_per_senior=_fs_float_map(
                d.get("additional_std_deduction_per_senior"), "additional_std_deduction_per_senior"
            ),
            senior_bonus_deduction_per_senior=float(d.get("senior_bonus_deduction_per_senior", 0.0)),
            senior_bonus_phaseout=_fs_pair_map(
                d.get("senior_bonus_phaseout"), "senior_bonus_phaseout"
            ),
            ltcg_breakpoints=_fs_pair_map(d.get("ltcg_breakpoints"), "ltcg_breakpoints"),
            niit_threshold=_fs_float_map(d.get("niit_threshold"), "niit_threshold"),
            ss_provisional_thresholds=_fs_pair_map(
                d.get("ss_provisional_thresholds"), "ss_provisional_thresholds"
            ),
            niit_rate=float(d.get("niit_rate", 0.038)),
            senior_age=int(d.get("senior_age", 65)),
        )

    def total_deduction(self, fs: FilingStatus, *, itemized: float | None, n_seniors: int, magi: float) -> float:
        """Total below-the-line deduction: itemized-or-standard (+ additional 65+
        standard if not itemizing) + the phased-out OBBBA senior bonus."""
        if itemized is not None:
            base = itemized
        else:
            base = self.standard_deduction[fs] + self.additional_std_deduction_per_senior[fs] * n_seniors
        bonus = self.senior_bonus_deduction_per_senior * n_seniors
        threshold, rate = self.senior_bonus_phaseout[fs]
        if bonus > 0.0 and magi > threshold:
            bonus = max(0.0, bonus - (magi - threshold) * rate)
        return base + bonus


# --- IRMAA (Medicare Part B + Part D income-related surcharge) -------------


@dataclass(frozen=True, slots=True)
class IrmaaTier:
    """One IRMAA tier: a MAGI floor + the per-beneficiary monthly surcharge.

    The surcharges are the IRMAA *adjustment* (the amount above the base premium),
    so the lowest tier is zero. A tier is a cliff: one dollar over ``magi_floor``
    applies the whole tier's surcharge for the year, per beneficiary.
    """

    magi_floor: float
    part_b_monthly: float
    part_d_monthly: float

    @property
    def annual_surcharge_per_person(self) -> float:
        return (self.part_b_monthly + self.part_d_monthly) * 12.0


@dataclass(frozen=True, slots=True)
class IrmaaTable:
    """Ascending IRMAA tiers for one filing status + their publication year."""

    source_year: int
    filing_status: FilingStatus
    tiers: list[IrmaaTier]

    def __post_init__(self) -> None:
        if not self.tiers:
            raise TableError("IrmaaTable.tiers must be non-empty")
        if self.tiers[0].magi_floor != 0.0:
            raise TableError("IrmaaTable.tiers[0].magi_floor must be 0 (the base tier)")
        floors = [t.magi_floor for t in self.tiers]
        if floors != sorted(floors) or len(set(floors)) != len(floors):
            raise TableError("IrmaaTable.tiers must be strictly ascending by magi_floor")

    @classmethod
    def from_dict(cls, d: Any) -> IrmaaTable:
        if not isinstance(d, dict):
            raise TableError("irmaa_table must be an object")
        raw_tiers = d.get("tiers")
        if not isinstance(raw_tiers, list) or not raw_tiers:
            raise TableError("irmaa_table.tiers must be a non-empty list")
        tiers = [
            IrmaaTier(
                magi_floor=float(t["magi_floor"]),
                part_b_monthly=float(t.get("part_b_monthly", 0.0)),
                part_d_monthly=float(t.get("part_d_monthly", 0.0)),
            )
            for t in raw_tiers
        ]
        return cls(
            source_year=int(d["source_year"]),
            filing_status=cast(FilingStatus, str(d["filing_status"])),
            tiers=tiers,
        )


# --- state treatment of a conversion --------------------------------------

StateTreatment = str  # "flat" | "exempt_retirement" | "none"


@dataclass(frozen=True, slots=True)
class StateConversionRule:
    """How a state taxes an IRA→Roth conversion.

    ``none`` — no state income tax (or retirement income exempt). ``flat`` — a
    flat marginal ``rate`` on the taxable conversion. ``exempt_retirement`` — the
    conversion is exempt once the owner is past ``retirement_exempt_age`` (e.g.
    Pennsylvania), otherwise taxed at ``rate``.
    """

    state_code: str
    treatment: StateTreatment
    rate: float = 0.0
    retirement_exempt_age: int = 59

    def __post_init__(self) -> None:
        if self.treatment not in ("flat", "exempt_retirement", "none"):
            raise TableError("treatment must be 'flat', 'exempt_retirement', or 'none'")
        if not 0.0 <= self.rate < 1.0:
            raise TableError("state rate must be in [0, 1)")

    @classmethod
    def from_dict(cls, d: Any) -> StateConversionRule:
        if not isinstance(d, dict):
            raise TableError("state_rule must be an object")
        return cls(
            state_code=str(d["state_code"]).upper(),
            treatment=str(d["treatment"]),
            rate=float(d.get("rate", 0.0)),
            retirement_exempt_age=int(d.get("retirement_exempt_age", 59)),
        )


AcaCliffMode = str  # "hard_400fpl" | "capped_8_5"


@dataclass(frozen=True, slots=True)
class AcaSituation:
    """Injected ACA-marketplace situation for the premium-tax-credit (PTC) cliff.

    Like :class:`StateConversionRule`, this is an injected *parameter*, not a
    PlanningContract field — so quantifying the ACA cliff needs no contract
    change. It bundles the case data (household size, benchmark premium,
    marketplace enrollment) with the credit-formula reference figures (FPL,
    applicable-percentage ramp). When absent, the composite leaves the ACA cliff
    as a qualitative note.

    The PTC is ``max(0, benchmark_premium_annual - applicable_pct(MAGI%FPL) *
    MAGI)``. ``cliff_mode`` selects the policy regime: ``hard_400fpl`` — the
    pre-2021 / post-2025 hard cliff (one dollar over 400% FPL → $0 PTC);
    ``capped_8_5`` — the 2021–2025 ARPA/IRA cap (contribution capped at
    ``cap_contribution_pct`` of MAGI with no hard cliff).

    Documented simplification (a flag-with-magnitude estimate, NOT a precise PTC
    determination): the applicable percentage ramps linearly from 0% at/below
    ``lower_fpl_pct`` to ``cap_contribution_pct`` at ``cap_fpl_pct``; uses the
    conversion-year IRMAA MAGI as the ACA MAGI proxy; ignores age-rating of the
    benchmark premium and the household's coverage months.
    """

    marketplace_enrolled: bool
    household_size: int
    benchmark_premium_annual: float
    fpl_base: float
    fpl_per_person: float
    lower_fpl_pct: float = 1.5
    cap_fpl_pct: float = 4.0
    cap_contribution_pct: float = 0.085
    cliff_mode: AcaCliffMode = "hard_400fpl"

    def __post_init__(self) -> None:
        if self.household_size < 1:
            raise TableError("household_size must be >= 1")
        if self.benchmark_premium_annual < 0.0:
            raise TableError("benchmark_premium_annual must be non-negative")
        if self.fpl_base <= 0.0 or self.fpl_per_person < 0.0:
            raise TableError("fpl_base must be > 0 and fpl_per_person >= 0")
        if not 0.0 < self.lower_fpl_pct < self.cap_fpl_pct:
            raise TableError("require 0 < lower_fpl_pct < cap_fpl_pct")
        if not 0.0 <= self.cap_contribution_pct < 1.0:
            raise TableError("cap_contribution_pct must be in [0, 1)")
        if self.cliff_mode not in ("hard_400fpl", "capped_8_5"):
            raise TableError("cliff_mode must be 'hard_400fpl' or 'capped_8_5'")

    def fpl(self) -> float:
        """Federal Poverty Level for this household size."""
        return self.fpl_base + self.fpl_per_person * (self.household_size - 1)

    @classmethod
    def from_dict(cls, d: Any) -> AcaSituation:
        if not isinstance(d, dict):
            raise TableError("aca must be an object")
        return cls(
            marketplace_enrolled=bool(d["marketplace_enrolled"]),
            household_size=int(d["household_size"]),
            benchmark_premium_annual=float(d["benchmark_premium_annual"]),
            fpl_base=float(d.get("fpl_base", 15_060.0)),
            fpl_per_person=float(d.get("fpl_per_person", 5_380.0)),
            lower_fpl_pct=float(d.get("lower_fpl_pct", 1.5)),
            cap_fpl_pct=float(d.get("cap_fpl_pct", 4.0)),
            cap_contribution_pct=float(d.get("cap_contribution_pct", 0.085)),
            cliff_mode=str(d.get("cliff_mode", "hard_400fpl")),
        )


# --- illustrative reference factories (NOT for production use as-is) --------

# Illustrative current-basis figures. Bracket schedules + standard deductions are
# pulled from the engine's published table (engine/planning/tax.py); the
# preferential/NIIT/SS/senior figures below are an illustrative 2025/2026 basis.
_ADDITIONAL_STD_65: dict[FilingStatus, float] = {
    "single": 2_000.0,
    "married_joint": 1_600.0,
    "married_separate": 1_600.0,
    "head_of_household": 2_000.0,
}
_SENIOR_BONUS_PHASEOUT: dict[FilingStatus, tuple[float, float]] = {
    "single": (75_000.0, 0.06),
    "married_joint": (150_000.0, 0.06),
    "married_separate": (75_000.0, 0.06),
    "head_of_household": (75_000.0, 0.06),
}
_LTCG_BREAKPOINTS: dict[FilingStatus, tuple[float, float]] = {
    "single": (48_350.0, 533_400.0),
    "married_joint": (96_700.0, 600_050.0),
    "married_separate": (48_350.0, 300_000.0),
    "head_of_household": (64_750.0, 566_700.0),
}
_NIIT_THRESHOLD: dict[FilingStatus, float] = {
    "single": 200_000.0,
    "married_joint": 250_000.0,
    "married_separate": 125_000.0,
    "head_of_household": 200_000.0,
}
_SS_PROVISIONAL: dict[FilingStatus, tuple[float, float]] = {
    "single": (25_000.0, 34_000.0),
    "married_joint": (32_000.0, 44_000.0),
    "married_separate": (0.0, 0.0),  # lived-with-spouse: up to 85% taxable
    "head_of_household": (25_000.0, 34_000.0),
}


def reference_bracket_table(year: int = 2026) -> BracketTable:
    """An illustrative current-basis :class:`BracketTable`. Verify before real use."""
    return BracketTable(
        year=year,
        ordinary_brackets={fs: ordinary_brackets(fs) for fs in _FILING_STATUSES},
        standard_deduction={fs: standard_deduction(fs) for fs in _FILING_STATUSES},
        additional_std_deduction_per_senior=dict(_ADDITIONAL_STD_65),
        senior_bonus_deduction_per_senior=6_000.0,
        senior_bonus_phaseout=dict(_SENIOR_BONUS_PHASEOUT),
        ltcg_breakpoints=dict(_LTCG_BREAKPOINTS),
        niit_threshold=dict(_NIIT_THRESHOLD),
        ss_provisional_thresholds=dict(_SS_PROVISIONAL),
    )


# Illustrative IRMAA tiers. Single/MFJ Part B + Part D monthly surcharges on a
# ~2025 basis (floors are the MAGI thresholds; verify against CMS). MFS uses the
# special two-step married-separate schedule.
_IRMAA_SINGLE = [
    IrmaaTier(0.0, 0.0, 0.0),
    IrmaaTier(106_000.0, 74.00, 13.70),
    IrmaaTier(133_000.0, 185.00, 35.30),
    IrmaaTier(167_000.0, 295.90, 57.00),
    IrmaaTier(200_000.0, 406.90, 78.60),
    IrmaaTier(500_000.0, 443.90, 85.80),
]
_IRMAA_MFJ = [
    IrmaaTier(0.0, 0.0, 0.0),
    IrmaaTier(212_000.0, 74.00, 13.70),
    IrmaaTier(266_000.0, 185.00, 35.30),
    IrmaaTier(334_000.0, 295.90, 57.00),
    IrmaaTier(400_000.0, 406.90, 78.60),
    IrmaaTier(750_000.0, 443.90, 85.80),
]
_IRMAA_MFS = [
    IrmaaTier(0.0, 0.0, 0.0),
    IrmaaTier(106_000.0, 406.90, 78.60),
    IrmaaTier(394_000.0, 443.90, 85.80),
]


def reference_irmaa_table(filing_status: FilingStatus, source_year: int = 2025) -> IrmaaTable:
    """An illustrative IRMAA table for ``filing_status``. Verify before real use.

    ``head_of_household`` shares the ``single`` IRMAA schedule (Medicare uses the
    individual return; HoH is not a distinct IRMAA basis).
    """
    if filing_status == "married_joint":
        tiers = list(_IRMAA_MFJ)
    elif filing_status == "married_separate":
        tiers = list(_IRMAA_MFS)
    else:
        tiers = list(_IRMAA_SINGLE)
    return IrmaaTable(source_year=source_year, filing_status=filing_status, tiers=tiers)


# A small, documented set of state rules. Everything else defaults to "not
# modeled" at the composite layer (state tax surfaced as unmodeled, never assumed).
_NO_INCOME_TAX_STATES = frozenset(
    {"AK", "FL", "NV", "NH", "SD", "TN", "TX", "WA", "WY"}
)
_REFERENCE_STATE_RATES: dict[str, float] = {
    "AZ": 0.025, "CO": 0.044, "IL": 0.0495, "MA": 0.05, "MI": 0.0425,
    "NC": 0.045, "NY": 0.0685, "OH": 0.035, "VA": 0.0575,
}


def reference_state_rule(state_code: str) -> StateConversionRule | None:
    """An illustrative :class:`StateConversionRule` for a documented set of states.

    Returns ``None`` for states not in the reference set, so the composite marks
    state tax as *unmodeled* rather than silently assuming zero. ``PA`` is the
    documented exempt-past-retirement-age case.
    """
    code = state_code.upper()
    if code == "PA":
        return StateConversionRule("PA", "exempt_retirement", rate=0.0307, retirement_exempt_age=59)
    if code in _NO_INCOME_TAX_STATES:
        return StateConversionRule(code, "none")
    if code in _REFERENCE_STATE_RATES:
        return StateConversionRule(code, "flat", rate=_REFERENCE_STATE_RATES[code])
    return None


def reference_aca_situation(
    *,
    household_size: int,
    benchmark_premium_annual: float,
    state_code: str = "US",
    cliff_mode: AcaCliffMode = "hard_400fpl",
) -> AcaSituation:
    """An illustrative :class:`AcaSituation` (2024-basis FPL). Verify before real use.

    FPL uses the 48-contiguous-state figure ($15,060 + $5,380/person) by default;
    ``AK`` and ``HI`` use their higher schedules. The applicable-percentage ramp
    (0% below 150% FPL → 8.5% at 400% FPL) is the ARPA/IRA basis; pair it with
    ``cliff_mode="hard_400fpl"`` to model the pre-2021 / post-2025 hard cliff.
    """
    fpl_base, fpl_per = 15_060.0, 5_380.0
    code = state_code.upper()
    if code == "AK":
        fpl_base, fpl_per = 18_810.0, 6_730.0
    elif code == "HI":
        fpl_base, fpl_per = 17_310.0, 6_190.0
    return AcaSituation(
        marketplace_enrolled=True,
        household_size=household_size,
        benchmark_premium_annual=benchmark_premium_annual,
        fpl_base=fpl_base,
        fpl_per_person=fpl_per,
        cliff_mode=cliff_mode,
    )


__all__ = [
    "AcaCliffMode",
    "AcaSituation",
    "BracketTable",
    "IrmaaTable",
    "IrmaaTier",
    "StateConversionRule",
    "StateTreatment",
    "TableError",
    "reference_aca_situation",
    "reference_bracket_table",
    "reference_irmaa_table",
    "reference_state_rule",
]
