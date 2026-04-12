# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Unit tests for the regime classifier."""

from __future__ import annotations

import pytest

from nexus_core.engine.regime import (
    RegimeClassifier,
    RegimeCode,
    RegimeSignals,
    RegimeThresholds,
)


def _make_signals(**overrides) -> RegimeSignals:  # noqa: ANN003
    """Build a RegimeSignals instance with reasonable GROWTH defaults."""
    defaults = {
        "gold_spx_ratio": 0.40,  # GROWTH
        "gold_spx_200wma": 0.45,
        "gold_spx_vs_wma": "below",
        "real_rates": 2.0,  # risk-on
        "dxy": 107.0,  # strong
        "vix": 14.0,  # complacent
        "credit_spreads": 70.0,  # tight
    }
    defaults.update(overrides)
    return RegimeSignals(**defaults)


@pytest.mark.unit
class TestRegimeClassifier:
    def test_classifies_growth(self) -> None:
        classifier = RegimeClassifier()
        result = classifier.classify(_make_signals())
        assert result.regime == RegimeCode.GROWTH.value
        assert result.confidence_score > 50

    def test_classifies_hard_asset_at_high_gold_ratio(self) -> None:
        classifier = RegimeClassifier()
        signals = _make_signals(
            gold_spx_ratio=0.85,  # above transition max
            dxy=92.0,  # weak
            vix=24.0,  # neutral
            credit_spreads=180.0,  # wide
        )
        result = classifier.classify(signals)
        assert result.regime == RegimeCode.HARD_ASSET.value

    def test_classifies_transition_at_mid_ratio(self) -> None:
        classifier = RegimeClassifier()
        signals = _make_signals(
            gold_spx_ratio=0.60,  # between growth and hard asset
        )
        result = classifier.classify(signals)
        assert result.regime == RegimeCode.TRANSITION.value

    def test_deflation_override_when_crisis(self) -> None:
        classifier = RegimeClassifier()
        signals = _make_signals(
            gold_spx_ratio=0.40,
            vix=40.0,  # above vix_crisis
            credit_spreads=400.0,  # above spreads_wide_max
        )
        result = classifier.classify(signals)
        assert result.regime == RegimeCode.DEFLATION.value

    def test_repression_override_on_negative_real_rates(self) -> None:
        classifier = RegimeClassifier()
        signals = _make_signals(real_rates=-1.5)  # below repression
        result = classifier.classify(signals)
        assert result.regime == RegimeCode.REPRESSION.value

    def test_custom_thresholds_shift_classification(self) -> None:
        """Overriding thresholds should move the decision boundary."""
        signals = _make_signals(gold_spx_ratio=0.45)

        # Default: 0.45 is below growth_max (0.50) → GROWTH
        default_classifier = RegimeClassifier()
        assert default_classifier.classify(signals).regime == RegimeCode.GROWTH.value

        # Custom: tight growth_max forces TRANSITION
        strict_classifier = RegimeClassifier(thresholds=RegimeThresholds(gold_spx_growth_max=0.30))
        assert strict_classifier.classify(signals).regime == RegimeCode.TRANSITION.value

    def test_signal_statuses_populated(self) -> None:
        classifier = RegimeClassifier()
        result = classifier.classify(_make_signals())
        assert len(result.signal_statuses) >= 5  # at least the 5 core signals
        names = {s.name for s in result.signal_statuses}
        assert "Gold/SPX Ratio" in names
        assert "Real Rates" in names
        assert "Dollar Index (DXY)" in names
        assert "VIX" in names
        assert "Credit Spreads (BBB OAS)" in names

    def test_bond_futures_adds_signal(self) -> None:
        classifier = RegimeClassifier()
        signals = _make_signals(bond_futures_30y=110.0)
        result = classifier.classify(signals)
        names = {s.name for s in result.signal_statuses}
        assert "30Y Bond Futures" in names

    def test_prediction_market_contrarian(self) -> None:
        classifier = RegimeClassifier()
        result = classifier.classify(
            _make_signals(),
            prediction_market={"value": 85, "direction": "growth"},
        )
        # 85% conviction in growth should classify as contrarian
        pm_status = next(
            s for s in result.signal_statuses if s.name == "Prediction Market Consensus"
        )
        assert pm_status.status == "contrarian"
        # Contrarian on growth should support TRANSITION
        assert pm_status.supports_regime == RegimeCode.TRANSITION.value

    def test_rationale_includes_supporting_signals(self) -> None:
        classifier = RegimeClassifier()
        result = classifier.classify(_make_signals())
        assert result.regime in result.rationale
        assert "Supporting signals:" in result.rationale

    def test_to_dict_serializes(self) -> None:
        classifier = RegimeClassifier()
        result = classifier.classify(_make_signals())
        payload = result.to_dict()
        assert payload["regime"] == RegimeCode.GROWTH.value
        assert "confidence_score" in payload
        assert "signals" in payload
        assert "signal_statuses" in payload
