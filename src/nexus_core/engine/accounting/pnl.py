# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Realized-PnL / disposition report for the onchain-accounting engine (P4).

Runs the P3 FIFO cost-basis engine over a priced ledger and aggregates its
disposals into a realized-gain report: an overall summary and a per-tax-year
rollup, each split short- vs long-term. This is the last phase of the engine.

Scope, by decision: it reports realized gain/loss on the dispositions that
happen **under management**, for **tax awareness/education** — it is NOT tax
advice, NOT a tax return, and NOT a complete cost-basis record. It deliberately
omits wash-sale, like-kind, and other adjustments. Where a disposal's basis or
proceeds are unknown it is EXCLUDED from the sums and counted in
``incomplete_count`` — never folded in as a fabricated 0. Every response carries
the tax disclaimer.

Clean-room; no AGPL code.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from ...disclaimers import TAX_AWARENESS
from .cost_basis import DisposalRecord, compute_cost_basis
from .models import BasisOverrideInput, LedgerEvent


class PnlBucket(BaseModel):
    """Aggregated realized figures for a set of disposals (a year, or overall).

    Sums include only disposals with a known realized gain (both proceeds and
    basis known); the rest are counted in ``incomplete_count`` and excluded, so
    ``complete`` says whether the sums cover every disposal."""

    model_config = ConfigDict(extra="forbid")

    realized_gain_usd: Decimal
    short_term_gain_usd: Decimal
    long_term_gain_usd: Decimal
    proceeds_usd: Decimal
    cost_basis_usd: Decimal
    disposal_count: int
    incomplete_count: int
    complete: bool


class PnlYear(PnlBucket):
    """A single tax year's realized figures."""

    year: int


class PnlReport(BaseModel):
    """The realized-PnL report."""

    model_config = ConfigDict(extra="forbid")

    method: str
    summary: PnlBucket
    by_year: list[PnlYear]
    warnings: list[str]
    disclaimer: str


def _aggregate(
    disposals: list[DisposalRecord],
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal, int]:
    """(realized, short_term, long_term, proceeds, cost_basis, incomplete_count)."""
    realized = Decimal(0)
    short_term = Decimal(0)
    long_term = Decimal(0)
    proceeds = Decimal(0)
    cost_basis = Decimal(0)
    incomplete = 0
    for disposal in disposals:
        if (
            disposal.realized_gain_usd is None
            or disposal.proceeds_usd is None
            or disposal.cost_basis_usd is None
        ):
            incomplete += 1
            continue
        realized += disposal.realized_gain_usd
        proceeds += disposal.proceeds_usd
        cost_basis += disposal.cost_basis_usd
        if disposal.term == "short":
            short_term += disposal.realized_gain_usd
        elif disposal.term == "long":
            long_term += disposal.realized_gain_usd
    return realized, short_term, long_term, proceeds, cost_basis, incomplete


def onchain_pnl_report(
    events: Sequence[LedgerEvent],
    *,
    overrides: Sequence[BasisOverrideInput] | None = None,
    method: str = "fifo",
) -> PnlReport:
    """Realized-PnL report: FIFO cost basis, then aggregate disposals by year."""
    result = compute_cost_basis(events, overrides=overrides, method=method)
    disposals = result.disposals

    realized, short_term, long_term, proceeds, cost_basis, incomplete = _aggregate(disposals)
    summary = PnlBucket(
        realized_gain_usd=realized,
        short_term_gain_usd=short_term,
        long_term_gain_usd=long_term,
        proceeds_usd=proceeds,
        cost_basis_usd=cost_basis,
        disposal_count=len(disposals),
        incomplete_count=incomplete,
        complete=incomplete == 0,
    )

    by_year_map: dict[int, list[DisposalRecord]] = {}
    for disposal in disposals:
        year = datetime.fromtimestamp(disposal.disposed_at, tz=UTC).year
        by_year_map.setdefault(year, []).append(disposal)

    by_year: list[PnlYear] = []
    for year in sorted(by_year_map):
        year_disposals = by_year_map[year]
        realized, short_term, long_term, proceeds, cost_basis, incomplete = _aggregate(
            year_disposals
        )
        by_year.append(
            PnlYear(
                year=year,
                realized_gain_usd=realized,
                short_term_gain_usd=short_term,
                long_term_gain_usd=long_term,
                proceeds_usd=proceeds,
                cost_basis_usd=cost_basis,
                disposal_count=len(year_disposals),
                incomplete_count=incomplete,
                complete=incomplete == 0,
            )
        )

    return PnlReport(
        method=method,
        summary=summary,
        by_year=by_year,
        warnings=result.warnings,
        disclaimer=TAX_AWARENESS,
    )


__all__ = ["PnlBucket", "PnlReport", "PnlYear", "onchain_pnl_report"]
