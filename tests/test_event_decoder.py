# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the P2 onchain event decoder (pure classification)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import pytest

from nexus_core.engine.accounting import (
    AssetRef,
    EventKind,
    MovementInput,
    RawTransactionInput,
    TransferTreatment,
    classify_kind,
    decode_transaction,
    decode_transactions,
    resolve_category,
)


def _mv(asset_id: str, direction: Literal["in", "out"], amount: str) -> MovementInput:
    return MovementInput(
        asset=AssetRef(asset_id=asset_id), direction=direction, amount=Decimal(amount)
    )


def _tx(
    movements: list[MovementInput],
    *,
    chain: str = "ethereum",
    ts: int = 1,
    protocol_hint: str | None = None,
    method: str | None = None,
    tx_ref: str | None = None,
    account_ref: str = "acct-1",
    sequence: int | None = None,
) -> RawTransactionInput:
    return RawTransactionInput(
        account_ref=account_ref,
        chain=chain,
        timestamp=ts,
        movements=movements,
        protocol_hint=protocol_hint,
        method=method,
        tx_ref=tx_ref,
        sequence=sequence,
    )


# --- resolve_category --------------------------------------------------------


def test_resolve_category_exact_decorated_and_unknown() -> None:
    assert resolve_category("uniswap_v3") == "dex"
    assert resolve_category("Uniswap V3") == "dex"
    assert resolve_category("uniswap_v3_router") == "dex"  # substring
    assert resolve_category("marinade") == "staking"
    assert resolve_category("aave_v3") == "lending"
    assert resolve_category("JLP") == "lp"
    assert resolve_category("some-unknown-thing") is None
    assert resolve_category(None) is None


# --- classify_kind -----------------------------------------------------------


def test_classify_dex_swap() -> None:
    assert classify_kind("dex", 1, 1, None) == EventKind.swap


def test_classify_staking_by_method_then_direction() -> None:
    assert classify_kind("staking", 1, 1, "stake") == EventKind.stake
    assert classify_kind("staking", 1, 0, "unstake") == EventKind.unstake
    assert classify_kind("staking", 0, 1, None) == EventKind.stake  # SOL out -> stake
    assert classify_kind("staking", 1, 0, None) == EventKind.unstake  # LST in -> unstake


def test_classify_lending_and_lp() -> None:
    assert classify_kind("lending", 0, 1, "supply") == EventKind.deposit
    assert classify_kind("lending", 1, 0, "withdraw") == EventKind.withdraw
    assert classify_kind("lp", 0, 2, "add") == EventKind.lp_add
    assert classify_kind("lp", 2, 0, "remove") == EventKind.lp_remove


def test_classify_claim_method_wins() -> None:
    assert classify_kind("lp", 1, 0, "claimFees") == EventKind.claim


def test_classify_no_category_movement_pattern() -> None:
    assert classify_kind(None, 1, 0, None) == EventKind.transfer_in
    assert classify_kind(None, 0, 1, None) == EventKind.transfer_out
    # ambiguous multi-asset with no known protocol -> typed `other`, not a guess
    assert classify_kind(None, 1, 1, None) == EventKind.other
    assert classify_kind(None, 0, 0, None) == EventKind.other


# --- decode_transaction (per-chain samples) ----------------------------------


def test_decode_evm_uniswap_swap() -> None:
    ev = decode_transaction(
        _tx(
            [_mv("eth:usdc", "out", "1000"), _mv("eth:weth", "in", "0.3")],
            protocol_hint="uniswap_v3",
        )
    )
    assert ev.kind == EventKind.swap
    assert len(ev.legs) == 2
    assert ev.event_id == "ethereum:acct-1:1"  # synthetic id when no tx_ref
    assert {leg.asset.chain for leg in ev.legs} == {"ethereum"}


def test_decode_solana_marinade_stake() -> None:
    ev = decode_transaction(
        _tx(
            [_mv("solana:So111", "out", "10"), _mv("solana:mSOL", "in", "9.5")],
            chain="solana",
            protocol_hint="marinade",
            method="deposit",
        )
    )
    assert ev.kind == EventKind.stake


def test_decode_solana_jlp_deposit_is_lp_add() -> None:
    ev = decode_transaction(
        _tx(
            [_mv("solana:usdc", "out", "500"), _mv("solana:jlp", "in", "120")],
            chain="solana",
            protocol_hint="jlp",
            method="deposit",
        )
    )
    assert ev.kind == EventKind.lp_add


def test_decode_bitcoin_transfer_in() -> None:
    ev = decode_transaction(_tx([_mv("bitcoin:btc", "in", "0.5")], chain="bitcoin"))
    assert ev.kind == EventKind.transfer_in
    assert ev.transfer_ref == ev.event_id
    assert ev.transfer_treatment == TransferTreatment.unknown


def test_fee_movement_does_not_change_principal_classification() -> None:
    tx = _tx(
        [
            _mv("eth:usdc", "in", "100"),
            MovementInput(
                asset=AssetRef(asset_id="eth:eth"),
                direction="out",
                amount=Decimal("0.001"),
                role="fee",
            ),
        ]
    )
    event = decode_transaction(tx)
    assert event.kind == EventKind.transfer_in
    assert event.legs[1].role == "fee"


def test_fee_only_transaction_decodes_as_fee_event() -> None:
    event = decode_transaction(
        _tx(
            [
                MovementInput(
                    asset=AssetRef(asset_id="eth:eth"),
                    direction="out",
                    amount=Decimal("0.001"),
                    role="fee",
                )
            ],
            tx_ref="fee-transaction",
        )
    )

    assert event.kind == EventKind.fee
    assert event.transfer_ref is None
    assert event.transfer_treatment is None
    assert event.legs[0].role == "fee"


def test_decode_unknown_protocol_multi_asset_is_other_not_dropped() -> None:
    ev = decode_transaction(
        _tx([_mv("eth:a", "out", "1"), _mv("eth:b", "in", "1")], protocol_hint="mystery-protocol")
    )
    assert ev.kind == EventKind.other  # typed, not guessed
    assert len(ev.legs) == 2  # legs preserved for review


def test_decode_uses_tx_ref_as_event_id() -> None:
    ev = decode_transaction(_tx([_mv("eth:a", "in", "1")], tx_ref="0xdeadbeef"))
    assert ev.event_id == "0xdeadbeef"
    assert ev.tx_ref == "0xdeadbeef"


def test_decode_transactions_batch_preserves_order() -> None:
    ledger = decode_transactions(
        [
            _tx([_mv("eth:a", "in", "1")], tx_ref="t1"),
            _tx([_mv("eth:a", "out", "1")], tx_ref="t2"),
        ]
    )
    assert len(ledger.events) == 2
    assert [e.kind for e in ledger.events] == [EventKind.transfer_in, EventKind.transfer_out]


def test_fallback_event_ids_include_sequence_and_reject_remaining_collisions() -> None:
    sequenced = decode_transactions(
        [
            _tx([_mv("eth:a", "in", "1")], sequence=0),
            _tx([_mv("eth:a", "out", "1")], sequence=1),
        ]
    )
    assert [event.event_id for event in sequenced.events] == [
        "ethereum:acct-1:1:0",
        "ethereum:acct-1:1:1",
    ]

    duplicate = _tx([_mv("eth:a", "in", "1")])
    with pytest.raises(ValueError, match="duplicate event_id"):
        decode_transactions([duplicate, duplicate])


def test_raw_transaction_normalizes_chain_and_rejects_movement_mismatch() -> None:
    normalized = _tx([_mv("eth:a", "in", "1")], chain=" Ethereum ")
    assert normalized.chain == "ethereum"
    assert decode_transaction(normalized).legs[0].asset.chain == "ethereum"

    with pytest.raises(ValueError, match="movement asset chain must match"):
        _tx(
            [
                MovementInput(
                    asset=AssetRef(asset_id="asset", chain="solana"),
                    direction="in",
                    amount=Decimal("1"),
                )
            ],
            chain="ethereum",
        )

    with pytest.raises(ValueError, match="chain must not be blank"):
        _tx([_mv("eth:a", "in", "1")], chain="   ")
