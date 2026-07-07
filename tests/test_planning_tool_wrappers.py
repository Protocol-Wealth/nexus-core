# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for planning tool wrapper input normalization."""

from __future__ import annotations

from nexus_core.app.planning.tools import rmd_tool, tax_aware_withdrawal_tool


def test_rmd_tool_accepts_birth_year_policy() -> None:
    out = rmd_tool({"age": 73, "balance": 500_000, "birthYear": 1960})
    assert out["rmdStartAge"] == 75
    assert out["applies"] is False
    assert out["rmdAmount"] == 0.0


def test_tax_aware_withdrawal_tool_accepts_birth_year_policy() -> None:
    out = tax_aware_withdrawal_tool(
        {
            "year": 2026,
            "filingStatus": "single",
            "accounts": [
                {"type": "traditional", "balance": 1_000_000, "allocation": {"x": 1.0}},
                {"type": "taxable", "balance": 500_000, "allocation": {"x": 1.0}},
            ],
            "grossNeed": 10_000,
            "age": 73,
            "birthYear": 1960,
            "otherTaxableIncome": 0,
        }
    )
    assert out["rmdStartAge"] == 75
    assert out["withdrawals"][0]["type"] == "taxable"
    assert out["withdrawals"][0]["gross"] == 10_000
