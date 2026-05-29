# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the pure hold-strategy benchmark math."""

from __future__ import annotations

import pytest

from nexus_core.engine.benchmarks import (
    build_benchmark_series,
    composition_series,
    normalize_base_100,
)


def test_normalize_base_100() -> None:
    assert normalize_base_100([2000.0, 3000.0, 1000.0]) == pytest.approx([100.0, 150.0, 50.0])


def test_normalize_empty_or_zero_base() -> None:
    assert normalize_base_100([]) == []
    assert normalize_base_100([0.0, 100.0]) == []


def test_composition_single_asset() -> None:
    series = composition_series({"ETH": [2000.0, 3000.0]}, {"ETH": 1.0})
    assert series == pytest.approx([100.0, 150.0])  # ETH +50%


def test_composition_50_50_eth_usdc() -> None:
    # ETH +50%, USDC flat → 50/50 buy-and-hold → +25%
    series = composition_series(
        {"ETH": [2000.0, 3000.0], "USDC": [1.0, 1.0]}, {"ETH": 0.5, "USDC": 0.5}
    )
    assert series == pytest.approx([100.0, 125.0])


def test_composition_skips_zero_base_asset() -> None:
    # SOL has a zero base price → its weight drops out; only ETH contributes.
    series = composition_series(
        {"ETH": [1000.0, 2000.0], "SOL": [0.0, 50.0]}, {"ETH": 0.5, "SOL": 0.5}
    )
    # Only ETH: 0.5 * (price_t/price_0) * 100 → [50, 100]
    assert series == pytest.approx([50.0, 100.0])


def test_build_benchmark_series_total_return() -> None:
    bench = build_benchmark_series(
        "ETH", {"ETH": 1.0}, {"ETH": [2000.0, 3000.0]}, ["t0", "t1"]
    )
    assert bench is not None
    assert bench.name == "ETH"
    assert [p.value for p in bench.points] == pytest.approx([100.0, 150.0])
    assert [p.timestamp for p in bench.points] == ["t0", "t1"]
    assert bench.total_return_pct == pytest.approx(50.0)


def test_build_benchmark_series_empty_returns_none() -> None:
    assert build_benchmark_series("ETH", {"ETH": 1.0}, {}, []) is None
