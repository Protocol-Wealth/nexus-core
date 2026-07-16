# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Per-protocol onchain event decoder for the accounting engine (P2).

Turns raw transactions (the asset movements the caller already resolved, plus
optional protocol/method hints) into a normalized :class:`EventLedger` — the
readable transaction history and the acquisition/disposal stream the P3
cost-basis engine consumes.

Classification is a clean-room re-derivation of standard DeFi mechanics, not a
port of any decoder source: a transaction's **protocol category** (dex / lending
/ lp / staking, resolved from the caller's hint) plus its **movement pattern**
(what went in vs out) plus an optional **method** hint decide the event kind. A
transaction that matches no known pattern is emitted as an explicit ``other``
event with its movements preserved — never dropped silently.

v1 chains: EVM DEX/LP (Ethereum, Base, Arbitrum, Optimism), Solana (SOL, staked
SOL, JLP), Bitcoin. Solana LSTs and JLP are SPL tokens here; native-stake
exchange-rate / APY enrichment (Marinade, Sanctum) is a follow-on.
"""

from __future__ import annotations

from .models import (
    EventKind,
    EventLedger,
    LedgerEvent,
    LedgerLeg,
    RawTransactionInput,
    TransferTreatment,
)

# Protocol categories. Keys are normalized (lower-case, alphanumerics only);
# see :func:`_normalize`. Curated from public protocol identity, extensible.
_DEX = "dex"
_LENDING = "lending"
_LP = "lp"
_STAKING = "staking"

PROTOCOL_CATEGORIES: dict[str, str] = {
    # EVM DEX / aggregators
    "uniswap": _DEX,
    "uniswapv2": _DEX,
    "uniswapv3": _DEX,
    "uniswapv4": _DEX,
    "sushiswap": _DEX,
    "curve": _DEX,
    "balancer": _DEX,
    "aerodrome": _DEX,
    "velodrome": _DEX,
    "1inch": _DEX,
    "0x": _DEX,
    "cowswap": _DEX,
    "pancakeswap": _DEX,
    # EVM lending / vaults
    "aave": _LENDING,
    "aavev2": _LENDING,
    "aavev3": _LENDING,
    "compound": _LENDING,
    "morpho": _LENDING,
    "spark": _LENDING,
    "yearn": _LP,
    # Solana DEX / aggregators
    "jupiter": _DEX,
    "raydium": _DEX,
    "orca": _DEX,
    "meteora": _DEX,
    # Solana staking / LST
    "marinade": _STAKING,
    "sanctum": _STAKING,
    "jito": _STAKING,
    "blazestake": _STAKING,
    "solanastake": _STAKING,
    # Solana LP token (Jupiter Liquidity Pool)
    "jlp": _LP,
    "jupiterperps": _LP,
}

_WITHDRAW_METHODS = ("withdraw", "redeem", "remove", "unstake", "exit", "undelegate", "deactivate")
_DEPOSIT_METHODS = ("deposit", "supply", "add", "mint", "stake", "join", "delegate")
_CLAIM_METHODS = ("claim", "harvest", "collectreward", "getreward", "collectfees")


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def resolve_category(protocol_hint: str | None) -> str | None:
    """Map a caller protocol hint to a category, or ``None`` if unknown.

    Tries an exact normalized match, then a substring match so a decorated hint
    (``uniswap_v3_router``) still resolves to ``uniswapv3``.
    """
    key = _normalize(protocol_hint)
    if not key:
        return None
    exact = PROTOCOL_CATEGORIES.get(key)
    if exact is not None:
        return exact
    for known, category in PROTOCOL_CATEGORIES.items():
        if known in key:
            return category
    return None


def classify_kind(
    category: str | None, in_count: int, out_count: int, method: str | None
) -> EventKind:
    """Decide the event kind from category + movement pattern + method hint."""
    method_norm = _normalize(method)
    has_in = in_count > 0
    has_out = out_count > 0

    if any(token in method_norm for token in _CLAIM_METHODS):
        return EventKind.claim

    if category == _DEX:
        if has_in and has_out:
            return EventKind.swap
    elif category == _LP:
        if any(token in method_norm for token in _WITHDRAW_METHODS):
            return EventKind.lp_remove
        if any(token in method_norm for token in _DEPOSIT_METHODS):
            return EventKind.lp_add
        return EventKind.lp_remove if (has_in and not has_out) else EventKind.lp_add
    elif category == _LENDING:
        if any(token in method_norm for token in _WITHDRAW_METHODS):
            return EventKind.withdraw
        if any(token in method_norm for token in _DEPOSIT_METHODS):
            return EventKind.deposit
        return EventKind.withdraw if (has_in and not has_out) else EventKind.deposit
    elif category == _STAKING:
        if any(token in method_norm for token in _WITHDRAW_METHODS):
            return EventKind.unstake
        if any(token in method_norm for token in _DEPOSIT_METHODS):
            return EventKind.stake
        return EventKind.unstake if (has_in and not has_out) else EventKind.stake

    # No known category matched a specific kind. A clean one-directional move is a
    # confident transfer; a multi-asset move with no known protocol is genuinely
    # ambiguous (swap? LP? deposit-with-receipt?), so surface it as a typed
    # `other` for review rather than guessing — never dropped, legs preserved.
    if has_in and has_out:
        return EventKind.other
    if has_in:
        return EventKind.transfer_in
    if has_out:
        return EventKind.transfer_out
    return EventKind.other


def decode_transaction(tx: RawTransactionInput) -> LedgerEvent:
    """Decode one raw transaction into a normalized :class:`LedgerEvent`."""
    principal = [movement for movement in tx.movements if movement.role == "principal"]
    in_count = sum(1 for movement in principal if movement.direction == "in")
    out_count = sum(1 for movement in principal if movement.direction == "out")
    kind = classify_kind(resolve_category(tx.protocol_hint), in_count, out_count, tx.method)

    legs = [
        LedgerLeg(
            asset=m.asset,
            direction=m.direction,
            amount=m.amount,
            unit_price_usd=m.unit_price_usd,
            usd_value=m.usd_value,
            role=m.role,
            price_source=m.price_source,
            price_as_of=m.price_as_of,
        )
        for m in tx.movements
    ]

    # Deterministic id: the caller's tx_ref when present, else a stable synthetic
    # from opaque fields (no Date/random, so decoding is reproducible).
    event_id = tx.tx_ref or f"{tx.chain}:{tx.account_ref}:{tx.timestamp}"
    is_transfer = kind in (EventKind.transfer_in, EventKind.transfer_out)

    return LedgerEvent(
        event_id=event_id,
        account_ref=tx.account_ref,
        kind=kind,
        timestamp=tx.timestamp,
        sequence=tx.sequence,
        tx_ref=tx.tx_ref,
        legs=legs,
        fee_usd=tx.fee_usd,
        fee_allocation=tx.fee_allocation,
        fee_payment=tx.fee_payment,
        transfer_ref=(tx.transfer_ref or event_id) if is_transfer else None,
        transfer_treatment=(tx.transfer_treatment or TransferTreatment.unknown)
        if is_transfer
        else None,
        tax_treatment=tx.tax_treatment,
    )


def decode_transactions(transactions: list[RawTransactionInput]) -> EventLedger:
    """Decode a batch of raw transactions into a normalized event ledger."""
    return EventLedger(events=[decode_transaction(tx) for tx in transactions])


__all__ = [
    "PROTOCOL_CATEGORIES",
    "classify_kind",
    "decode_transaction",
    "decode_transactions",
    "resolve_category",
]
