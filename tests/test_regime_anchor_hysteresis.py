# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Anchor hysteresis + override-aware conviction.

Two defects these pin:

1. The Gold/SPX anchor is the ONLY signal that selects the base regime and it had
   no dead-zone — a ratio hovering either side of a cutoff flipped the published
   regime day to day on noise.
2. Crisis regimes were scored by anchor agreement, but the anchor can never
   support DEFLATION or REPRESSION — so the engine reported its most severe calls
   with its lowest conviction (ceilings ~33 and ~16).
"""

from __future__ import annotations

from nexus_core.engine.regime.classifier import RegimeClassifier
from nexus_core.engine.regime.codes import RegimeCode
from nexus_core.engine.regime.signals import RegimeSignals

BAND = 0.02  # RegimeThresholds.gold_spx_hysteresis_band


def _signals(ratio: float, *, vix: float = 14.0, spreads: float = 95.0, real: float = 1.8) -> RegimeSignals:
    return RegimeSignals(
        gold_spx_ratio=ratio,
        gold_spx_200wma=0.40,
        gold_spx_vs_wma="above",
        real_rates=real,
        dxy=104.0,
        vix=vix,
        credit_spreads=spreads,
    )


class TestAnchorHysteresis:
    def test_no_prior_uses_plain_cutoffs(self) -> None:
        c = RegimeClassifier()
        assert c.classify(_signals(0.49)).regime == RegimeCode.GROWTH.value
        assert c.classify(_signals(0.51)).regime == RegimeCode.TRANSITION.value
        assert c.classify(_signals(0.71)).regime == RegimeCode.HARD_ASSET.value

    def test_noise_around_the_cutoff_no_longer_flips_the_regime(self) -> None:
        """0.4999 -> 0.5001 must NOT flip GROWTH -> TRANSITION. This is the bug."""
        c = RegimeClassifier()
        # Sitting in GROWTH, the ratio ticks just past 0.50 on noise.
        held = c.classify(_signals(0.5001), prior_regime=RegimeCode.GROWTH.value)
        assert held.regime == RegimeCode.GROWTH.value
        # Without a prior it WOULD have flipped — proving the band is what held it.
        assert c.classify(_signals(0.5001)).regime == RegimeCode.TRANSITION.value

    def test_a_real_move_still_transitions(self) -> None:
        """The band damps noise, it must not trap the regime."""
        c = RegimeClassifier()
        moved = c.classify(_signals(0.50 + BAND + 0.001), prior_regime=RegimeCode.GROWTH.value)
        assert moved.regime == RegimeCode.TRANSITION.value

    def test_hard_asset_is_sticky_downward_but_releases(self) -> None:
        c = RegimeClassifier()
        prior = RegimeCode.HARD_ASSET.value
        # just under 0.70 — inside the band, hold HARD_ASSET
        assert c.classify(_signals(0.695), prior_regime=prior).regime == RegimeCode.HARD_ASSET.value
        # cleared the band — release to TRANSITION
        assert c.classify(_signals(0.70 - BAND - 0.001), prior_regime=prior).regime == (
            RegimeCode.TRANSITION.value
        )

    def test_crisis_overrides_are_not_damped(self) -> None:
        """A crisis must register immediately, prior regime notwithstanding."""
        c = RegimeClassifier()
        crisis = c.classify(
            _signals(0.30, vix=40.0, spreads=300.0), prior_regime=RegimeCode.GROWTH.value
        )
        assert crisis.regime == RegimeCode.DEFLATION.value


class TestOverrideConviction:
    def test_deflation_no_longer_scores_lower_than_a_calm_growth_call(self) -> None:
        c = RegimeClassifier()
        deflation = c.classify(_signals(0.30, vix=40.0, spreads=300.0))
        assert deflation.regime == RegimeCode.DEFLATION.value
        # Old behaviour capped this around 33. It must now clear the floor.
        assert deflation.confidence_score >= 60

    def test_deeper_crisis_scores_higher(self) -> None:
        c = RegimeClassifier()
        marginal = c.classify(_signals(0.30, vix=36.0, spreads=255.0))
        severe = c.classify(_signals(0.30, vix=70.0, spreads=600.0))
        assert marginal.regime == severe.regime == RegimeCode.DEFLATION.value
        assert severe.confidence_score > marginal.confidence_score
        assert severe.confidence_score <= 100

    def test_repression_scores_by_how_far_below_the_trigger(self) -> None:
        c = RegimeClassifier()
        marginal = c.classify(_signals(0.30, real=-1.05))
        deep = c.classify(_signals(0.30, real=-2.5))
        assert marginal.regime == deep.regime == RegimeCode.REPRESSION.value
        assert marginal.confidence_score >= 60
        assert deep.confidence_score > marginal.confidence_score

    def test_anchor_regimes_still_score_by_agreement(self) -> None:
        """The agreement path is unchanged for non-crisis calls."""
        c = RegimeClassifier()
        growth = c.classify(_signals(0.30))
        assert growth.regime == RegimeCode.GROWTH.value
        assert 0 <= growth.confidence_score <= 100
