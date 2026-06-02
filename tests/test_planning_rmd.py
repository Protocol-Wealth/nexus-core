# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the RMD calculator."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import rmd


def test_no_rmd_before_start_age() -> None:
    out = rmd(age=70, balance=500_000.0)
    assert out["applies"] is False
    assert out["rmdAmount"] == 0.0
    assert out["rmdStartAge"] == 73


def test_rmd_at_start_age() -> None:
    out = rmd(age=73, balance=500_000.0)
    assert out["applies"] is True
    assert out["distributionPeriod"] == 26.5
    assert out["rmdAmount"] == round(500_000.0 / 26.5, 2)  # 18867.92
    assert out["effectiveRate"] == round((500_000.0 / 26.5) / 500_000.0, 4)


def test_rmd_beyond_table_uses_last_factor() -> None:
    out = rmd(age=105, balance=100_000.0)
    assert out["distributionPeriod"] == 6.4  # age-100 factor, clamped
    assert out["rmdAmount"] == round(100_000.0 / 6.4, 2)


def test_zero_balance() -> None:
    out = rmd(age=75, balance=0.0)
    assert out["rmdAmount"] == 0.0
    assert out["effectiveRate"] == 0.0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"age": -1, "balance": 100.0}, "age must be non-negative"),
        ({"age": 75, "balance": -1.0}, "balance must be non-negative"),
    ],
)
def test_validation(kwargs: dict[str, object], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        rmd(**kwargs)  # type: ignore[arg-type]
