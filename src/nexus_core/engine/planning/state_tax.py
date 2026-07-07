# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Illustrative state-tax rules for planning.

Data-driven state rules over de-identified inputs only. This module does not
ingest addresses, account records, raw transactions, notes, approvals, or audit
state. It is a planning illustration, not tax advice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .tables import FilingStatus, TableError

RateStructure = Literal["none", "flat", "brackets"]
RetirementExclusionKind = Literal["none", "full", "capped", "tiered_percentage"]
IncomeSource = Literal[
    "earned_income",
    "social_security",
    "pension",
    "annuity",
    "traditional_distribution",
    "government_pension",
    "roth_distribution",
    "taxable_gain",
    "conversion",
]

_INF = float("inf")
_FILING_STATUSES: tuple[FilingStatus, ...] = (
    "single",
    "married_joint",
    "married_separate",
    "head_of_household",
)
_RETIREMENT_SOURCES = frozenset(
    {"pension", "annuity", "traditional_distribution", "government_pension", "conversion"}
)


def _normalize_state_code(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 2 or not value.isalpha():
        raise TableError(f"{field} must be a two-letter postal abbreviation")
    return value.upper()


@dataclass(frozen=True, slots=True)
class StateRetirementExclusionBand:
    """Income band for a percentage-based retirement exclusion."""

    income_upper: float
    pct_single: float
    pct_married_joint: float
    pct_married_separate: float
    pct_head_of_household: float

    def percentage_for(self, filing_status: FilingStatus) -> float:
        return {
            "single": self.pct_single,
            "married_joint": self.pct_married_joint,
            "married_separate": self.pct_married_separate,
            "head_of_household": self.pct_head_of_household,
        }[filing_status]


@dataclass(frozen=True, slots=True)
class StateRetirementExclusion:
    """How a state excludes retirement income from taxable income."""

    kind: RetirementExclusionKind = "none"
    age_min: float | None = None
    amount: float = 0.0
    under_age_amount: float = 0.0
    phaseout_threshold_single: float | None = None
    phaseout_threshold_married_joint: float | None = None
    phaseout_threshold_married_separate: float | None = None
    phaseout_threshold_head_of_household: float | None = None
    phaseout_rate: float = 0.0
    government_pension_full_exempt: bool = False
    bands: tuple[StateRetirementExclusionBand, ...] = ()

    def phaseout_threshold_for(self, filing_status: FilingStatus) -> float | None:
        return {
            "single": self.phaseout_threshold_single,
            "married_joint": self.phaseout_threshold_married_joint,
            "married_separate": self.phaseout_threshold_married_separate,
            "head_of_household": self.phaseout_threshold_head_of_household,
        }[filing_status]


@dataclass(frozen=True, slots=True)
class StateTaxRule:
    """One state's illustrative income-tax rule for a tax year."""

    tax_year: int
    state_code: str
    rate_structure: RateStructure
    flat_rate: float | None = None
    brackets: tuple[tuple[float, float], ...] = ()
    ss_taxed: bool = False
    retirement_exclusion: StateRetirementExclusion = StateRetirementExclusion()
    local_income_tax_hook: bool = False
    flags: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    table_version: str = "state-tax-reference-illustrative-unversioned"

    def __post_init__(self) -> None:
        if len(self.state_code) != 2 or not self.state_code.isalpha():
            raise TableError("state_code must be a two-letter postal abbreviation")
        if self.rate_structure == "flat" and self.flat_rate is None:
            raise TableError("flat state tax rules require flat_rate")
        if self.flat_rate is not None and not 0.0 <= self.flat_rate < 1.0:
            raise TableError("flat_rate must be in [0, 1)")
        if self.rate_structure == "brackets":
            if not self.brackets or self.brackets[-1][0] != _INF:
                raise TableError("bracket state tax rules must end with infinity")
            uppers = [upper for upper, _rate in self.brackets]
            if uppers != sorted(uppers):
                raise TableError("state brackets must be ascending")


@dataclass(frozen=True, slots=True)
class StateTaxEstimate:
    """State-tax estimate for one income component."""

    state_code: str
    modeled: bool
    source: IncomeSource
    gross_income: float
    taxable_income: float
    tax: float
    exclusion: float
    note: str
    table_version: str


@dataclass(frozen=True, slots=True)
class StateResidencyChange:
    """A deterministic one-time residency change by projection year."""

    year: int
    from_state: str
    to_state: str

    def __post_init__(self) -> None:
        if isinstance(self.year, bool) or not isinstance(self.year, int):
            raise TableError("residencyChange.year must be a whole number")
        _normalize_state_code(self.from_state, "residencyChange.from")
        _normalize_state_code(self.to_state, "residencyChange.to")

    @classmethod
    def from_dict(cls, raw: object) -> StateResidencyChange:
        if not isinstance(raw, dict):
            raise TableError("residencyChange must be an object")
        allowed = {"year", "from", "to"}
        extra = set(raw) - allowed
        if extra:
            raise TableError(f"residencyChange only accepts {', '.join(sorted(allowed))}")
        return cls(
            year=int(raw["year"]),
            from_state=str(raw["from"]),
            to_state=str(raw["to"]),
        )


def _round_money(value: float) -> float:
    return round(value + 0.0, 2)


def _tax_from_rule(rule: StateTaxRule, taxable_income: float) -> float:
    if taxable_income <= 0.0 or rule.rate_structure == "none":
        return 0.0
    if rule.rate_structure == "flat":
        assert rule.flat_rate is not None
        return taxable_income * rule.flat_rate
    tax = 0.0
    lower = 0.0
    for upper, rate in rule.brackets:
        if taxable_income <= lower:
            break
        top = min(taxable_income, upper)
        tax += (top - lower) * rate
        lower = upper
    return tax


def _is_age_eligible(exclusion: StateRetirementExclusion, age: float) -> bool:
    return exclusion.age_min is None or age >= exclusion.age_min


def _capped_exclusion_amount(
    exclusion: StateRetirementExclusion,
    *,
    age: float,
    filing_status: FilingStatus,
    total_income: float,
) -> float:
    amount = exclusion.amount if _is_age_eligible(exclusion, age) else exclusion.under_age_amount
    threshold = exclusion.phaseout_threshold_for(filing_status)
    if threshold is not None and exclusion.phaseout_rate > 0.0 and total_income > threshold:
        amount = max(0.0, amount - (total_income - threshold) * exclusion.phaseout_rate)
    return amount


def retirement_exclusion_amount(
    rule: StateTaxRule,
    *,
    gross_income: float,
    age: float,
    source: IncomeSource,
    filing_status: FilingStatus,
    total_income: float,
) -> float:
    """Return the excluded amount for one state-income component."""

    if gross_income <= 0.0:
        return 0.0
    if source == "roth_distribution":
        return gross_income
    if source == "social_security" and not rule.ss_taxed:
        return gross_income
    if source == "government_pension" and rule.retirement_exclusion.government_pension_full_exempt:
        return gross_income
    if source not in _RETIREMENT_SOURCES:
        return 0.0

    exclusion = rule.retirement_exclusion
    if exclusion.kind == "none":
        return 0.0
    if exclusion.kind == "full":
        return gross_income if _is_age_eligible(exclusion, age) else 0.0
    if exclusion.kind == "capped":
        return min(
            gross_income,
            _capped_exclusion_amount(
                exclusion, age=age, filing_status=filing_status, total_income=total_income
            ),
        )
    if exclusion.kind == "tiered_percentage":
        if not _is_age_eligible(exclusion, age):
            return 0.0
        for band in exclusion.bands:
            if total_income <= band.income_upper:
                return gross_income * band.percentage_for(filing_status)
        return 0.0
    raise TableError(f"unknown retirement exclusion kind: {exclusion.kind}")


def estimate_state_income_tax(
    rule: StateTaxRule,
    *,
    gross_income: float,
    age: float,
    source: IncomeSource,
    filing_status: FilingStatus = "single",
    total_income: float | None = None,
) -> StateTaxEstimate:
    """Estimate state tax on one income component."""

    if filing_status not in _FILING_STATUSES:
        raise TableError(f"filing_status must be one of {', '.join(_FILING_STATUSES)}")
    total = gross_income if total_income is None else total_income
    exclusion = retirement_exclusion_amount(
        rule,
        gross_income=gross_income,
        age=age,
        source=source,
        filing_status=filing_status,
        total_income=total,
    )
    taxable = max(0.0, gross_income - exclusion)
    tax = _tax_from_rule(rule, taxable)
    return StateTaxEstimate(
        state_code=rule.state_code,
        modeled=True,
        source=source,
        gross_income=_round_money(gross_income),
        taxable_income=_round_money(taxable),
        tax=_round_money(tax),
        exclusion=_round_money(exclusion),
        note=_state_note(rule, source),
        table_version=rule.table_version,
    )


def estimate_state_income_tax_components(
    rule: StateTaxRule,
    components: list[tuple[str, IncomeSource, float]],
    *,
    age: float,
    filing_status: FilingStatus = "single",
    total_income: float | None = None,
    baseline_taxable_income: float = 0.0,
) -> dict[str, StateTaxEstimate]:
    """Estimate state tax for named income components.

    Capped/tiered retirement exclusions are shared across retirement-income
    components. This avoids applying a state's cap independently to pension,
    annuity, RMD, and discretionary IRA withdrawals in the same projection year.
    """

    if filing_status not in _FILING_STATUSES:
        raise TableError(f"filing_status must be one of {', '.join(_FILING_STATUSES)}")
    positive = [
        (label, source, float(gross_income))
        for label, source, gross_income in components
        if gross_income > 0.0
    ]
    total = sum(gross for _, _, gross in positive) if total_income is None else total_income
    exclusions: dict[str, float] = {}
    retirement_labels: list[tuple[str, float]] = []
    for label, source, gross in positive:
        if (
            source == "roth_distribution"
            or (source == "social_security" and not rule.ss_taxed)
            or (
                source == "government_pension"
                and rule.retirement_exclusion.government_pension_full_exempt
            )
        ):
            exclusions[label] = gross
        elif source in _RETIREMENT_SOURCES:
            retirement_labels.append((label, gross))
        else:
            exclusions[label] = 0.0

    exclusion = rule.retirement_exclusion
    retirement_gross = sum(gross for _, gross in retirement_labels)
    retirement_exclusion_total = 0.0
    if retirement_gross > 0.0:
        if exclusion.kind == "full":
            retirement_exclusion_total = (
                retirement_gross if _is_age_eligible(exclusion, age) else 0.0
            )
        elif exclusion.kind == "capped":
            retirement_exclusion_total = min(
                retirement_gross,
                _capped_exclusion_amount(
                    exclusion,
                    age=age,
                    filing_status=filing_status,
                    total_income=total,
                ),
            )
        elif exclusion.kind == "tiered_percentage":
            if _is_age_eligible(exclusion, age):
                pct = 0.0
                for band in exclusion.bands:
                    if total <= band.income_upper:
                        pct = band.percentage_for(filing_status)
                        break
                retirement_exclusion_total = retirement_gross * pct
        elif exclusion.kind != "none":
            raise TableError(f"unknown retirement exclusion kind: {exclusion.kind}")

    for label, gross in retirement_labels:
        exclusions[label] = (
            retirement_exclusion_total * gross / retirement_gross if retirement_gross > 0.0 else 0.0
        )

    taxable_by_label: dict[str, float] = {}
    for label, _source, gross in positive:
        excluded = min(gross, exclusions.get(label, 0.0))
        taxable_by_label[label] = max(0.0, gross - excluded)

    total_component_taxable = sum(taxable_by_label.values())
    baseline = max(0.0, baseline_taxable_income)
    incremental_tax = _tax_from_rule(rule, baseline + total_component_taxable) - _tax_from_rule(
        rule, baseline
    )

    estimates: dict[str, StateTaxEstimate] = {}
    for label, source, gross in positive:
        excluded = min(gross, exclusions.get(label, 0.0))
        taxable = taxable_by_label[label]
        tax = (
            incremental_tax * taxable / total_component_taxable
            if total_component_taxable > 0.0
            else 0.0
        )
        estimates[label] = StateTaxEstimate(
            state_code=rule.state_code,
            modeled=True,
            source=source,
            gross_income=_round_money(gross),
            taxable_income=_round_money(taxable),
            tax=_round_money(tax),
            exclusion=_round_money(excluded),
            note=_state_note(rule, source),
            table_version=rule.table_version,
        )
    return estimates


def state_tax_notes(
    rule: StateTaxRule,
    estimates: list[StateTaxEstimate] | tuple[StateTaxEstimate, ...],
) -> tuple[str, ...]:
    """Return public notes for a modeled state-tax result."""

    notes = [estimate.note for estimate in estimates]
    notes.extend(rule.notes)
    if rule.local_income_tax_hook:
        notes.append(f"{rule.state_code} local income-tax hook is flagged but not modeled.")
    if "wa_capital_gains_excise_not_modeled" in rule.flags:
        notes.append(
            "Washington capital-gains excise tax on high earners is flagged but not modeled."
        )
    return tuple(sorted(dict.fromkeys(note for note in notes if note)))


def _state_note(rule: StateTaxRule, source: IncomeSource) -> str:
    if rule.rate_structure == "none":
        return f"{rule.state_code} has no broad-based state individual income tax in this table."
    if source == "social_security" and not rule.ss_taxed:
        return f"{rule.state_code} does not tax Social Security in this table."
    if rule.retirement_exclusion.kind == "full":
        return f"{rule.state_code} full retirement-income exclusion applies when eligible."
    if rule.retirement_exclusion.kind == "capped":
        return f"{rule.state_code} capped retirement-income exclusion applied when eligible."
    if rule.retirement_exclusion.kind == "tiered_percentage":
        return f"{rule.state_code} tiered retirement-income exclusion applied by income band."
    return f"{rule.state_code} state tax estimated from the illustrative reference rule."


def state_code_for_year(
    *,
    base_state: str | None,
    residency_change: StateResidencyChange | None,
    year: int,
) -> str | None:
    """Resolve state residency for a projection year."""

    if base_state is None and residency_change is None:
        return None
    if residency_change is None:
        return _normalize_state_code(base_state, "state")
    if year >= residency_change.year:
        return _normalize_state_code(residency_change.to_state, "residencyChange.to")
    return _normalize_state_code(base_state or residency_change.from_state, "state")


_NO_INCOME_TAX_STATES = frozenset({"AK", "FL", "NV", "SD", "TN", "TX", "WY", "NH", "WA"})


def _no_income_rule(
    code: str, *, flags: tuple[str, ...] = (), notes: tuple[str, ...] = ()
) -> StateTaxRule:
    return StateTaxRule(
        tax_year=2026,
        state_code=code,
        rate_structure="none",
        retirement_exclusion=StateRetirementExclusion(kind="full"),
        flags=flags,
        notes=notes,
        table_version="state-tax-reference-2026-no-income-tax-v1",
    )


_NJ_BANDS = (
    StateRetirementExclusionBand(100_000.0, 1.0, 1.0, 1.0, 1.0),
    StateRetirementExclusionBand(125_000.0, 0.375, 0.50, 0.25, 0.375),
    StateRetirementExclusionBand(150_000.0, 0.1875, 0.25, 0.125, 0.1875),
    StateRetirementExclusionBand(_INF, 0.0, 0.0, 0.0, 0.0),
)

_REFERENCE_STATE_TAX_RULES_2026: dict[str, StateTaxRule] = {
    **{
        code: _no_income_rule(
            code,
            flags=("wa_capital_gains_excise_not_modeled",) if code == "WA" else (),
            notes=(
                "Washington capital-gains excise tax on high earners is flagged but not modeled.",
            )
            if code == "WA"
            else (
                "New Hampshire interest and dividends tax repealed for taxable periods after 2024.",
            )
            if code == "NH"
            else (),
        )
        for code in _NO_INCOME_TAX_STATES
    },
    "PA": StateTaxRule(
        tax_year=2026,
        state_code="PA",
        rate_structure="flat",
        flat_rate=0.0307,
        ss_taxed=False,
        retirement_exclusion=StateRetirementExclusion(kind="full", age_min=59.5),
        table_version="state-tax-reference-2026-pa-revenue-v1",
        notes=("PA retirement-plan distributions are generally excluded at/after retirement age.",),
    ),
    "IL": StateTaxRule(
        tax_year=2026,
        state_code="IL",
        rate_structure="flat",
        flat_rate=0.0495,
        ss_taxed=False,
        retirement_exclusion=StateRetirementExclusion(kind="full"),
        table_version="state-tax-reference-2026-il-revenue-v1",
    ),
    "MS": StateTaxRule(
        tax_year=2026,
        state_code="MS",
        rate_structure="brackets",
        brackets=((10_000.0, 0.0), (_INF, 0.044)),
        ss_taxed=False,
        retirement_exclusion=StateRetirementExclusion(kind="full", age_min=59.5),
        table_version="state-tax-reference-2026-ms-dor-v1",
    ),
    "IA": StateTaxRule(
        tax_year=2026,
        state_code="IA",
        rate_structure="flat",
        flat_rate=0.038,
        ss_taxed=False,
        retirement_exclusion=StateRetirementExclusion(kind="full", age_min=55),
        table_version="state-tax-reference-2026-ia-dor-v1",
    ),
    "CO": StateTaxRule(
        tax_year=2026,
        state_code="CO",
        rate_structure="flat",
        flat_rate=0.044,  # VERIFY-2026: confirm current flat rate before advice.
        ss_taxed=False,
        retirement_exclusion=StateRetirementExclusion(kind="capped", age_min=55, amount=20_000.0),
        table_version="state-tax-reference-2026-co-retirees-v1",
        notes=(
            "VERIFY-2026: Colorado 65+ cap/full-subtraction updates require final-form review.",
        ),
    ),
    "NY": StateTaxRule(
        tax_year=2026,
        state_code="NY",
        rate_structure="flat",
        flat_rate=0.0685,  # VERIFY-2026: illustrative mid-bracket proxy, not the NY tax table.
        ss_taxed=False,
        retirement_exclusion=StateRetirementExclusion(
            kind="capped",
            age_min=59.5,
            amount=20_000.0,
            government_pension_full_exempt=True,
        ),
        table_version="state-tax-reference-2026-ny-dtf-v1",
    ),
    "VA": StateTaxRule(
        tax_year=2026,
        state_code="VA",
        rate_structure="flat",
        flat_rate=0.0575,  # VERIFY-2026: illustrative top marginal proxy.
        ss_taxed=False,
        retirement_exclusion=StateRetirementExclusion(
            kind="capped",
            age_min=65,
            amount=12_000.0,
            phaseout_threshold_single=50_000.0,
            phaseout_threshold_head_of_household=50_000.0,
            phaseout_threshold_married_joint=75_000.0,
            phaseout_threshold_married_separate=75_000.0,
            phaseout_rate=1.0,
        ),
        table_version="state-tax-reference-2026-va-age-deduction-v1",
    ),
    "NJ": StateTaxRule(
        tax_year=2026,
        state_code="NJ",
        rate_structure="flat",
        flat_rate=0.05525,  # VERIFY-2026: illustrative bracket proxy.
        ss_taxed=False,
        retirement_exclusion=StateRetirementExclusion(
            kind="tiered_percentage",
            age_min=62,
            bands=_NJ_BANDS,
        ),
        table_version="state-tax-reference-2026-nj-retirement-exclusion-v1",
    ),
    "MD": StateTaxRule(
        tax_year=2026,
        state_code="MD",
        rate_structure="flat",
        flat_rate=0.0575,  # VERIFY-2026: state-only top marginal proxy; local hook flagged.
        ss_taxed=False,
        retirement_exclusion=StateRetirementExclusion(kind="capped", age_min=65, amount=40_600.0),
        local_income_tax_hook=True,
        table_version="state-tax-reference-2026-md-pension-exclusion-v1",
        notes=("VERIFY-2026: local county income-tax layer is flagged but not modeled.",),
    ),
    "DE": StateTaxRule(
        tax_year=2026,
        state_code="DE",
        rate_structure="flat",
        flat_rate=0.066,
        ss_taxed=False,
        retirement_exclusion=StateRetirementExclusion(
            kind="capped", age_min=60, amount=12_500.0, under_age_amount=2_000.0
        ),
        table_version="state-tax-reference-2026-de-revenue-faq-v1",
    ),
}


def reference_state_tax_rule(state_code: str, tax_year: int = 2026) -> StateTaxRule | None:
    """Return the illustrative state-tax rule for ``state_code`` / ``tax_year``."""

    if tax_year != 2026:
        raise TableError("state tax reference rules are registered only for tax year 2026")
    code = _normalize_state_code(state_code, "state_code")
    assert code is not None
    return _REFERENCE_STATE_TAX_RULES_2026.get(code)


__all__ = [
    "IncomeSource",
    "RateStructure",
    "RetirementExclusionKind",
    "StateResidencyChange",
    "StateRetirementExclusion",
    "StateRetirementExclusionBand",
    "StateTaxEstimate",
    "StateTaxRule",
    "estimate_state_income_tax",
    "estimate_state_income_tax_components",
    "reference_state_tax_rule",
    "retirement_exclusion_amount",
    "state_code_for_year",
    "state_tax_notes",
]
