# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Valuation + composite analysis models.

Pure functions; no third-party dep on the import path.

Models implemented:
    - DCF (perpetuity-growth terminal)
    - CAPM expected return
    - WACC
    - DuPont (3-step and 5-step ROE decomposition)
    - Altman Z-Score (manufacturing variant)

Specific formulas are standard textbook finance; no FinanceToolkit code
copied. The shapes (input dataclasses, output dataclass) are
re-derivable; only the computation kernels matter for IP.
"""

from __future__ import annotations

from dataclasses import dataclass

from .statements import StatementBundle

# ─── DCF ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DcfInputs:
    """Inputs for a perpetuity-growth DCF."""

    free_cash_flows: list[float]  # years 1..N forecast FCFs
    terminal_growth: float  # g
    discount_rate: float  # WACC or required return
    net_debt: float = 0.0
    shares_outstanding: float | None = None


@dataclass(frozen=True)
class DcfResult:
    enterprise_value: float
    equity_value: float
    per_share_value: float | None


def dcf_value(inputs: DcfInputs) -> DcfResult:
    """Compute enterprise + equity value via perpetuity-growth DCF."""
    if inputs.discount_rate <= inputs.terminal_growth:
        raise ValueError(
            "discount_rate must exceed terminal_growth for a finite DCF"
        )
    if not inputs.free_cash_flows:
        raise ValueError("at least one forecast FCF is required")

    pv_explicit = 0.0
    for n, fcf in enumerate(inputs.free_cash_flows, start=1):
        pv_explicit += fcf / ((1 + inputs.discount_rate) ** n)

    n = len(inputs.free_cash_flows)
    terminal_fcf = inputs.free_cash_flows[-1] * (1 + inputs.terminal_growth)
    terminal_value = terminal_fcf / (inputs.discount_rate - inputs.terminal_growth)
    pv_terminal = terminal_value / ((1 + inputs.discount_rate) ** n)

    ev = pv_explicit + pv_terminal
    equity = ev - inputs.net_debt
    per_share = (
        equity / inputs.shares_outstanding
        if inputs.shares_outstanding and inputs.shares_outstanding > 0
        else None
    )
    return DcfResult(enterprise_value=ev, equity_value=equity, per_share_value=per_share)


# ─── CAPM ────────────────────────────────────────────────────────────


def capm_expected_return(
    risk_free_rate: float,
    beta: float,
    market_risk_premium: float,
) -> float:
    """Expected return = rf + β × (E[Rm] − rf)."""
    return risk_free_rate + beta * market_risk_premium


# ─── WACC ────────────────────────────────────────────────────────────


def wacc(
    market_value_equity: float,
    market_value_debt: float,
    cost_of_equity: float,
    cost_of_debt: float,
    tax_rate: float,
) -> float:
    """Weighted average cost of capital."""
    total = market_value_equity + market_value_debt
    if total == 0:
        raise ValueError("market_value_equity + market_value_debt must be > 0")
    we = market_value_equity / total
    wd = market_value_debt / total
    return we * cost_of_equity + wd * cost_of_debt * (1 - tax_rate)


# ─── DuPont ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DupontThreeStep:
    """ROE = net_margin × asset_turnover × leverage."""

    net_margin: float | None
    asset_turnover: float | None
    equity_multiplier: float | None  # leverage = total_assets / total_equity
    roe: float | None


@dataclass(frozen=True)
class DupontFiveStep:
    """Decomposition: ROE = (NI/EBT) × (EBT/EBIT) × (EBIT/Sales) × (Sales/Assets) × (Assets/Equity)."""

    tax_burden: float | None       # NI / EBT
    interest_burden: float | None  # EBT / EBIT
    operating_margin: float | None # EBIT / Sales
    asset_turnover: float | None   # Sales / Assets
    equity_multiplier: float | None
    roe: float | None


def _maybe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def dupont_three_step(bundle: StatementBundle) -> DupontThreeStep:
    inc = bundle.income
    bs = bundle.balance
    nm = _maybe_div(inc.net_income, inc.revenue)
    at = _maybe_div(inc.revenue, bs.total_assets)
    em = _maybe_div(bs.total_assets, bs.total_equity)
    roe = (nm * at * em) if (nm is not None and at is not None and em is not None) else None
    return DupontThreeStep(net_margin=nm, asset_turnover=at, equity_multiplier=em, roe=roe)


def dupont_five_step(bundle: StatementBundle) -> DupontFiveStep:
    inc = bundle.income
    bs = bundle.balance
    tax_burden = _maybe_div(inc.net_income, inc.income_before_tax)
    interest_burden = _maybe_div(inc.income_before_tax, inc.operating_income)
    op_margin = _maybe_div(inc.operating_income, inc.revenue)
    asset_turn = _maybe_div(inc.revenue, bs.total_assets)
    em = _maybe_div(bs.total_assets, bs.total_equity)
    components = [tax_burden, interest_burden, op_margin, asset_turn, em]
    roe = None
    if all(c is not None for c in components):
        prod = 1.0
        for c in components:
            prod *= c  # type: ignore[operator]
        roe = prod
    return DupontFiveStep(
        tax_burden=tax_burden,
        interest_burden=interest_burden,
        operating_margin=op_margin,
        asset_turnover=asset_turn,
        equity_multiplier=em,
        roe=roe,
    )


# ─── Altman Z-Score ──────────────────────────────────────────────────


@dataclass(frozen=True)
class AltmanZ:
    z_score: float | None
    distress_zone: str  # "safe" | "grey" | "distress" | "unknown"


def altman_z_score(bundle: StatementBundle, *, market_cap: float | None = None) -> AltmanZ:
    """Altman Z-Score (manufacturing variant).

    Z = 1.2·X1 + 1.4·X2 + 3.3·X3 + 0.6·X4 + 1.0·X5
        X1 = working_capital / total_assets
        X2 = retained_earnings / total_assets
        X3 = ebit / total_assets
        X4 = market_value_equity / total_liabilities
        X5 = revenue / total_assets

    Zones (manufacturing): >2.99 safe; 1.81–2.99 grey; <1.81 distress.
    """
    inc = bundle.income
    bs = bundle.balance
    market_cap = market_cap or (bundle.stats.market_cap if bundle.stats else None)

    x1 = _maybe_div(bs.working_capital, bs.total_assets)
    x2 = _maybe_div(bs.retained_earnings, bs.total_assets)
    x3 = _maybe_div(inc.operating_income, bs.total_assets)
    x4 = _maybe_div(market_cap, bs.total_liabilities)
    x5 = _maybe_div(inc.revenue, bs.total_assets)
    components = [x1, x2, x3, x4, x5]
    if any(c is None for c in components):
        return AltmanZ(z_score=None, distress_zone="unknown")

    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5  # type: ignore[operator]
    if z > 2.99:
        zone = "safe"
    elif z > 1.81:
        zone = "grey"
    else:
        zone = "distress"
    return AltmanZ(z_score=z, distress_zone=zone)
