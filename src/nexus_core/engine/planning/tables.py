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

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

FilingStatus = Literal["single", "married_joint", "married_separate", "head_of_household"]

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
    table_version: str = "caller-provided-unversioned"

    def __post_init__(self) -> None:
        for name in (
            "ordinary_brackets",
            "standard_deduction",
            "additional_std_deduction_per_senior",
            "senior_bonus_phaseout",
            "ltcg_breakpoints",
            "niit_threshold",
            "ss_provisional_thresholds",
        ):
            mapping = getattr(self, name)
            missing = set(_FILING_STATUSES) - set(mapping)
            if missing:
                raise TableError(
                    f"BracketTable.{name} missing filing status(es): {sorted(missing)}"
                )
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
            senior_bonus_deduction_per_senior=float(
                d.get("senior_bonus_deduction_per_senior", 0.0)
            ),
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
            table_version=str(
                d.get("table_version", d.get("tableVersion", "caller-provided-unversioned"))
            ),
        )

    def total_deduction(
        self, fs: FilingStatus, *, itemized: float | None, n_seniors: int, magi: float
    ) -> float:
        """Total below-the-line deduction: itemized-or-standard (+ additional 65+
        standard if not itemizing) + the phased-out OBBBA senior bonus."""
        if itemized is not None:
            base = itemized
        else:
            base = (
                self.standard_deduction[fs]
                + self.additional_std_deduction_per_senior[fs] * n_seniors
            )
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
    table_version: str = "caller-provided-unversioned"

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
            table_version=str(
                d.get("table_version", d.get("tableVersion", "caller-provided-unversioned"))
            ),
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


@dataclass(frozen=True, slots=True)
class EducationVehicleRule:
    """Reference education-savings vehicle rules for one tax year.

    These public rules are for display and assumption stamping, not for tax
    advice or state-plan selection. State-specific 529 caps, deductions, credits,
    investment menus, and recapture rules stay outside this public engine table.
    """

    tax_year: int
    vehicle: str
    label: str
    contribution_limit: float | None
    annual_gift_exclusion: float | None
    five_year_superfunding_single: float | None
    five_year_superfunding_married_joint: float | None
    magi_phaseout_single: tuple[float, float] | None
    magi_phaseout_married_joint: tuple[float, float] | None
    qualified_distribution_treatment: str
    nonqualified_distribution_penalty_rate: float | None
    notes: tuple[str, ...]
    table_version: str


# --- illustrative reference factories (NOT for production use as-is) --------

# Illustrative current-basis figures. These reference registries are explicit by
# year so missing years fail closed instead of silently reusing a stale basis.
_REFERENCE_TAX_TABLE_VERSION_BY_YEAR: dict[int, str] = {
    2026: "federal-income-tax-reference-2026-illustrative-v1",
}
_STD_DEDUCTION_BY_YEAR: dict[int, dict[FilingStatus, float]] = {
    2026: {
        "single": 15_000.0,
        "married_joint": 30_000.0,
        "married_separate": 15_000.0,
        "head_of_household": 22_500.0,
    },
}
_ORDINARY_BRACKETS_BY_YEAR: dict[int, dict[FilingStatus, list[tuple[float, float]]]] = {
    2026: {
        "single": [
            (11_925, 0.10),
            (48_475, 0.12),
            (103_350, 0.22),
            (197_300, 0.24),
            (250_525, 0.32),
            (626_350, 0.35),
            (_INF, 0.37),
        ],
        "married_joint": [
            (23_850, 0.10),
            (96_950, 0.12),
            (206_700, 0.22),
            (394_600, 0.24),
            (501_050, 0.32),
            (751_600, 0.35),
            (_INF, 0.37),
        ],
        "married_separate": [
            (11_925, 0.10),
            (48_475, 0.12),
            (103_350, 0.22),
            (197_300, 0.24),
            (250_525, 0.32),
            (375_800, 0.35),
            (_INF, 0.37),
        ],
        "head_of_household": [
            (17_000, 0.10),
            (64_850, 0.12),
            (103_350, 0.22),
            (197_300, 0.24),
            (250_500, 0.32),
            (626_350, 0.35),
            (_INF, 0.37),
        ],
    },
}
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


class TaxTableProvider(Protocol):
    """Snapshot-able tax-table source used by planning engines and tool wrappers."""

    def bracket_table(self, year: int) -> BracketTable:
        """Return the complete federal tax table for ``year`` or fail closed."""

    def irmaa_table(self, filing_status: FilingStatus, source_year: int) -> IrmaaTable:
        """Return the IRMAA table for ``source_year`` / filing status or fail closed."""


class ReferenceTaxTableProvider:
    """Built-in illustrative provider for tests, demos, and keyless public tools."""

    def bracket_table(self, year: int) -> BracketTable:
        if year not in _REFERENCE_TAX_TABLE_VERSION_BY_YEAR:
            available = ", ".join(str(y) for y in sorted(_REFERENCE_TAX_TABLE_VERSION_BY_YEAR))
            raise TableError(
                f"no reference federal tax table registered for tax year {year}; "
                f"available years: {available}"
            )
        return BracketTable(
            year=year,
            ordinary_brackets=deepcopy(_ORDINARY_BRACKETS_BY_YEAR[year]),
            standard_deduction=dict(_STD_DEDUCTION_BY_YEAR[year]),
            additional_std_deduction_per_senior=dict(_ADDITIONAL_STD_65),
            senior_bonus_deduction_per_senior=6_000.0,
            senior_bonus_phaseout=dict(_SENIOR_BONUS_PHASEOUT),
            ltcg_breakpoints=dict(_LTCG_BREAKPOINTS),
            niit_threshold=dict(_NIIT_THRESHOLD),
            ss_provisional_thresholds=dict(_SS_PROVISIONAL),
            table_version=_REFERENCE_TAX_TABLE_VERSION_BY_YEAR[year],
        )

    def irmaa_table(self, filing_status: FilingStatus, source_year: int) -> IrmaaTable:
        if source_year not in _REFERENCE_IRMAA_TIERS_BY_YEAR:
            available = ", ".join(str(y) for y in sorted(_REFERENCE_IRMAA_TIERS_BY_YEAR))
            raise TableError(
                f"no reference IRMAA table registered for source year {source_year}; "
                f"available years: {available}"
            )
        by_status = _REFERENCE_IRMAA_TIERS_BY_YEAR[source_year]
        schedule_key: FilingStatus = (
            "married_joint"
            if filing_status == "married_joint"
            else "married_separate"
            if filing_status == "married_separate"
            else "single"
        )
        return IrmaaTable(
            source_year=source_year,
            filing_status=filing_status,
            tiers=list(by_status[schedule_key]),
            table_version=(f"irmaa-reference-{source_year}-{schedule_key}-illustrative-v1"),
        )


_REFERENCE_PROVIDER = ReferenceTaxTableProvider()


_REFERENCE_EDUCATION_RULES_VERSION_BY_YEAR: dict[int, str] = {
    2026: "education-vehicle-reference-2026-irs-pub970-giftfaq-v1",
}


def reference_education_vehicle_rules(tax_year: int = 2026) -> tuple[EducationVehicleRule, ...]:
    """Reference 529 / Coverdell / UGMA-UTMA comparison rules.

    Source basis checked on 2026-07-07: IRS Topic 310 and Publication 970 for
    Coverdell ESA limits/phaseouts; IRS gift-tax FAQ for the 2026 annual
    gift-tax exclusion. The 529 five-year figure is annual exclusion × 5; review
    Form 709 handling and state-specific limits before using in advice.
    """

    if tax_year not in _REFERENCE_EDUCATION_RULES_VERSION_BY_YEAR:
        available = ", ".join(str(y) for y in sorted(_REFERENCE_EDUCATION_RULES_VERSION_BY_YEAR))
        raise TableError(
            f"no reference education vehicle rules registered for tax year {tax_year}; "
            f"available years: {available}"
        )
    version = _REFERENCE_EDUCATION_RULES_VERSION_BY_YEAR[tax_year]
    annual_exclusion = 19_000.0
    return (
        EducationVehicleRule(
            tax_year=tax_year,
            vehicle="529",
            label="529 qualified tuition program",
            contribution_limit=None,
            annual_gift_exclusion=annual_exclusion,
            five_year_superfunding_single=annual_exclusion * 5.0,
            five_year_superfunding_married_joint=annual_exclusion * 10.0,
            magi_phaseout_single=None,
            magi_phaseout_married_joint=None,
            qualified_distribution_treatment=(
                "Federal tax-free when used for qualified education expenses."
            ),
            nonqualified_distribution_penalty_rate=0.10,
            notes=(
                "No federal annual contribution cap; state aggregate account limits vary.",
                "Five-year gift-tax election figure is illustrative and requires Form 709 review.",
                "Nonqualified-distribution penalty generally applies to the earnings portion.",
                "State tax deductions/credits and recapture rules are not modeled.",
            ),
            table_version=version,
        ),
        EducationVehicleRule(
            tax_year=tax_year,
            vehicle="coverdell_esa",
            label="Coverdell education savings account",
            contribution_limit=2_000.0,
            annual_gift_exclusion=None,
            five_year_superfunding_single=None,
            five_year_superfunding_married_joint=None,
            magi_phaseout_single=(95_000.0, 110_000.0),
            magi_phaseout_married_joint=(190_000.0, 220_000.0),
            qualified_distribution_treatment=(
                "Federal tax-free to the extent distributions do not exceed qualified education expenses."
            ),
            nonqualified_distribution_penalty_rate=0.10,
            notes=(
                "Total contributions for one beneficiary cannot exceed $2,000 per year.",
                "Excess contributions can trigger a 6% excise tax while excess remains.",
                "Nonqualified-distribution penalty generally applies to the earnings portion.",
                "Beneficiary age and special-needs rules are not modeled by this table.",
            ),
            table_version=version,
        ),
        EducationVehicleRule(
            tax_year=tax_year,
            vehicle="ugma_utma",
            label="UGMA/UTMA custodial account",
            contribution_limit=None,
            annual_gift_exclusion=annual_exclusion,
            five_year_superfunding_single=None,
            five_year_superfunding_married_joint=None,
            magi_phaseout_single=None,
            magi_phaseout_married_joint=None,
            qualified_distribution_treatment=(
                "No federal qualified-education tax exclusion; assets are custodial property."
            ),
            nonqualified_distribution_penalty_rate=None,
            notes=(
                "Transfers are generally irrevocable gifts to the minor.",
                "Income taxation and financial-aid treatment depend on facts not modeled here.",
                "Use only as a planning comparison; not an account recommendation.",
            ),
            table_version=version,
        ),
    )


def reference_bracket_table(year: int = 2026) -> BracketTable:
    """An illustrative current-basis :class:`BracketTable`. Verify before real use."""
    return _REFERENCE_PROVIDER.bracket_table(year)


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
_REFERENCE_IRMAA_TIERS_BY_YEAR: dict[int, dict[FilingStatus, list[IrmaaTier]]] = {
    2025: {
        "single": _IRMAA_SINGLE,
        "head_of_household": _IRMAA_SINGLE,
        "married_joint": _IRMAA_MFJ,
        "married_separate": _IRMAA_MFS,
    },
}


def reference_irmaa_table(filing_status: FilingStatus, source_year: int = 2025) -> IrmaaTable:
    """An illustrative IRMAA table for ``filing_status``. Verify before real use.

    ``head_of_household`` shares the ``single`` IRMAA schedule (Medicare uses the
    individual return; HoH is not a distinct IRMAA basis).
    """
    return _REFERENCE_PROVIDER.irmaa_table(filing_status, source_year)


# A small, documented set of state rules. Everything else defaults to "not
# modeled" at the composite layer (state tax surfaced as unmodeled, never assumed).
_NO_INCOME_TAX_STATES = frozenset({"AK", "FL", "NV", "NH", "SD", "TN", "TX", "WA", "WY"})
_REFERENCE_STATE_RATES: dict[str, float] = {
    "AZ": 0.025,
    "CO": 0.044,
    "DE": 0.066,
    "MD": 0.0575,
    "IL": 0.0495,
    "MA": 0.05,
    "MI": 0.0425,
    "NC": 0.045,
    "NJ": 0.05525,
    "NY": 0.0685,
    "OH": 0.035,
    "VA": 0.0575,
}
_REFERENCE_RETIREMENT_EXEMPT_STATES: dict[str, tuple[float, int]] = {
    "PA": (0.0307, 59),
    "IL": (0.0495, 0),
    "MS": (0.044, 59),
    "IA": (0.038, 55),
}


def reference_state_rule(state_code: str) -> StateConversionRule | None:
    """An illustrative :class:`StateConversionRule` for a documented set of states.

    Returns ``None`` for states not in the reference set, so the composite marks
    state tax as *unmodeled* rather than silently assuming zero. ``PA`` is the
    documented exempt-past-retirement-age case.
    """
    code = state_code.upper()
    if code in _REFERENCE_RETIREMENT_EXEMPT_STATES:
        rate, age = _REFERENCE_RETIREMENT_EXEMPT_STATES[code]
        return StateConversionRule(code, "exempt_retirement", rate=rate, retirement_exempt_age=age)
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
    "EducationVehicleRule",
    "FilingStatus",
    "IrmaaTable",
    "IrmaaTier",
    "ReferenceTaxTableProvider",
    "StateConversionRule",
    "StateTreatment",
    "TableError",
    "TaxTableProvider",
    "reference_aca_situation",
    "reference_bracket_table",
    "reference_education_vehicle_rules",
    "reference_irmaa_table",
    "reference_state_rule",
]
