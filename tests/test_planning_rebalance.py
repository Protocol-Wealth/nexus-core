# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the rebalance-to-target engine."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import rebalance


def _by_id(out: dict, asset_id: str) -> dict:
    return next(row for row in out["perAsset"] if row["id"] == asset_id)


def test_drift_and_self_financing_trades() -> None:
    out = rebalance(
        holdings={"a": 70_000, "b": 30_000},
        target_weights={"a": 0.6, "b": 0.4},
    )
    assert out["totalValue"] == 100_000.0
    assert out["turnover"] == 10_000.0  # buys == sells
    a, b = _by_id(out, "a"), _by_id(out, "b")
    assert (a["currentWeight"], a["targetWeight"], a["drift"], a["tradeAmount"]) == (
        0.7,
        0.6,
        0.1,
        -10_000.0,
    )
    assert (b["currentWeight"], b["targetWeight"], b["drift"], b["tradeAmount"]) == (
        0.3,
        0.4,
        -0.1,
        10_000.0,
    )


def test_target_introduces_a_new_asset() -> None:
    out = rebalance(holdings={"a": 100_000}, target_weights={"a": 0.5, "b": 0.5})
    assert out["turnover"] == 50_000.0
    assert _by_id(out, "a")["tradeAmount"] == -50_000.0
    b = _by_id(out, "b")
    assert b["currentWeight"] == 0.0
    assert b["tradeAmount"] == 50_000.0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"holdings": {"a": 100}, "target_weights": {"a": 0.6, "b": 0.3}}, "sum to 1"),
        ({"holdings": {"a": 0}, "target_weights": {"a": 1.0}}, "must be > 0"),
        ({"holdings": {"a": 100}, "target_weights": {"a": 1.2, "b": -0.2}}, ">= 0"),
        ({"holdings": {}, "target_weights": {"a": 1.0}}, "non-empty"),
    ],
)
def test_validation(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        rebalance(**kwargs)
