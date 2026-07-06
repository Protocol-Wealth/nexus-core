# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Multi-name collar BOOK assembly — an advisor research worksheet.

Given a set of pre-screened collar candidates (one per underlying: spot, tenor,
per-share net credit, optional window dividend income and an optional external
``score``), :func:`assemble_collar_book` sizes a whole-contract portfolio
against a notional target with per-position and per-sector caps, then reports
the resulting book's arithmetic: deployed notional, cash residual, dollar and
percentage income, and capital-weighted floor/cap geometry when strike data is
supplied.

Assembly is a two-pass greedy allocator (ported from an operator-reviewed
reference implementation):

* **Pass 1** walks the ranking (external ``score`` descending when every
  candidate carries one, otherwise annualized income yield descending) and
  gives each name one budget slot of ``notional_target / n_positions_target``,
  floored to whole contracts (100-share round lots — fully-paid accounts, no
  margin) and clipped by the per-position and per-sector caps.
* **Pass 2** tops up already-held names with the residual cash, in the same
  ranking order, still respecting both caps.

Price-tier feasibility is the binding constraint at small notionals: a $950
stock is one $95,000 contract — infeasible in a $250K/15-name book. The engine
reports every price-tier exclusion (``excluded_price_tier``) and sector-cap
exclusion (``excluded_sector_cap``) explicitly instead of silently dropping
names. Degenerate inputs (``spot <= 0`` or ``dte <= 0``) are excluded with a
structured reason (``excluded_degenerate``), never an exception, and the
module is clock-free (callers supply ``dte``).

The engine **describes** a book; it does not prescribe one. It reports the
portfolio yield but applies no yield-band policing, places no orders, and
produces no execution instructions. Everything here is an advisor research
WORKSHEET over caller-supplied parameters — not individualized advice, a
recommendation to trade, or a suitability assessment.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from nexus_core.engine.pricing.overlays import DISCLAIMER

#: Shares per US equity option contract (100-share round lots).
_SHARES_PER_CONTRACT = 100.0

#: Pass 1 stops early once the target name count is reached AND this fraction
#: of the notional target is deployed; pass 2 then handles the residual.
_PASS1_FILL_FRACTION = 0.95


@dataclass(frozen=True)
class CollarBookPosition:
    """One pre-screened collar candidate submitted for book assembly.

    Dollar fields are **per share**; the engine converts to per-contract
    figures internally (× 100). ``score`` is an external ranking key (e.g.
    from a screening step) — when every candidate carries one the book ranks
    by it, otherwise ranking falls back to annualized income yield.

    ``expiration`` / ``put_strike`` / ``call_strike`` / ``floor_pct`` /
    ``cap_pct`` are display passthrough for the worksheet; ``floor_pct`` /
    ``cap_pct`` are derived from the strikes when omitted but derivable.
    """

    symbol: str
    spot: float
    dte: int
    net_credit: float  # per share; negative = net-debit collar
    dividend_income_window: float = 0.0  # per share, over the option window
    score: float | None = None
    sector: str | None = None
    expiration: str | None = None
    put_strike: float | None = None
    call_strike: float | None = None
    floor_pct: float | None = None
    cap_pct: float | None = None


@dataclass
class CollarBookHolding:
    """One sized position in the assembled book.

    ``weight_pct`` is the position notional as a percentage of the book's
    ``notional_target`` — directly comparable to ``max_position_weight_pct``.
    ``floor_pct`` / ``cap_pct`` echo the candidate's values, derived from the
    strikes when omitted but derivable, ``None`` otherwise.
    """

    symbol: str
    sector: str | None
    contracts: int
    capital_per_contract: float  # spot × 100
    notional: float  # contracts × capital_per_contract
    weight_pct: float  # % of notional_target
    annual_income: float  # $ per year, 365-day-convention annualization
    period_income: float  # $ over the option window
    expiration: str | None
    put_strike: float | None
    call_strike: float | None
    floor_pct: float | None
    cap_pct: float | None


@dataclass(frozen=True)
class PriceTierExclusion:
    """A name whose single-contract capital did not fit its budget or cap."""

    symbol: str
    capital_per_contract: float


@dataclass(frozen=True)
class DegenerateExclusion:
    """A candidate excluded for a degenerate input, with the reason."""

    symbol: str
    reason: str


@dataclass
class CollarBookResult:
    """The assembled book: sized positions, totals, and explicit exclusions.

    ``capital_weighted_floor_pct`` / ``capital_weighted_cap_pct`` are ``None``
    when any held position lacks floor/cap data (given or strike-derived) —
    a partial average would misstate the book's protection geometry.
    """

    positions: list[CollarBookHolding]
    notional_target: float
    notional_deployed: float
    cash_residual: float
    deploy_pct: float  # notional_deployed / notional_target × 100
    annual_income: float  # total $, 365-day-convention annualization
    portfolio_yield_pct: float  # annual_income / notional_deployed × 100
    capital_weighted_floor_pct: float | None
    capital_weighted_cap_pct: float | None
    counts: dict[str, int]
    excluded_price_tier: list[PriceTierExclusion]
    excluded_sector_cap: list[str]
    excluded_degenerate: list[DegenerateExclusion]
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = DISCLAIMER


@dataclass
class _Slot:
    """Internal mutable sizing state for one usable candidate."""

    position: CollarBookPosition
    capital: float  # per contract
    period_income: float  # per contract, over the window
    annual_income: float  # per contract, annualized
    rank_value: float
    contracts: int = 0

    @property
    def notional(self) -> float:
        return self.contracts * self.capital


def _effective_floor_pct(position: CollarBookPosition) -> float | None:
    """The candidate's floor%, derived from the put strike when omitted."""
    if position.floor_pct is not None:
        return position.floor_pct
    if position.put_strike is not None and position.spot > 0.0:
        return (position.spot - position.put_strike) / position.spot * 100.0
    return None


def _effective_cap_pct(position: CollarBookPosition) -> float | None:
    """The candidate's cap%, derived from the call strike when omitted."""
    if position.cap_pct is not None:
        return position.cap_pct
    if position.call_strike is not None and position.spot > 0.0:
        return (position.call_strike - position.spot) / position.spot * 100.0
    return None


def _capital_weighted(
    holdings: Sequence[tuple[float | None, float]], deployed: float
) -> float | None:
    """Capital-weighted average of ``(value, notional)`` pairs.

    ``None`` when there is nothing deployed or any held position lacks the
    value — a partial average would misstate the book.
    """
    if deployed <= 0.0 or not holdings:
        return None
    total = 0.0
    for value, notional in holdings:
        if value is None:
            return None
        total += value * notional
    return round(total / deployed, 2)


def assemble_collar_book(
    positions: Sequence[CollarBookPosition],
    *,
    notional_target: float = 1_000_000.0,
    n_positions_min: int = 12,
    n_positions_max: int = 25,
    n_positions_target: int = 15,
    max_position_weight_pct: float = 12.0,
    max_sector_weight_pct: float = 25.0,
    min_cash_deploy_pct: float = 90.0,
    days_per_year: int = 365,
) -> CollarBookResult:
    """Assemble a whole-contract collar book from pre-screened candidates.

    Per position: ``capital_per_contract = spot × 100``;
    ``period_income = (net_credit + dividend_income_window) × 100``;
    ``annual_income = period_income × days_per_year / dte``. Candidates with
    ``dte <= 0`` or ``spot <= 0`` are excluded with a structured reason —
    never an exception.

    Ranking: external ``score`` descending when EVERY usable candidate
    carries one; otherwise annualized income yield descending (the two scales
    never interleave — a partially-scored universe falls back with a warning).
    Ties break by symbol for determinism.

    Args:
        positions: Pre-screened candidates, at most one per underlying.
        notional_target: Book size the allocator sizes against, in dollars.
        n_positions_min: Below this held-name count the result carries a
            breadth warning (reported, not enforced).
        n_positions_max: Hard cap on held names.
        n_positions_target: Names the pass-1 budget is sliced for (clamped
            into ``[n_positions_min, n_positions_max]``).
        max_position_weight_pct: Per-position cap, % of ``notional_target``.
        max_sector_weight_pct: Per-sector cap, % of ``notional_target``.
            Applies only to positions that declare a ``sector`` — unsectored
            positions are not pooled into a phantom bucket (the per-position
            cap still applies to them).
        min_cash_deploy_pct: Below this deployment % the result carries a
            cash-drag warning (reported, not enforced).
        days_per_year: Annualization convention for income figures.

    Returns:
        A :class:`CollarBookResult`. The portfolio yield is REPORTED without
        any yield-band policing — this engine describes, it does not
        prescribe. No orders, no execution instructions.
    """
    warnings: list[str] = []
    excluded_degenerate: list[DegenerateExclusion] = []
    excluded_price: list[PriceTierExclusion] = []
    excluded_sector: list[str] = []

    if notional_target <= 0.0 or days_per_year <= 0:
        return CollarBookResult(
            positions=[],
            notional_target=notional_target,
            notional_deployed=0.0,
            cash_residual=notional_target,
            deploy_pct=0.0,
            annual_income=0.0,
            portfolio_yield_pct=0.0,
            capital_weighted_floor_pct=None,
            capital_weighted_cap_pct=None,
            counts={
                "input": len(positions),
                "held": 0,
                "excluded_price_tier": 0,
                "excluded_sector_cap": 0,
                "excluded_degenerate": 0,
            },
            excluded_price_tier=[],
            excluded_sector_cap=[],
            excluded_degenerate=[],
            warnings=["notional_target and days_per_year must be > 0 — nothing assembled"],
        )

    slots: list[_Slot] = []
    for position in positions:
        if position.spot <= 0.0:
            excluded_degenerate.append(
                DegenerateExclusion(position.symbol, f"spot must be > 0 (got {position.spot})")
            )
            continue
        if position.dte <= 0:
            excluded_degenerate.append(
                DegenerateExclusion(position.symbol, f"dte must be >= 1 (got {position.dte})")
            )
            continue
        capital = position.spot * _SHARES_PER_CONTRACT
        period = (position.net_credit + position.dividend_income_window) * _SHARES_PER_CONTRACT
        annual = period * days_per_year / position.dte
        slots.append(
            _Slot(
                position=position,
                capital=capital,
                period_income=period,
                annual_income=annual,
                rank_value=annual / capital,  # income-yield default; may be replaced below
            )
        )

    scored = [s for s in slots if s.position.score is not None]
    if slots and len(scored) == len(slots):
        for slot in slots:
            # Every candidate carries a score — mypy can't see that, hence the check.
            if slot.position.score is not None:
                slot.rank_value = slot.position.score
    elif scored:
        warnings.append(
            f"'score' supplied on only {len(scored)} of {len(slots)} usable positions — "
            "ranked by annualized income yield instead"
        )
    slots.sort(key=lambda s: (-s.rank_value, s.position.symbol))

    n_target = max(1, n_positions_min, min(n_positions_target, n_positions_max))
    budget = notional_target / n_target
    max_pos_notional = notional_target * max_position_weight_pct / 100.0
    max_sector_notional = notional_target * max_sector_weight_pct / 100.0

    held: list[_Slot] = []
    sector_notional: dict[str, float] = {}
    deployed = 0.0

    # Pass 1: one budget slot per name down the ranking until n_target filled.
    for slot in slots:
        if len(held) >= n_positions_max:
            break
        contracts = int(budget // slot.capital)
        if contracts < 1:
            excluded_price.append(PriceTierExclusion(slot.position.symbol, slot.capital))
            continue
        notional = min(contracts * slot.capital, max_pos_notional)
        contracts = int(notional // slot.capital)
        if contracts < 1:
            excluded_price.append(PriceTierExclusion(slot.position.symbol, slot.capital))
            continue
        sector = slot.position.sector
        if sector is not None:
            used = sector_notional.get(sector, 0.0)
            if used + contracts * slot.capital > max_sector_notional:
                fit = int((max_sector_notional - used) // slot.capital)
                if fit < 1:
                    excluded_sector.append(slot.position.symbol)
                    continue
                contracts = fit
        slot.contracts = contracts
        held.append(slot)
        if sector is not None:
            sector_notional[sector] = sector_notional.get(sector, 0.0) + slot.notional
        deployed += slot.notional
        if len(held) >= n_target and deployed >= notional_target * _PASS1_FILL_FRACTION:
            break

    # Pass 2: top up held positions with residual cash (respect both caps).
    residual = notional_target - deployed
    for slot in held:  # already in ranking order
        if residual < slot.capital:
            continue
        sector = slot.position.sector
        room_pos = max_pos_notional - slot.notional
        room_sec = (
            math.inf
            if sector is None
            else max_sector_notional - sector_notional.get(sector, 0.0)
        )
        add = int(min(residual, room_pos, room_sec) // slot.capital)
        if add >= 1:
            slot.contracts += add
            added = add * slot.capital
            if sector is not None:
                sector_notional[sector] = sector_notional.get(sector, 0.0) + added
            deployed += added
            residual -= added

    holdings = [
        CollarBookHolding(
            symbol=slot.position.symbol,
            sector=slot.position.sector,
            contracts=slot.contracts,
            capital_per_contract=round(slot.capital, 2),
            notional=round(slot.notional, 2),
            weight_pct=round(slot.notional / notional_target * 100.0, 2),
            annual_income=round(slot.annual_income * slot.contracts, 2),
            period_income=round(slot.period_income * slot.contracts, 2),
            expiration=slot.position.expiration,
            put_strike=slot.position.put_strike,
            call_strike=slot.position.call_strike,
            floor_pct=_effective_floor_pct(slot.position),
            cap_pct=_effective_cap_pct(slot.position),
        )
        for slot in held
    ]

    annual_income = sum(slot.annual_income * slot.contracts for slot in held)
    deploy_pct = deployed / notional_target * 100.0

    if len(held) < n_positions_min:
        warnings.append(
            f"only {len(held)} positions vs minimum {n_positions_min} — "
            "widen the universe or raise notional"
        )
    if deploy_pct < min_cash_deploy_pct:
        warnings.append(
            f"deployed {deploy_pct:.0f}% of target < {min_cash_deploy_pct:.0f}% — "
            "cash drag; add lower-priced candidates"
        )
    # Deliberately NO yield-band policing: the portfolio yield is reported
    # as-is. This engine describes a book; it does not prescribe one.

    return CollarBookResult(
        positions=holdings,
        notional_target=notional_target,
        notional_deployed=round(deployed, 2),
        cash_residual=round(notional_target - deployed, 2),
        deploy_pct=round(deploy_pct, 2),
        annual_income=round(annual_income, 2),
        portfolio_yield_pct=round(annual_income / deployed * 100.0, 2) if deployed else 0.0,
        capital_weighted_floor_pct=_capital_weighted(
            [(h.floor_pct, h.notional) for h in holdings], deployed
        ),
        capital_weighted_cap_pct=_capital_weighted(
            [(h.cap_pct, h.notional) for h in holdings], deployed
        ),
        counts={
            "input": len(positions),
            "held": len(held),
            "excluded_price_tier": len(excluded_price),
            "excluded_sector_cap": len(excluded_sector),
            "excluded_degenerate": len(excluded_degenerate),
        },
        excluded_price_tier=excluded_price,
        excluded_sector_cap=excluded_sector,
        excluded_degenerate=excluded_degenerate,
        warnings=warnings,
    )


__all__ = [
    "CollarBookHolding",
    "CollarBookPosition",
    "CollarBookResult",
    "DegenerateExclusion",
    "PriceTierExclusion",
    "assemble_collar_book",
]
