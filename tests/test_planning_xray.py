# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the portfolio X-ray engine."""

from __future__ import annotations

import pytest

from nexus_core.engine.planning import portfolio_xray


def _by_id(out: dict, fid: str) -> dict:
    return next(f for f in out["findings"] if f["id"] == fid)


def test_metrics_and_findings_hand_values() -> None:
    # 65% us_equity (r .07, vol .16, λ .35) + 35% us_bonds (r .03, vol .05, λ .10),
    # balances 700k traditional + 300k roth, live regime = crisis.
    out = portfolio_xray(
        asset_ids=["us_equity", "us_bonds"],
        weights=[0.65, 0.35],
        means=[0.07, 0.03],
        vols=[0.16, 0.05],
        lambdas=[0.35, 0.10],
        account_balances={"traditional": 700_000, "roth": 300_000},
        regime="crisis",
    )
    assert out["weightedExpectedReturn"] == 0.056  # .65*.07 + .35*.03
    assert out["weightedAvgVolatility"] == 0.1215
    assert out["portfolioLambda"] == 0.2625
    assert out["growthAllocation"] == 0.65  # only us_equity vol >= 0.12
    assert out["concentration"] == {
        "maxWeight": 0.65,
        "maxWeightAsset": "us_equity",
        "herfindahl": 0.545,  # .65^2 + .35^2
        "effectiveHoldings": 1.83,  # 1/0.545
    }
    assert out["accountMix"] == {"taxable": 0.0, "traditional": 0.7, "roth": 0.3}
    # 0.65 >= 0.60 -> concentration alert
    assert _by_id(out, "concentration")["severity"] == "alert"
    # crisis (adverse) + λ 0.2625 in [0.15, 0.30) -> regime sensitivity warn
    assert _by_id(out, "regime_sensitivity")["severity"] == "warn"
    # 70% traditional < 90% -> tax-location info
    assert _by_id(out, "tax_location")["severity"] == "info"


def test_regime_sensitivity_is_conditioned_on_the_regime() -> None:
    kw = {
        "asset_ids": ["a", "b"],
        "weights": [0.5, 0.5],
        "means": [0.07, 0.03],
        "vols": [0.16, 0.05],
        "lambdas": [0.4, 0.4],  # portfolio λ = 0.40, above the alert threshold
        "account_balances": {"taxable": 1_000_000},
    }
    assert _by_id(portfolio_xray(**kw, regime="crisis"), "regime_sensitivity")["severity"] == "alert"
    # Same high-λ portfolio in a benign regime is only informational.
    assert _by_id(portfolio_xray(**kw, regime="expansion"), "regime_sensitivity")["severity"] == "info"


def test_tax_location_concentration_warns() -> None:
    out = portfolio_xray(
        asset_ids=["a"],
        weights=[1.0],
        means=[0.06],
        vols=[0.14],
        lambdas=[0.2],
        account_balances={"traditional": 1_000_000},  # 100% one bucket
        regime="expansion",
    )
    assert _by_id(out, "tax_location")["severity"] == "warn"
    assert _by_id(out, "concentration")["severity"] == "alert"  # single asset
    assert out["concentration"]["effectiveHoldings"] == 1.0


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        (
            {"asset_ids": ["a"], "weights": [1.0], "means": [0.05], "vols": [0.1],
             "lambdas": [0.2, 0.3], "account_balances": {}, "regime": "crisis"},
            "must align",
        ),
        (
            {"asset_ids": [], "weights": [], "means": [], "vols": [], "lambdas": [],
             "account_balances": {}, "regime": "crisis"},
            "at least one asset",
        ),
    ],
)
def test_validation(kwargs: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        portfolio_xray(**kwargs)
