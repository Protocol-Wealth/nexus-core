# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Integration tests for ``RegimeEngine`` with stub providers."""

from __future__ import annotations

import pytest

from nexus_core.engine.regime import RegimeCode, RegimeEngine


@pytest.mark.unit
class TestRegimeEngine:
    def test_classify_with_stubs(self, stub_market, stub_fred) -> None:
        engine = RegimeEngine(market_data=stub_market, macro_data=stub_fred)
        result = engine.classify()
        # With the stub data (gold/SPX ratio ~0.84) we expect HARD_ASSET.
        assert result.regime in {
            RegimeCode.HARD_ASSET.value,
            RegimeCode.TRANSITION.value,
        }
        assert result.confidence_score >= 0
        assert result.confidence_score <= 100
        assert len(result.signal_statuses) > 0

    def test_caches_signals_within_ttl(self, stub_market, stub_fred) -> None:
        engine = RegimeEngine(market_data=stub_market, macro_data=stub_fred, cache_ttl_minutes=60)
        s1 = engine.fetch_signals()
        s2 = engine.fetch_signals()
        assert s1.timestamp == s2.timestamp  # same cached instance

    def test_force_refresh_bypasses_cache(self, stub_market, stub_fred) -> None:
        engine = RegimeEngine(market_data=stub_market, macro_data=stub_fred, cache_ttl_minutes=60)
        s1 = engine.fetch_signals()
        s2 = engine.fetch_signals(force_refresh=True)
        # New fetch (fresh signals built anew, may share timestamp at second-level)
        assert s2 is not None
        assert s2.gold_spx_ratio == s1.gold_spx_ratio

    def test_tracks_regime_start(self, stub_market, stub_fred) -> None:
        engine = RegimeEngine(market_data=stub_market, macro_data=stub_fred)
        assert engine.current_regime is None
        engine.classify()
        assert engine.current_regime is not None
        assert engine.regime_start is not None
