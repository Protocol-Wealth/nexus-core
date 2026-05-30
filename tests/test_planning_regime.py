# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the planning regime engine (taxonomy, transition matrix, paths)."""

from __future__ import annotations

import numpy as np

from nexus_core.engine.planning.regime import (
    GENERIC_REGIMES,
    path_cache_key,
    seed_from_cache_key,
    simulate_regime_path,
    to_generic_regime,
    transition_matrix,
)


def test_emf_to_generic_mapping() -> None:
    assert to_generic_regime("GROWTH") == "expansion"
    assert to_generic_regime("HARD_ASSET") == "inflationary"
    assert to_generic_regime("DEFLATION") == "deflationary"
    assert to_generic_regime("REPRESSION") == "stagflation"
    assert to_generic_regime("TRANSITION") == "crisis"
    assert to_generic_regime("SOMETHING_ELSE") == "expansion"  # safe default


def test_transition_matrix_rows_sum_to_one() -> None:
    tm = transition_matrix()
    assert set(tm) == set(GENERIC_REGIMES)
    for frm in GENERIC_REGIMES:
        assert set(tm[frm]) == set(GENERIC_REGIMES)
        assert abs(sum(tm[frm].values()) - 1.0) < 1e-9
        assert all(0.0 <= p <= 1.0 for p in tm[frm].values())


def test_transition_matrix_matches_spec_expansion_row() -> None:
    assert transition_matrix()["expansion"] == {
        "expansion": 0.80,
        "inflationary": 0.08,
        "deflationary": 0.04,
        "stagflation": 0.04,
        "crisis": 0.04,
    }


def test_cache_key_roundtrip() -> None:
    assert path_cache_key(12345) == "emf-v1-12345"
    assert seed_from_cache_key("emf-v1-12345") == 12345
    assert seed_from_cache_key(None) is None  # absent ⇒ miss
    assert seed_from_cache_key("some-other-engine-key") is None  # unknown ⇒ miss
    assert seed_from_cache_key("emf-v1-notanint") is None


def test_simulate_regime_path_deterministic_and_valid() -> None:
    p1 = simulate_regime_path("expansion", 50, np.random.default_rng(7))
    p2 = simulate_regime_path("expansion", 50, np.random.default_rng(7))
    assert p1 == p2  # same seed ⇒ identical path
    assert len(p1) == 50
    assert p1[0] == "expansion"  # starts at the start regime
    assert all(r in GENERIC_REGIMES for r in p1)
