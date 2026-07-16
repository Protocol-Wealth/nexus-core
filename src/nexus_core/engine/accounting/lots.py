# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Account-scoped FIFO lot book for the onchain-accounting engine.

A per-``(account_ref, asset_id)`` queue of acquisition lots. Disposals consume
the oldest lots in that account first (FIFO); no implicit cross-account matching
is permitted. A lot's ``unit_cost_usd`` may be ``None`` when the opening basis is
genuinely unknown (an unpriced acquisition with no override) — that stays
``None`` all the way through, so a downstream figure is honestly gapped rather
than fabricated as ``0``.

Clean-room: standard FIFO lot mechanics (IRS Pub. 550), re-derived. No AGPL code.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

_MAX_DERIVED_DECIMAL_SCALE = 256
_MAX_DERIVED_DECIMAL_INTEGER_DIGITS = 128
_MAX_ALIGNED_DECIMAL_DIGITS = 512
_MAX_MULTIPLICATION_SCALE = 512
_MAX_MULTIPLICATION_INTEGER_DIGITS = 256
_MAX_MULTIPLICATION_COEFFICIENT_DIGITS = 512
_DIVISION_PRECISION = _MAX_DERIVED_DECIMAL_SCALE + _MAX_DERIVED_DECIMAL_INTEGER_DIGITS


def _validate_decimal_bound(
    value: Decimal,
    *,
    max_scale: int,
    max_integer_digits: int,
    max_coefficient_digits: int,
) -> None:
    if not value.is_finite():
        raise ValueError("accounting decimals must be finite")
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):  # pragma: no cover - finite values use int exponents
        raise ValueError("accounting decimals must be finite")
    if exponent < -max_scale:
        raise ValueError("accounting decimal scale exceeds the supported arithmetic envelope")
    integer_digits = 0 if value.is_zero() or value.adjusted() < 0 else value.adjusted() + 1
    if integer_digits > max_integer_digits:
        raise ValueError("accounting decimal magnitude exceeds the supported arithmetic envelope")
    if len(value.as_tuple().digits) > max_coefficient_digits:
        raise ValueError("accounting decimal precision exceeds the supported arithmetic envelope")


def exact_decimal_sum(values: Sequence[Decimal]) -> Decimal:
    """Add finite Decimals with enough local precision to preserve every digit."""
    if not values:
        return Decimal(0)
    for value in values:
        _validate_decimal_bound(
            value,
            max_scale=_MAX_DERIVED_DECIMAL_SCALE,
            max_integer_digits=_MAX_DERIVED_DECIMAL_INTEGER_DIGITS,
            max_coefficient_digits=(
                _MAX_DERIVED_DECIMAL_SCALE + _MAX_DERIVED_DECIMAL_INTEGER_DIGITS
            ),
        )
    nonzero_values = [value for value in values if not value.is_zero()]
    if not nonzero_values:
        return Decimal(0)
    exponents = [value.as_tuple().exponent for value in nonzero_values]
    if any(not isinstance(exponent, int) for exponent in exponents):  # pragma: no cover
        raise ValueError("accounting decimals must be finite")
    integer_exponents = [exponent for exponent in exponents if isinstance(exponent, int)]
    minimum_exponent = min(integer_exponents)
    if minimum_exponent < -_MAX_DERIVED_DECIMAL_SCALE:
        raise ValueError("accounting decimal scale exceeds the supported arithmetic envelope")
    if any(value.adjusted() >= _MAX_DERIVED_DECIMAL_INTEGER_DIGITS for value in nonzero_values):
        raise ValueError("accounting decimal magnitude exceeds the supported arithmetic envelope")
    aligned_digits = max(
        1,
        *(value.adjusted() - minimum_exponent + 1 for value in nonzero_values),
    )
    if aligned_digits > _MAX_ALIGNED_DECIMAL_DIGITS:
        raise ValueError("accounting decimal precision exceeds the supported arithmetic envelope")
    with localcontext() as context:
        context.prec = aligned_digits + len(str(len(values))) + 2
        return sum(values, Decimal(0))


def exact_decimal_multiply(left: Decimal, right: Decimal) -> Decimal:
    """Multiply bounded Decimals without ambient-context rounding."""
    for value in (left, right):
        _validate_decimal_bound(
            value,
            max_scale=_MAX_DERIVED_DECIMAL_SCALE,
            max_integer_digits=_MAX_DERIVED_DECIMAL_INTEGER_DIGITS,
            max_coefficient_digits=(
                _MAX_DERIVED_DECIMAL_SCALE + _MAX_DERIVED_DECIMAL_INTEGER_DIGITS
            ),
        )
    if left.is_zero() or right.is_zero():
        return Decimal(0)
    precision = len(left.as_tuple().digits) + len(right.as_tuple().digits) + 1
    if precision > _MAX_MULTIPLICATION_COEFFICIENT_DIGITS:
        raise ValueError("accounting decimal precision exceeds the supported arithmetic envelope")
    with localcontext() as context:
        context.prec = precision
        product = left * right
    _validate_decimal_bound(
        product,
        max_scale=_MAX_MULTIPLICATION_SCALE,
        max_integer_digits=_MAX_MULTIPLICATION_INTEGER_DIGITS,
        max_coefficient_digits=_MAX_MULTIPLICATION_COEFFICIENT_DIGITS,
    )
    return product


def deterministic_decimal_divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Divide with method-pinned precision, scale, and half-even rounding."""
    _validate_decimal_bound(
        numerator,
        max_scale=_MAX_MULTIPLICATION_SCALE,
        max_integer_digits=_MAX_MULTIPLICATION_INTEGER_DIGITS,
        max_coefficient_digits=_MAX_MULTIPLICATION_COEFFICIENT_DIGITS,
    )
    _validate_decimal_bound(
        denominator,
        max_scale=_MAX_DERIVED_DECIMAL_SCALE,
        max_integer_digits=_MAX_DERIVED_DECIMAL_INTEGER_DIGITS,
        max_coefficient_digits=(_MAX_DERIVED_DECIMAL_SCALE + _MAX_DERIVED_DECIMAL_INTEGER_DIGITS),
    )
    if denominator.is_zero():
        raise ValueError("accounting decimal division requires a nonzero denominator")
    with localcontext() as context:
        context.prec = _DIVISION_PRECISION
        context.rounding = ROUND_HALF_EVEN
        quotient = numerator / denominator
        exponent = quotient.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -_MAX_DERIVED_DECIMAL_SCALE:
            quantum = Decimal(1).scaleb(-_MAX_DERIVED_DECIMAL_SCALE)
            quotient = quotient.quantize(quantum, rounding=ROUND_HALF_EVEN)
    _validate_decimal_bound(
        quotient,
        max_scale=_MAX_DERIVED_DECIMAL_SCALE,
        max_integer_digits=_MAX_DERIVED_DECIMAL_INTEGER_DIGITS,
        max_coefficient_digits=(_MAX_DERIVED_DECIMAL_SCALE + _MAX_DERIVED_DECIMAL_INTEGER_DIGITS),
    )
    return quotient


def bounded_decimal_share(total: Decimal, part: Decimal, whole: Decimal) -> Decimal:
    """Return a deterministic nonnegative proportional share bounded by total."""
    if total < 0 or part < 0 or whole <= 0 or part > whole:
        raise ValueError("accounting proportional share inputs are out of bounds")
    if total.is_zero() or part.is_zero():
        return Decimal(0)
    if part == whole:
        return total
    share = deterministic_decimal_divide(exact_decimal_multiply(total, part), whole)
    return min(total, max(Decimal(0), share))


def exact_decimal_subtract(total: Decimal, component: Decimal) -> Decimal:
    """Return the exact represented-Decimal complement of one component."""
    return exact_decimal_sum((total, component.copy_negate()))


@dataclass
class Lot:
    """One acquisition lot. ``quantity`` decreases as the lot is consumed;
    ``unit_cost_usd`` (original basis rate) and ``acquired_at`` are fixed at
    open; authoritative remaining basis totals decrease with consumption."""

    lot_ref: str
    account_ref: str
    asset_id: str
    quantity: Decimal
    unit_cost_usd: Decimal | None
    acquired_at: int | None
    basis_source: str
    remaining_cost_basis_usd: Decimal | None = None
    remaining_fee_basis_usd: Decimal | None = None
    acquisition_sequence: int | None = None
    acquisition_leg_index: int = 0
    basis_override_ref: str | None = None
    basis_last_verified: date | None = None
    basis_evidence_source: str | None = None
    unit_fee_basis_usd: Decimal = Decimal(0)
    acquisition_event_id: str | None = None
    acquisition_tx_ref: str | None = None
    origin_lot_ref: str | None = None
    basis_price_source: str | None = None
    basis_price_as_of: int | None = None
    symbol: str | None = None
    chain: str | None = None


@dataclass(frozen=True)
class Consumed:
    """A fragment of a lot taken by a disposal (the lot's fixed fields are read
    from ``lot``; ``quantity`` is the amount taken from it)."""

    lot: Lot
    quantity: Decimal
    cost_basis_usd: Decimal | None
    fee_basis_usd: Decimal


class LotBook:
    """FIFO lot queues keyed by opaque account and public-safe asset identity."""

    def __init__(self) -> None:
        self._books: dict[tuple[str, str], deque[Lot]] = {}
        self._lot_refs: set[str] = set()
        self._origin_roots: dict[str, Lot] = {}

    def add(self, lot: Lot) -> None:
        if lot.lot_ref in self._lot_refs:
            raise ValueError(f"duplicate lot_ref: {lot.lot_ref}")
        if lot.remaining_cost_basis_usd is None and lot.unit_cost_usd is not None:
            lot.remaining_cost_basis_usd = exact_decimal_multiply(lot.unit_cost_usd, lot.quantity)
        if lot.remaining_fee_basis_usd is None:
            lot.remaining_fee_basis_usd = exact_decimal_multiply(
                lot.unit_fee_basis_usd, lot.quantity
            )
        root_ref = lot.origin_lot_ref or lot.lot_ref
        existing_root = self._origin_roots.get(root_ref)
        if existing_root is not None:
            self._validate_same_root(existing_root, lot)
        book = self._books.setdefault((lot.account_ref, lot.asset_id), deque())
        for existing in book:
            if existing.acquired_at != lot.acquired_at:
                continue
            existing_root_ref = existing.origin_lot_ref or existing.lot_ref
            if existing_root_ref == root_ref:
                continue
            if lot.acquired_at is None:
                continue
            sequence_orders = (
                existing.acquisition_sequence is not None
                and lot.acquisition_sequence is not None
                and existing.acquisition_sequence != lot.acquisition_sequence
            )
            same_event_leg_orders = (
                existing.acquisition_event_id is not None
                and existing.acquisition_event_id == lot.acquisition_event_id
                and existing.acquisition_leg_index != lot.acquisition_leg_index
            )
            if not sequence_orders and not same_event_leg_orders:
                raise ValueError(
                    "lots sharing account/asset/acquired_at require unique "
                    "acquisition_sequence or intra-event leg order values"
                )
        key = self._sort_key(lot)
        for index, existing in enumerate(book):
            if key < self._sort_key(existing):
                book.insert(index, lot)
                break
        else:
            book.append(lot)
        self._lot_refs.add(lot.lot_ref)
        self._origin_roots.setdefault(root_ref, lot)

    @staticmethod
    def _sort_key(lot: Lot) -> tuple[bool, int, bool, int, str, int, str]:
        """Original acquisition order, including lots arriving by transfer."""
        return (
            lot.acquired_at is None,
            lot.acquired_at or 0,
            lot.acquisition_sequence is None,
            lot.acquisition_sequence or 0,
            lot.acquisition_event_id or "",
            lot.acquisition_leg_index,
            lot.lot_ref,
        )

    @staticmethod
    def _validate_same_root(existing: Lot, incoming: Lot) -> None:
        invariant_fields = (
            "asset_id",
            "acquired_at",
            "acquisition_sequence",
            "acquisition_leg_index",
            "unit_cost_usd",
            "basis_source",
            "basis_override_ref",
            "basis_last_verified",
            "basis_evidence_source",
            "unit_fee_basis_usd",
            "acquisition_event_id",
            "acquisition_tx_ref",
            "basis_price_source",
            "basis_price_as_of",
        )
        if any(getattr(existing, field) != getattr(incoming, field) for field in invariant_fields):
            raise ValueError("fragments sharing origin_lot_ref have conflicting lot invariants")

    def consume(
        self, account_ref: str, asset_id: str, quantity: Decimal
    ) -> tuple[list[Consumed], Decimal]:
        """Consume ``quantity`` of ``asset_id`` FIFO within ``account_ref``.

        Returns the matched lot fragments and any ``shortfall`` (the quantity
        disposed beyond the available lots — an unmatched disposal whose basis
        is unknown, surfaced by the caller as a warning, never a fabricated 0).
        """
        matched: list[Consumed] = []
        remaining = quantity
        book = self._books.get((account_ref, asset_id))
        while remaining > 0 and book:
            lot = book[0]
            take = min(remaining, lot.quantity)
            quantity_before = lot.quantity
            consume_all = take == quantity_before
            cost_basis = lot.remaining_cost_basis_usd
            if cost_basis is not None and not consume_all:
                cost_basis = bounded_decimal_share(cost_basis, take, quantity_before)
            fee_basis = lot.remaining_fee_basis_usd or Decimal(0)
            if not consume_all:
                fee_basis = bounded_decimal_share(fee_basis, take, quantity_before)
            matched.append(
                Consumed(
                    lot=lot,
                    quantity=take,
                    cost_basis_usd=cost_basis,
                    fee_basis_usd=fee_basis,
                )
            )
            lot.quantity = exact_decimal_subtract(lot.quantity, take)
            if lot.remaining_cost_basis_usd is not None and cost_basis is not None:
                lot.remaining_cost_basis_usd = exact_decimal_subtract(
                    lot.remaining_cost_basis_usd,
                    cost_basis,
                )
            if lot.remaining_fee_basis_usd is not None:
                lot.remaining_fee_basis_usd = exact_decimal_subtract(
                    lot.remaining_fee_basis_usd,
                    fee_basis,
                )
            remaining = exact_decimal_subtract(remaining, take)
            if lot.quantity <= 0:
                book.popleft()
        return matched, remaining

    def open_lots(self) -> list[Lot]:
        """Remaining lots with a positive quantity, oldest first per asset."""
        return [lot for book in self._books.values() for lot in book if lot.quantity > 0]


__all__ = [
    "Consumed",
    "Lot",
    "LotBook",
    "bounded_decimal_share",
    "deterministic_decimal_divide",
    "exact_decimal_multiply",
    "exact_decimal_subtract",
    "exact_decimal_sum",
]
