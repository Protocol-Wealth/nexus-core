# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the injected tax/IRMAA tables + their wire-form parsers.

The ``from_dict`` parsers are the path a caller (pw-api) uses to inject a
snapshotted table over the wire, so they are part of the ABI.
"""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

import pytest

from nexus_core.engine.planning.tables import (
    BracketTable,
    IrmaaTable,
    StateConversionRule,
    TableError,
    reference_bracket_table,
    reference_irmaa_table,
)


def _bracket_table_to_wire(bt: BracketTable) -> dict[str, Any]:
    """Serialize a BracketTable to JSON-safe wire form (inf upper bound -> null)."""
    d = asdict(bt)
    d["ordinary_brackets"] = {
        fs: [[None if math.isinf(u) else u, r] for (u, r) in rows]
        for fs, rows in bt.ordinary_brackets.items()
    }
    return d


def test_bracket_table_round_trips_through_wire_form() -> None:
    bt = reference_bracket_table(2026)
    parsed = BracketTable.from_dict(_bracket_table_to_wire(bt))
    assert parsed.year == bt.year
    assert parsed.brackets_for("single") == bt.brackets_for("single")
    assert math.isinf(parsed.brackets_for("single")[-1][0])  # top bracket preserved as inf
    assert parsed.standard_deduction == bt.standard_deduction
    assert parsed.table_version == bt.table_version
    assert parsed.niit_threshold == bt.niit_threshold
    assert parsed.ss_provisional_thresholds == bt.ss_provisional_thresholds


def test_irmaa_table_round_trips_through_wire_form() -> None:
    it = reference_irmaa_table("married_joint", 2025)
    parsed = IrmaaTable.from_dict(asdict(it))
    assert parsed.source_year == 2025
    assert parsed.filing_status == "married_joint"
    assert parsed.table_version == it.table_version
    assert [t.magi_floor for t in parsed.tiers] == [t.magi_floor for t in it.tiers]


def test_reference_bracket_table_rejects_unregistered_year() -> None:
    with pytest.raises(TableError, match="no reference federal tax table registered"):
        reference_bracket_table(2027)


def test_reference_irmaa_table_rejects_unregistered_source_year() -> None:
    with pytest.raises(TableError, match="no reference IRMAA table registered"):
        reference_irmaa_table("single", 2026)


def test_state_rule_from_dict() -> None:
    rule = StateConversionRule.from_dict(
        {
            "state_code": "pa",
            "treatment": "exempt_retirement",
            "rate": 0.0307,
            "retirement_exempt_age": 59,
        }
    )
    assert rule.state_code == "PA"
    assert rule.treatment == "exempt_retirement"


def test_bracket_table_from_dict_rejects_missing_filing_status() -> None:
    bt = reference_bracket_table(2026)
    wire = _bracket_table_to_wire(bt)
    del wire["standard_deduction"]["single"]
    with pytest.raises(TableError, match="standard_deduction"):
        BracketTable.from_dict(wire)


def test_bracket_table_requires_open_ended_top_bracket() -> None:
    with pytest.raises(TableError, match="infinity"):
        BracketTable(
            year=2026,
            ordinary_brackets={
                fs: [(10_000.0, 0.10), (50_000.0, 0.22)]  # no inf top -> invalid
                for fs in ("single", "married_joint", "married_separate", "head_of_household")
            },
            standard_deduction=dict.fromkeys(
                ("single", "married_joint", "married_separate", "head_of_household"), 15_000.0
            ),
            additional_std_deduction_per_senior=dict.fromkeys(
                ("single", "married_joint", "married_separate", "head_of_household"), 2_000.0
            ),
            senior_bonus_deduction_per_senior=6_000.0,
            senior_bonus_phaseout=dict.fromkeys(
                ("single", "married_joint", "married_separate", "head_of_household"),
                (75_000.0, 0.06),
            ),
            ltcg_breakpoints=dict.fromkeys(
                ("single", "married_joint", "married_separate", "head_of_household"),
                (48_350.0, 533_400.0),
            ),
            niit_threshold=dict.fromkeys(
                ("single", "married_joint", "married_separate", "head_of_household"), 200_000.0
            ),
            ss_provisional_thresholds=dict.fromkeys(
                ("single", "married_joint", "married_separate", "head_of_household"),
                (25_000.0, 34_000.0),
            ),
        )


def test_total_deduction_phases_out_senior_bonus() -> None:
    bt = reference_bracket_table(2026)
    low = bt.total_deduction("single", itemized=None, n_seniors=1, magi=50_000.0)
    high = bt.total_deduction("single", itemized=None, n_seniors=1, magi=200_000.0)
    assert low > high  # the $6k bonus phases out at high MAGI
