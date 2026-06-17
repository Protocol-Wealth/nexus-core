# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF Check 5 — Perez Phase (technology adoption cycle position).

Ported from the Protocol Wealth research engine (``portfolio_engine``
``_check_perez_cycle`` for the verdict logic, and ``framework_engine``
``_calculate_perez`` for the capex/revenue phase computation).

Carlota Perez, *Technological Revolutions and Financial Capital* (2002),
splits each ~50-year technological revolution into Installation (financial
capital funds new tech) -> Frenzy (speculation) -> Turning Point
(crash/regulation) -> Deployment (production capital spreads the tech).

The check is binary: **pass if the asset's phase is Installation or
Deployment, fail if Frenzy or Turning Point**. Installation and Deployment
are the productive phases for capital allocation; Frenzy and Turning Point
carry elevated cycle risk.

Phase resolution (matches pw-nexus precedence):

1. An explicit phase string already on the context — ``ctx.fundamentals``
   / ``ctx.extra`` ``"perez_phase"`` (e.g. from a sector model or a static
   per-ticker profile). The string is normalised the same way pw-nexus
   normalises ``analysis.perez.phase``: substrings "Installation",
   "Frenzy", "Deployment"/"Synergy", "Turning".
2. Otherwise, dynamic detection from capex/revenue growth (``_calculate_perez``).

Layer override (pw-nexus): L1-L3 infrastructure names are building the
physical layer of the current cycle; a "Frenzy" reading is reclassified to
Installation for those layers, since infrastructure buildout is itself
Installation-phase activity.

Best-effort: when neither a phase string nor enough statements to compute
one are present, returns ``passed=None`` / ``signal="insufficient_data"``.
"""

from __future__ import annotations

from typing import Any

from ..checks import CheckResult, ScoringContext

# Frenzy-score thresholds — verbatim from pw-nexus framework_engine.py.
PEREZ_FRENZY_START = 0.65  # Early frenzy
PEREZ_FRENZY_LATE = 0.80  # Late frenzy (danger)

# Canonical phase labels.
INSTALLATION = "Installation"
FRENZY = "Frenzy"
TURNING_POINT = "Turning Point"
DEPLOYMENT = "Deployment"

# Phases that pass Check 5.
_PASSING_PHASES = frozenset({INSTALLATION, DEPLOYMENT})

# Layers whose Frenzy reading is reclassified to Installation (infrastructure
# buildout is Installation-phase activity even during a broader Frenzy).
_INFRASTRUCTURE_LAYERS = frozenset({"L1", "L2", "L3"})

THRESHOLD = "Installation or Deployment"


def _to_float(value: Any) -> float | None:
    """Coerce a provider value (number, ``{"raw": ...}``, or str) to float."""
    if isinstance(value, dict):
        value = value.get("raw")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_val(statement: Any, *keys: str) -> float:
    """First present numeric value among ``keys`` in a statement dict; else 0.0."""
    if not isinstance(statement, dict):
        return 0.0
    for key in keys:
        coerced = _to_float(statement.get(key))
        if coerced is not None:
            return coerced
    return 0.0


def normalize_phase(phase_str: str | None) -> str | None:
    """Map a free-text phase label to a canonical phase.

    Mirrors pw-nexus ``_check_perez_cycle`` substring matching. Returns one of
    the four canonical phases, or ``None`` if the string carries no recognised
    phase token (e.g. "Unclassified").
    """
    if not phase_str:
        return None
    if "Installation" in phase_str:
        return INSTALLATION
    if "Frenzy" in phase_str:
        return FRENZY
    if "Deployment" in phase_str or "Synergy" in phase_str:
        return DEPLOYMENT
    if "Turning" in phase_str:
        return TURNING_POINT
    return None


def compute_perez_phase(
    income_statements: list[dict[str, Any]] | None,
    cash_flows: list[dict[str, Any]] | None,
) -> str | None:
    """Detect the Perez phase from capex vs revenue growth.

    Faithful port of pw-nexus ``_calculate_perez``:

    - Installation: capex growth > revenue growth (building infrastructure)
    - Deployment: revenue growth >= capex growth (harvesting returns)
    - Frenzy / Early Frenzy: high frenzy-score (capex outpacing, both growing fast)

    For a capex-light subject (no PP&E capex — banks, REITs, insurers) the phase
    is derived from revenue growth alone (D8): contraction (< -10%) -> Turning
    Point; steady (-10%..+40%) -> Deployment; implausibly fast (> +40%) -> Frenzy.

    Returns the phase label string (one of "Installation", "Deployment",
    "Frenzy", "Early Frenzy", "Turning Point"), or ``None`` when data is
    insufficient (fewer than two income statements, no cash flows, or neither
    capex nor revenue present).
    """
    if not income_statements or len(income_statements) < 2:
        return None
    if not cash_flows:
        return None

    inc = income_statements
    cf = cash_flows

    curr_rev = _get_val(inc[0], "revenue", "totalRevenue")
    prev_rev = _get_val(inc[1], "revenue", "totalRevenue")

    # Some providers use "capitalExpenditure" (singular); MBOUM the plural
    # form; the nexus-core SEC fetcher emits snake_case "capital_expenditure".
    _capex_keys = ("capitalExpenditures", "capitalExpenditure", "capital_expenditure")
    curr_capex = abs(_get_val(cf[0], *_capex_keys))
    prev_capex = abs(_get_val(cf[1], *_capex_keys)) if len(cf) > 1 else curr_capex

    # Capex-light subject (banks, REITs, insurers — no PP&E capex). The
    # capex-vs-revenue detector below can't run, so derive the phase from
    # revenue growth alone, per the operator-ratified bands (D8): a steady or
    # modestly-growing business is in Deployment (PASS); a contracting one is at
    # a Turning Point (FAIL); implausibly fast growth for a capex-light business
    # reads as Frenzy (FAIL). No revenue either → still undeterminable.
    if curr_capex == 0 and prev_capex == 0:
        if curr_rev <= 0:
            return None
        rev_only_growth = (curr_rev - prev_rev) / prev_rev if prev_rev > 0 else 0.0
        if rev_only_growth < -0.10:
            return TURNING_POINT
        if rev_only_growth > 0.40:
            return FRENZY
        return DEPLOYMENT

    rev_growth = (curr_rev - prev_rev) / prev_rev if prev_rev > 0 else 0.0
    capex_growth = (curr_capex - prev_capex) / prev_capex if prev_capex > 0 else 0.0

    frenzy_score = 0.0
    if capex_growth > 0.3:
        frenzy_score += 0.3
    if rev_growth > 0.2:
        frenzy_score += 0.2
    if capex_growth > rev_growth:
        frenzy_score += 0.2
    if capex_growth > 0.5:
        frenzy_score += 0.15
    if rev_growth > 0.4:
        frenzy_score += 0.15

    if frenzy_score > PEREZ_FRENZY_LATE:
        return FRENZY
    if frenzy_score > PEREZ_FRENZY_START:
        return "Early Frenzy"
    if capex_growth > rev_growth:
        return INSTALLATION
    return DEPLOYMENT


class PerezPhaseCheck:
    """EMF Check 5 — Perez technology-cycle position.

    Passes when the asset's phase is Installation or Deployment.

    Phase source precedence:
      1. ``ctx.fundamentals["perez_phase"]`` or ``ctx.extra["perez_phase"]``
         — a phase string from a sector/ticker model (``needs_upstream``).
      2. Dynamic capex/revenue detection from
         ``ctx.fundamentals["income_statements"]`` + ``["cash_flows"]``.

    Layer (``ctx.fundamentals["layer"]`` / ``ctx.extra["layer"]``, e.g. "L1")
    drives the infrastructure override: a Frenzy reading on L1-L3 becomes
    Installation.
    """

    check_number = 5
    name = "Perez Phase"

    def __init__(self, threshold: str = THRESHOLD) -> None:
        self.threshold = threshold

    def _resolve_layer(self, ctx: ScoringContext) -> str | None:
        layer = ctx.fundamentals.get("layer") or ctx.extra.get("layer")
        return str(layer) if layer else None

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        # 1) Explicit phase string from an upstream model, if present.
        raw_phase = ctx.fundamentals.get("perez_phase") or ctx.extra.get("perez_phase")
        current_phase = normalize_phase(raw_phase if isinstance(raw_phase, str) else None)

        # 2) Otherwise compute dynamically from capex/revenue growth.
        if current_phase is None:
            computed = compute_perez_phase(
                ctx.fundamentals.get("income_statements"),
                ctx.fundamentals.get("cash_flows"),
            )
            current_phase = normalize_phase(computed)

        if current_phase is None:
            return CheckResult(
                check_number=self.check_number,
                name=self.name,
                value=None,
                threshold=self.threshold,  # type: ignore[arg-type]
                passed=None,
                signal="insufficient_data",
                interpretation="Phase detection unavailable",
                details={"current_phase": "N/A"},
            )

        # Infrastructure safeguard: L1-L3 buildout is Installation-phase activity
        # even during a broader Frenzy.
        layer = self._resolve_layer(ctx)
        override_applied = False
        if current_phase == FRENZY and layer in _INFRASTRUCTURE_LAYERS:
            current_phase = INSTALLATION
            override_applied = True

        passed = current_phase in _PASSING_PHASES
        if passed:
            signal = "favorable"
            interp = f"{current_phase} phase — favorable for capital deployment"
        else:
            signal = "elevated_risk"
            interp = f"{current_phase} phase — elevated cycle risk"

        details: dict[str, Any] = {"current_phase": current_phase}
        if layer:
            details["layer"] = layer
        if override_applied:
            details["infrastructure_override"] = True

        return CheckResult(
            check_number=self.check_number,
            name=self.name,
            value=None,
            threshold=self.threshold,  # type: ignore[arg-type]
            passed=passed,
            signal=signal,
            interpretation=interp,
            details=details,
        )


__all__ = [
    "PerezPhaseCheck",
    "compute_perez_phase",
    "normalize_phase",
    "PEREZ_FRENZY_START",
    "PEREZ_FRENZY_LATE",
]
