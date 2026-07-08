# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the RMD calculator."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import rmd, rmd_start_age
from nexus_core.engine.planning.tax import RMD_START_AGE_POLICY_VERSION


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
    assert out["rmdStartAgePolicyVersion"] == RMD_START_AGE_POLICY_VERSION


def test_rmd_start_age_policy_table() -> None:
    assert rmd_start_age(None) == 73
    assert rmd_start_age(1948) == 70.5
    assert rmd_start_age(1949) == 72
    assert rmd_start_age(1950) == 72
    assert rmd_start_age(1951) == 73
    assert rmd_start_age(1959) == 73
    assert rmd_start_age(1960) == 75


def test_rmd_uses_birth_year_policy_for_1960_plus_cohort() -> None:
    age_73 = rmd(age=73, balance=500_000.0, birth_year=1960)
    assert age_73["rmdStartAge"] == 75
    assert age_73["applies"] is False
    assert age_73["rmdAmount"] == 0.0

    age_75 = rmd(age=75, balance=500_000.0, birth_year=1960)
    assert age_75["applies"] is True
    assert age_75["distributionPeriod"] == 24.6
    assert age_75["rmdAmount"] == round(500_000.0 / 24.6, 2)


def test_rmd_uses_good_faith_1959_age_73_policy() -> None:
    out = rmd(age=73, balance=500_000.0, birth_year=1959)
    assert out["rmdStartAge"] == 73
    assert out["rmdStartAgePolicyVersion"] == "secure2.0-goodfaith-73-per-89FR58644"
    assert out["applies"] is True


@pytest.mark.parametrize("birth_year", [True, 1899, 2201])
def test_rmd_start_age_rejects_bad_birth_year(birth_year: object) -> None:
    with pytest.raises(ValueError, match="birthYear"):
        rmd_start_age(birth_year)  # type: ignore[arg-type]


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
