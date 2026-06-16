# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""PlanningContract — the PII-free case shape for multi-year Roth-conversion analysis.

This module is the **canonical, language-neutral input contract** for the
Roth-conversion + IRMAA planning capability. It is the ABI between the engine
(nexus-core, Python), the planning UI (pwplan-core, React), and the
application/workflow layer (pw-api, which brokers calls and owns the
identity↔de-identified boundary, HITL, and retention).

Three properties make it safe to open-source and to point at either the public
MCP backend or a private application:

- **PII-free by construction.** No identity field exists anywhere in the shape:
  an opaque ``case_id`` (never identity-derived), *birth years* not dates of
  birth, *aggregated* balances, no name/SSN/account number. This is Protocol
  Wealth's Reg S-P §248.30(b) design — the boundary is the schema, not a runtime
  scrub. ``app/planning/contract.py`` adds a fail-closed structural tripwire on
  top of this.
- **Versioned.** :data:`PLANNING_CONTRACT_VERSION` is semver. A breaking change
  to any request/response shape is a cross-repo contract event: bump the major
  and note it in each repo's CHANGELOG. The canonical JSON-Schema lives beside
  this module (``planning_contract.schema.json``); the TypeScript mirror lives in
  ``@protocolwealthos/planning-contract``.
- **Table-free.** The contract carries the *case*, never the tax/IRMAA tables.
  Bracket + tier tables are injected at call time so the caller can snapshot the
  exact figures used into its retention record (see :mod:`.tables`).

Design choice: this is a frozen ``dataclass`` (not a pydantic model). The shape
is a canonical, snapshot-able value object consumed by the pure-math engine
layer, which is pydantic-free by design; runtime validation lives in
:meth:`PlanningContract.from_dict`, mirroring the manual validation the planning
gateway already performs.

Versioning note: this is the **case contract** (``PLANNING_CONTRACT_VERSION``,
v1.0.0) — the structured Roth/IRMAA case object. It is distinct from, and
coexists with, the per-tool gateway envelope version in
``app/planning/contract.py`` (``CONTRACT_VERSION``, the 19 single-purpose
planning tools). The two version on independent timelines.

v1 scope (documented exclusions — adding any of these is a MAJOR bump):
- Only IRA-class pre-tax money via ``trad_ira_aggregate``. Employer-plan
  balances (401(k)/403(b)) are out of scope: their still-working RMD exception
  and separate pro-rata treatment differ, so they are not folded into the
  aggregate.
- No explicit deceased-spouse / survivor-year flag. Survivor-filing compression
  is modelled only as a *rationale* (and reachable by analysing an ``mfs``/
  ``single`` case), not as a future-dated transition input.
- No inherited-IRA 10-year-drain modelling (the SECURE-Act heir arbitrage is a
  narrative ``purpose`` framing, not a modelled cash flow).

Educational scenario analysis only — not investment, tax, or legal advice.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, fields
from importlib import resources
from typing import Any, Literal, cast

from .tax import FilingStatus

#: Semver for the PlanningContract + RothConversionAnalysis shapes. Bump the
#: MAJOR on any breaking change to either; coordinate across nexus-core /
#: pwos-core / pwplan-core and record it in every CHANGELOG.
PLANNING_CONTRACT_VERSION = "1.1.0"

#: Filing statuses the contract accepts. Deliberately narrower than the engine's
#: full set: a single retiree is ``single``, a couple is ``mfj``, and ``mfs`` is
#: the survivor-filing-compression edge. Head-of-household is out of scope for v1
#: (it does not arise in the joint→single retirement-conversion thesis).
ContractFilingStatus = Literal["single", "mfj", "mfs"]

#: How the caller wants each year's conversion sized.
TargetRule = Literal["fill_to_rate", "fill_to_irmaa_tier", "fixed_amount"]

#: Optional framing for the composite — drives narrative, never the math.
Purpose = Literal["tax_smoothing", "irmaa_management", "legacy"]

#: ContractFilingStatus → the engine's FilingStatus literal.
_FILING_STATUS_MAP: dict[ContractFilingStatus, FilingStatus] = {
    "single": "single",
    "mfj": "married_joint",
    "mfs": "married_separate",
}

_CONTRACT_FILING_STATUSES: tuple[ContractFilingStatus, ...] = ("single", "mfj", "mfs")
_TARGET_RULES: tuple[TargetRule, ...] = ("fill_to_rate", "fill_to_irmaa_tier", "fixed_amount")
_PURPOSES: tuple[Purpose, ...] = ("tax_smoothing", "irmaa_management", "legacy")


class PlanningContractError(ValueError):
    """A malformed or invalid PlanningContract (maps to HTTP 400 at the gateway)."""


def engine_filing_status(status: ContractFilingStatus) -> FilingStatus:
    """Map the contract's compact filing status to the engine's ``FilingStatus``."""
    return _FILING_STATUS_MAP[status]


def planning_contract_schema() -> dict[str, Any]:
    """Load the canonical PlanningContract JSON-Schema (Draft 2020-12).

    The ``planning_contract.schema.json`` file beside this module is the
    cross-language source of truth; this loader exposes it to Python callers + the
    in-sync test. The TypeScript mirror copies the same schema.
    """
    text = (
        resources.files("nexus_core.engine.planning") / "planning_contract.schema.json"
    ).read_text(encoding="utf-8")
    return cast(dict[str, Any], json.loads(text))


@dataclass(frozen=True, slots=True)
class IncomeExConversion:
    """Projected income for ``tax_year`` **before** any conversion.

    Every field is an annual dollar amount. Realized capital losses live in
    ``short_term_gains`` / ``long_term_gains`` as negative values.
    ``tax_exempt_interest`` is reported because it feeds the IRMAA MAGI even
    though it is not federally taxable.
    """

    wages: float = 0.0
    pension: float = 0.0
    social_security_gross: float = 0.0
    taxable_interest: float = 0.0
    tax_exempt_interest: float = 0.0
    ordinary_dividends: float = 0.0
    qualified_dividends: float = 0.0
    short_term_gains: float = 0.0
    long_term_gains: float = 0.0
    other_ordinary: float = 0.0
    above_the_line: float = 0.0
    #: ``"standard"`` to take the standard deduction, or a dollar amount to itemize.
    itemized_or_standard: Literal["standard"] | float = "standard"

    def __post_init__(self) -> None:
        if self.qualified_dividends < 0.0:
            raise PlanningContractError("qualified_dividends must be non-negative")
        if self.qualified_dividends > self.ordinary_dividends + 1e-6:
            raise PlanningContractError(
                "qualified_dividends cannot exceed ordinary_dividends "
                "(qualified is a subset of ordinary)"
            )
        for name in ("wages", "pension", "social_security_gross", "tax_exempt_interest",
                     "ordinary_dividends", "above_the_line"):
            if getattr(self, name) < 0.0:
                raise PlanningContractError(f"{name} must be non-negative")
        if not (self.itemized_or_standard == "standard" or isinstance(self.itemized_or_standard, (int, float))):
            raise PlanningContractError('itemized_or_standard must be "standard" or a number')
        if isinstance(self.itemized_or_standard, (int, float)) and self.itemized_or_standard < 0.0:
            raise PlanningContractError("itemized deduction amount must be non-negative")


@dataclass(frozen=True, slots=True)
class AccountBalances:
    """Aggregated, de-identified balances. No per-account identifiers.

    ``trad_ira_aggregate`` sums **all** Traditional/SEP/SIMPLE IRA balances —
    the pro-rata rule (IRC §72) applies across the total, so they cannot be
    analysed in isolation. ``taxable_liquidity`` is cash available **outside**
    the IRA to pay the conversion tax. ``employer_plan_aggregate`` (added in
    contract v1.1.0) is pre-tax employer-plan money (401(k)/403(b)); it is **not**
    directly convertible (roll to an IRA first) but it adds to the future RMD drag.
    """

    trad_ira_aggregate: float
    nondeductible_basis: float = 0.0
    roth_balance: float = 0.0
    first_roth_year: int | None = None
    taxable_liquidity: float = 0.0
    employer_plan_aggregate: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "trad_ira_aggregate", "nondeductible_basis", "roth_balance",
            "taxable_liquidity", "employer_plan_aggregate",
        ):
            if getattr(self, name) < 0.0:
                raise PlanningContractError(f"{name} must be non-negative")
        if self.nondeductible_basis > self.trad_ira_aggregate + 1e-6:
            raise PlanningContractError(
                "nondeductible_basis cannot exceed trad_ira_aggregate"
            )
        if self.first_roth_year is not None and not 1998 <= self.first_roth_year <= 2100:
            raise PlanningContractError("first_roth_year must be a plausible year or null")


@dataclass(frozen=True, slots=True)
class ConversionIntent:
    """What the caller wants to do, and over which years."""

    target_rule: TargetRule
    years: tuple[int, ...]
    target_rate: float | None = None
    fixed_amount: float | None = None
    purpose: Purpose | None = None

    def __post_init__(self) -> None:
        if self.target_rule not in _TARGET_RULES:
            raise PlanningContractError(f"target_rule must be one of {', '.join(_TARGET_RULES)}")
        if not self.years:
            raise PlanningContractError("intent.years must be a non-empty list of years")
        if len(set(self.years)) != len(self.years):
            raise PlanningContractError("intent.years must not contain duplicates")
        for y in self.years:
            if not 2000 <= y <= 2100:
                raise PlanningContractError(f"intent.years contains an implausible year: {y}")
        if self.target_rule == "fill_to_rate" and self.target_rate is None:
            raise PlanningContractError("target_rate is required when target_rule is 'fill_to_rate'")
        if self.target_rate is not None and not 0.0 < self.target_rate < 1.0:
            raise PlanningContractError("target_rate must be in (0, 1)")
        if self.target_rule == "fixed_amount" and self.fixed_amount is None:
            raise PlanningContractError("fixed_amount is required when target_rule is 'fixed_amount'")
        if self.fixed_amount is not None and self.fixed_amount <= 0.0:
            raise PlanningContractError("fixed_amount must be positive")
        # Reject silently-ignored cross-field params so the UI and engine never
        # disagree about what was requested. (target_rate IS used as an optional
        # bracket cap under fill_to_irmaa_tier, so it is only rejected here for
        # fixed_amount; fixed_amount is meaningful only for the fixed_amount rule.)
        if self.fixed_amount is not None and self.target_rule != "fixed_amount":
            raise PlanningContractError(
                f"fixed_amount is not used by target_rule '{self.target_rule}'"
            )
        if self.target_rate is not None and self.target_rule == "fixed_amount":
            raise PlanningContractError("target_rate is not used by target_rule 'fixed_amount'")
        if self.purpose is not None and self.purpose not in _PURPOSES:
            raise PlanningContractError(f"purpose must be one of {', '.join(_PURPOSES)} or null")


@dataclass(frozen=True, slots=True)
class PlanningContract:
    """The PII-free planning case. The canonical input to the composite engine.

    See the module docstring for the PII-free / versioned / table-free
    invariants. Construct from an untrusted dict with :meth:`from_dict`, which
    validates and raises :class:`PlanningContractError` with a human-readable
    message.
    """

    case_id: str
    tax_year: int
    filing_status: ContractFilingStatus
    state_code: str
    birth_years: tuple[int, ...]
    income_ex_conversion: IncomeExConversion
    accounts: AccountBalances
    intent: ConversionIntent
    medicare_enrolled: int = 0
    contract_version: str = PLANNING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.case_id or not isinstance(self.case_id, str):
            raise PlanningContractError("case_id must be a non-empty string")
        if self.filing_status not in _CONTRACT_FILING_STATUSES:
            raise PlanningContractError(
                f"filing_status must be one of {', '.join(_CONTRACT_FILING_STATUSES)}"
            )
        if not 2000 <= self.tax_year <= 2100:
            raise PlanningContractError("tax_year must be a plausible year")
        if not (isinstance(self.state_code, str) and len(self.state_code) == 2 and self.state_code.isalpha()):
            raise PlanningContractError("state_code must be a 2-letter US state/territory code")
        n = len(self.birth_years)
        if n not in (1, 2):
            raise PlanningContractError("birth_years must hold one (self) or two (self, spouse) years")
        for by in self.birth_years:
            if not 1900 <= by <= self.tax_year:
                raise PlanningContractError(f"birth_years contains an implausible year: {by}")
        if self.filing_status == "single" and n != 1:
            raise PlanningContractError("a 'single' filer has exactly one birth year")
        if self.filing_status == "mfj" and n != 2:
            raise PlanningContractError("'mfj' requires two birth years (self, spouse)")
        if not 0 <= self.medicare_enrolled <= n:
            raise PlanningContractError(
                f"medicare_enrolled must be between 0 and {n} (one per person in birth_years)"
            )
        if self.tax_year != min(self.intent.years):
            raise PlanningContractError(
                "tax_year must be the FIRST (earliest) year in intent.years"
            )

    @property
    def engine_filing_status(self) -> FilingStatus:
        """The engine's ``FilingStatus`` literal for this contract's filing status."""
        return engine_filing_status(self.filing_status)

    def ages_in(self, year: int) -> tuple[int, ...]:
        """Each person's age at year-end in ``year`` (same order as ``birth_years``)."""
        return tuple(year - by for by in self.birth_years)

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> PlanningContract:
        """Validate + construct a PlanningContract from an untrusted JSON object.

        Raises :class:`PlanningContractError` (human-readable) on any malformed
        field. Unknown top-level keys are rejected to fail closed on typos and on
        accidental identity smuggling.
        """
        if not isinstance(payload, dict):
            raise PlanningContractError("planning contract must be a JSON object")

        version = payload.get("contract_version", PLANNING_CONTRACT_VERSION)
        _require_major_match(version)

        allowed = {
            "case_id", "tax_year", "filing_status", "state_code", "birth_years",
            "medicare_enrolled", "income_ex_conversion", "accounts", "intent",
            "contract_version",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise PlanningContractError(f"unknown contract field(s): {', '.join(sorted(unknown))}")

        try:
            contract = PlanningContract(
                case_id=_req_str(payload, "case_id"),
                tax_year=_req_int(payload, "tax_year"),
                filing_status=cast(ContractFilingStatus, _req_str(payload, "filing_status")),
                state_code=_req_str(payload, "state_code").upper(),
                birth_years=_req_int_tuple(payload, "birth_years"),
                medicare_enrolled=_opt_int(payload, "medicare_enrolled", 0),
                income_ex_conversion=_parse_income(payload.get("income_ex_conversion", {})),
                accounts=_parse_accounts(_req_obj(payload, "accounts")),
                intent=_parse_intent(_req_obj(payload, "intent")),
                contract_version=str(version),
            )
        except PlanningContractError:
            raise
        except (TypeError, ValueError) as exc:  # defensive: surface as a clean 400
            raise PlanningContractError(str(exc)) from exc
        return contract


#: Strict semver-core (matches the JSON-Schema ``pattern``); no pre-release/build
#: suffixes, no extra segments, no surrounding whitespace.
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _require_major_match(version: Any) -> None:
    if not isinstance(version, str) or not _SEMVER_RE.match(version):
        raise PlanningContractError(
            "contract_version must be a semver string 'MAJOR.MINOR.PATCH'"
        )
    want = PLANNING_CONTRACT_VERSION.split(".", 1)[0]
    got = version.split(".", 1)[0]
    if got != want:
        raise PlanningContractError(
            f"contract_version major mismatch: engine speaks {PLANNING_CONTRACT_VERSION}, "
            f"got {version}. Pin versions before retrying."
        )


# --- typed dict accessors (clean 400s on the wrong shape) ------------------


def _req_obj(body: dict[str, Any], key: str) -> dict[str, Any]:
    value = body.get(key)
    if not isinstance(value, dict):
        raise PlanningContractError(f"'{key}' must be an object")
    return value


def _req_str(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise PlanningContractError(f"'{key}' must be a non-empty string")
    return value


def _req_int(body: dict[str, Any], key: str) -> int:
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanningContractError(f"'{key}' must be an integer")
    return value


def _opt_int(body: dict[str, Any], key: str, default: int) -> int:
    if key not in body or body[key] is None:
        return default
    return _req_int(body, key)


def _req_int_tuple(body: dict[str, Any], key: str) -> tuple[int, ...]:
    value = body.get(key)
    if not isinstance(value, list) or not value:
        raise PlanningContractError(f"'{key}' must be a non-empty list of integers")
    out: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise PlanningContractError(f"'{key}' must contain only integers")
        out.append(item)
    return tuple(out)


def _reject_unknown(obj: dict[str, Any], allowed: set[str], where: str) -> None:
    """Fail closed on unknown nested keys (typos + accidental identity smuggling).

    Mirrors the JSON-Schema's ``additionalProperties: false`` on every nested
    object — without this the parser would silently drop anything it doesn't
    pluck, which is a hole in the PII-free claim (a value nested under an
    unrecognised key would never be inspected).
    """
    unknown = set(obj) - allowed
    if unknown:
        raise PlanningContractError(f"unknown {where} field(s): {', '.join(sorted(unknown))}")


def _num(obj: dict[str, Any], key: str, default: float = 0.0) -> float:
    if key not in obj or obj[key] is None:
        return default
    value = obj[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanningContractError(f"'{key}' must be a number")
    if not math.isfinite(value):
        raise PlanningContractError(f"'{key}' must be a finite number (no NaN/Infinity)")
    return float(value)


def _parse_income(obj: Any) -> IncomeExConversion:
    if not isinstance(obj, dict):
        raise PlanningContractError("income_ex_conversion must be an object")
    _reject_unknown(obj, {f.name for f in fields(IncomeExConversion)}, "income_ex_conversion")
    ded = obj.get("itemized_or_standard", "standard")
    if ded != "standard":
        if isinstance(ded, bool) or not isinstance(ded, (int, float)):
            raise PlanningContractError('itemized_or_standard must be "standard" or a number')
        ded = float(ded)
    return IncomeExConversion(
        wages=_num(obj, "wages"),
        pension=_num(obj, "pension"),
        social_security_gross=_num(obj, "social_security_gross"),
        taxable_interest=_num(obj, "taxable_interest"),
        tax_exempt_interest=_num(obj, "tax_exempt_interest"),
        ordinary_dividends=_num(obj, "ordinary_dividends"),
        qualified_dividends=_num(obj, "qualified_dividends"),
        short_term_gains=_num(obj, "short_term_gains"),
        long_term_gains=_num(obj, "long_term_gains"),
        other_ordinary=_num(obj, "other_ordinary"),
        above_the_line=_num(obj, "above_the_line"),
        itemized_or_standard=ded,
    )


def _parse_accounts(obj: dict[str, Any]) -> AccountBalances:
    _reject_unknown(obj, {f.name for f in fields(AccountBalances)}, "accounts")
    first_roth = obj.get("first_roth_year")
    if first_roth is not None and (isinstance(first_roth, bool) or not isinstance(first_roth, int)):
        raise PlanningContractError("first_roth_year must be an integer or null")
    return AccountBalances(
        trad_ira_aggregate=_num(obj, "trad_ira_aggregate"),
        nondeductible_basis=_num(obj, "nondeductible_basis"),
        roth_balance=_num(obj, "roth_balance"),
        first_roth_year=first_roth,
        taxable_liquidity=_num(obj, "taxable_liquidity"),
        employer_plan_aggregate=_num(obj, "employer_plan_aggregate"),
    )


def _parse_intent(obj: dict[str, Any]) -> ConversionIntent:
    _reject_unknown(obj, {f.name for f in fields(ConversionIntent)}, "intent")
    rule = obj.get("target_rule")
    if not isinstance(rule, str):
        raise PlanningContractError("intent.target_rule must be a string")
    target_rate = obj.get("target_rate")
    if target_rate is not None and (isinstance(target_rate, bool) or not isinstance(target_rate, (int, float))):
        raise PlanningContractError("intent.target_rate must be a number or null")
    fixed = obj.get("fixed_amount")
    if fixed is not None and (isinstance(fixed, bool) or not isinstance(fixed, (int, float))):
        raise PlanningContractError("intent.fixed_amount must be a number or null")
    purpose = obj.get("purpose")
    if purpose is not None and not isinstance(purpose, str):
        raise PlanningContractError("intent.purpose must be a string or null")
    return ConversionIntent(
        target_rule=cast(TargetRule, rule),
        years=_req_int_tuple(obj, "years"),
        target_rate=float(target_rate) if target_rate is not None else None,
        fixed_amount=float(fixed) if fixed is not None else None,
        purpose=cast("Purpose | None", purpose),
    )


__all__ = [
    "PLANNING_CONTRACT_VERSION",
    "AccountBalances",
    "ContractFilingStatus",
    "ConversionIntent",
    "IncomeExConversion",
    "PlanningContract",
    "PlanningContractError",
    "Purpose",
    "TargetRule",
    "engine_filing_status",
    "planning_contract_schema",
]
