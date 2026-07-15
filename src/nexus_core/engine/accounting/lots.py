# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""FIFO tax-lot book for the cost-basis engine (P3).

A per-asset queue of acquisition lots. Disposals consume the oldest lots first
(FIFO). A lot's ``unit_cost_usd`` may be ``None`` when the opening basis is
genuinely unknown (an unpriced acquisition with no override) — that stays
``None`` all the way through, so a downstream figure is honestly gapped rather
than fabricated as ``0``.

Clean-room: standard FIFO lot mechanics (IRS Pub. 550), re-derived. No AGPL code.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Lot:
    """One acquisition lot. ``quantity`` decreases as the lot is consumed;
    ``unit_cost_usd`` (basis per unit) and ``acquired_at`` are fixed at open."""

    asset_id: str
    quantity: Decimal
    unit_cost_usd: Decimal | None
    acquired_at: int
    basis_source: str
    symbol: str | None = None
    chain: str | None = None


@dataclass(frozen=True)
class Consumed:
    """A fragment of a lot taken by a disposal (the lot's fixed fields are read
    from ``lot``; ``quantity`` is the amount taken from it)."""

    lot: Lot
    quantity: Decimal


class LotBook:
    """FIFO lot queues keyed by ``asset_id``."""

    def __init__(self) -> None:
        self._books: dict[str, deque[Lot]] = {}

    def add(self, lot: Lot) -> None:
        self._books.setdefault(lot.asset_id, deque()).append(lot)

    def consume(self, asset_id: str, quantity: Decimal) -> tuple[list[Consumed], Decimal]:
        """Consume ``quantity`` of ``asset_id`` FIFO.

        Returns the matched lot fragments and any ``shortfall`` (the quantity
        disposed beyond the available lots — an unmatched disposal whose basis
        is unknown, surfaced by the caller as a warning, never a fabricated 0).
        """
        matched: list[Consumed] = []
        remaining = quantity
        book = self._books.get(asset_id)
        while remaining > 0 and book:
            lot = book[0]
            take = min(remaining, lot.quantity)
            matched.append(Consumed(lot=lot, quantity=take))
            lot.quantity -= take
            remaining -= take
            if lot.quantity <= 0:
                book.popleft()
        return matched, remaining

    def open_lots(self) -> list[Lot]:
        """Remaining lots with a positive quantity, oldest first per asset."""
        return [lot for book in self._books.values() for lot in book if lot.quantity > 0]


__all__ = ["Consumed", "Lot", "LotBook"]
