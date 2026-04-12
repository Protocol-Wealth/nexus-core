# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Regime classifier — pure function from signals to regime code.

Given a ``RegimeSignals`` instance and configured thresholds, classify each
signal and return a ``RegimeResult`` with the majority-supported regime,
confidence score, and per-signal explainability data.

The classifier is intentionally a small pure module — it doesn't fetch data,
doesn't persist state (aside from the injected hysteresis state), and doesn't
perform I/O. This makes it trivial to test and composes cleanly with any
data source.
"""

from __future__ import annotations

from .codes import RegimeCode
from .hysteresis import HysteresisState, ZoneBoundary
from .signals import RegimeResult, RegimeSignals, SignalStatus
from .thresholds import RegimeThresholds


class RegimeClassifier:
    """Classify a ``RegimeSignals`` snapshot into a ``RegimeCode``.

    Stateful only in that it holds the VIX hysteresis zone; all other logic
    is derived from the current signals and thresholds. To share hysteresis
    state across process restarts, pass a ``HysteresisStore`` to the
    ``vix_state`` constructor.
    """

    def __init__(
        self,
        thresholds: RegimeThresholds | None = None,
        vix_state: HysteresisState | None = None,
    ) -> None:
        self.thresholds = thresholds or RegimeThresholds()
        self.vix_state = vix_state or HysteresisState(
            default_zone="normal",
            zones=[
                ZoneBoundary(
                    "elevated",
                    enter=self.thresholds.vix_elevated_enter,
                    exit=self.thresholds.vix_elevated_exit,
                ),
                ZoneBoundary(
                    "crisis",
                    enter=self.thresholds.vix_crisis_enter,
                    exit=self.thresholds.vix_crisis_exit,
                ),
            ],
        )

    # ---------------------------------------------------------------- public

    def classify(
        self,
        signals: RegimeSignals,
        *,
        prior_regime: str | None = None,
        days_in_regime: int = 0,
        prediction_market: dict[str, float | str] | None = None,
    ) -> RegimeResult:
        """Classify signals into a regime result.

        Args:
            signals: Current signal readings.
            prior_regime: Last regime code, used by the forced-liquidation
                dampener to decide whether to hold a prior classification.
            days_in_regime: Days since the last regime transition.
            prediction_market: Optional 6th signal (conviction + direction).
        """
        signal_statuses = self._classify_signals(signals, prediction_market)

        # Primary classification: Gold/SPX ratio is the anchor signal.
        t = self.thresholds
        if signals.gold_spx_ratio < t.gold_spx_growth_max:
            primary = RegimeCode.GROWTH
        elif signals.gold_spx_ratio < t.gold_spx_transition_max:
            primary = RegimeCode.TRANSITION
        else:
            primary = RegimeCode.HARD_ASSET

        # Crisis overrides — sustained stress trumps the gold/SPX reading.
        if signals.vix > t.vix_crisis and signals.credit_spreads > t.spreads_wide_max:
            primary = RegimeCode.DEFLATION
        elif signals.real_rates < t.real_rates_repression:
            primary = RegimeCode.REPRESSION

        # Confidence: how many of the classified signals agree with primary?
        confidence = self._confidence(signal_statuses, primary)

        rationale = self._build_rationale(signal_statuses, primary)

        return RegimeResult(
            regime=primary.value,
            confidence_score=confidence,
            days_in_regime=days_in_regime,
            signals=signals,
            signal_statuses=signal_statuses,
            rationale=rationale,
        )

    # ---------------------------------------------------------------- internal

    def _classify_signals(
        self,
        signals: RegimeSignals,
        prediction_market: dict[str, float | str] | None,
    ) -> list[SignalStatus]:
        """Run per-signal classification and return status list."""
        t = self.thresholds
        statuses: list[SignalStatus] = []

        # 1. Gold/SPX ratio
        if signals.gold_spx_ratio < t.gold_spx_growth_max:
            statuses.append(
                SignalStatus(
                    name="Gold/SPX Ratio",
                    current_value=signals.gold_spx_ratio,
                    threshold_info=f"<{t.gold_spx_growth_max}=Growth, >{t.gold_spx_hard_asset_min}=Hard Asset",
                    status="bullish",
                    supports_regime=RegimeCode.GROWTH.value,
                )
            )
        elif signals.gold_spx_ratio < t.gold_spx_transition_max:
            statuses.append(
                SignalStatus(
                    name="Gold/SPX Ratio",
                    current_value=signals.gold_spx_ratio,
                    threshold_info=f"<{t.gold_spx_growth_max}=Growth, >{t.gold_spx_hard_asset_min}=Hard Asset",
                    status="neutral",
                    supports_regime=RegimeCode.TRANSITION.value,
                )
            )
        else:
            statuses.append(
                SignalStatus(
                    name="Gold/SPX Ratio",
                    current_value=signals.gold_spx_ratio,
                    threshold_info=f"<{t.gold_spx_growth_max}=Growth, >{t.gold_spx_hard_asset_min}=Hard Asset",
                    status="bearish",
                    supports_regime=RegimeCode.HARD_ASSET.value,
                )
            )

        # 2. Real rates
        if signals.real_rates > t.real_rates_risk_on:
            status, supports = "bullish", RegimeCode.GROWTH.value
        elif signals.real_rates > t.real_rates_risk_off:
            status, supports = "neutral", RegimeCode.TRANSITION.value
        elif signals.real_rates > t.real_rates_repression:
            status, supports = "bearish", RegimeCode.HARD_ASSET.value
        else:
            status, supports = "crisis", RegimeCode.REPRESSION.value
        statuses.append(
            SignalStatus(
                name="Real Rates",
                current_value=signals.real_rates,
                threshold_info=f">{t.real_rates_risk_on}%=Risk On, <{t.real_rates_repression}%=Repression",
                status=status,
                supports_regime=supports,
            )
        )

        # 3. DXY
        if signals.dxy > t.dxy_strong:
            status, supports = "bullish", RegimeCode.GROWTH.value
        elif signals.dxy > t.dxy_weak:
            status, supports = "neutral", RegimeCode.TRANSITION.value
        else:
            status, supports = "bearish", RegimeCode.HARD_ASSET.value
        statuses.append(
            SignalStatus(
                name="Dollar Index (DXY)",
                current_value=signals.dxy,
                threshold_info=f">{t.dxy_strong}=Strong, <{t.dxy_weak}=Weak",
                status=status,
                supports_regime=supports,
            )
        )

        # 4. VIX (with hysteresis)
        vix = signals.vix
        new_zone = self.vix_state.update(vix)
        if vix < t.vix_complacent:
            status, supports = "bullish", RegimeCode.GROWTH.value
        elif new_zone == "crisis":
            status, supports = "crisis", RegimeCode.DEFLATION.value
        elif new_zone == "elevated":
            status, supports = "bearish", RegimeCode.HARD_ASSET.value
        else:
            status, supports = "neutral", RegimeCode.TRANSITION.value
        statuses.append(
            SignalStatus(
                name="VIX",
                current_value=signals.vix,
                threshold_info=(
                    f"<{t.vix_complacent}=Complacent, enter>{t.vix_elevated_enter}=Elevated, "
                    f"exit<{t.vix_elevated_exit}"
                ),
                status=status,
                supports_regime=supports,
            )
        )

        # 5. Credit spreads (BBB OAS)
        if signals.credit_spreads < t.spreads_tight:
            status, supports = "bullish", RegimeCode.GROWTH.value
        elif signals.credit_spreads < t.spreads_normal_max:
            status, supports = "neutral", RegimeCode.TRANSITION.value
        elif signals.credit_spreads < t.spreads_wide_max:
            status, supports = "bearish", RegimeCode.HARD_ASSET.value
        else:
            status, supports = "crisis", RegimeCode.DEFLATION.value
        statuses.append(
            SignalStatus(
                name="Credit Spreads (BBB OAS)",
                current_value=signals.credit_spreads,
                threshold_info=f"<{t.spreads_tight}bps=Tight, >{t.spreads_wide_max}bps=Crisis",
                status=status,
                supports_regime=supports,
            )
        )

        # 6. Bond futures (PM signal)
        if signals.bond_futures_30y is not None:
            if signals.bond_futures_30y <= t.bond_futures_bullish_pm:
                status, supports = "bullish", RegimeCode.HARD_ASSET.value
            elif signals.bond_futures_30y >= t.bond_futures_bearish_pm:
                status, supports = "bearish", RegimeCode.GROWTH.value
            else:
                status, supports = "neutral", RegimeCode.TRANSITION.value
            statuses.append(
                SignalStatus(
                    name="30Y Bond Futures",
                    current_value=signals.bond_futures_30y,
                    threshold_info=(
                        f"<{t.bond_futures_bullish_pm}=PM Bullish, "
                        f">{t.bond_futures_bearish_pm}=PM Bearish"
                    ),
                    status=status,
                    supports_regime=supports,
                )
            )

        # 7. Prediction market (optional, contrarian when >75%)
        if prediction_market is not None:
            conviction = float(prediction_market.get("value", 50))
            direction = str(prediction_market.get("direction", "transition"))

            if conviction > 75:
                # Contrarian — extreme consensus is itself a warning.
                contrarian_map = {
                    "growth": RegimeCode.TRANSITION.value,
                    "hard_asset": RegimeCode.TRANSITION.value,
                    "deflation": RegimeCode.GROWTH.value,
                    "transition": RegimeCode.TRANSITION.value,
                }
                supports = contrarian_map.get(direction, RegimeCode.TRANSITION.value)
                status = "contrarian"
            else:
                direction_map = {
                    "growth": RegimeCode.GROWTH.value,
                    "hard_asset": RegimeCode.HARD_ASSET.value,
                    "deflation": RegimeCode.DEFLATION.value,
                    "transition": RegimeCode.TRANSITION.value,
                }
                supports = direction_map.get(direction, RegimeCode.TRANSITION.value)
                if conviction > 60:
                    status = "bullish"
                elif conviction > 40:
                    status = "neutral"
                else:
                    status = "bearish"

            statuses.append(
                SignalStatus(
                    name="Prediction Market Consensus",
                    current_value=conviction,
                    threshold_info=">75=Contrarian, 50-70=Growth, 30-50=Neutral, <30=Risk-Off",
                    status=status,
                    supports_regime=supports,
                )
            )

        return statuses

    @staticmethod
    def _confidence(statuses: list[SignalStatus], regime: RegimeCode) -> int:
        """Confidence 0-100 based on signal agreement with the regime."""
        if not statuses:
            return 50
        supporting = sum(1 for s in statuses if s.supports_regime == regime.value)
        base = int((supporting / len(statuses)) * 100)

        # Weight the anchor signal extra — it's load-bearing by design.
        gold_spx = next((s for s in statuses if s.name == "Gold/SPX Ratio"), None)
        if gold_spx and gold_spx.supports_regime == regime.value:
            base = min(100, base + 15)
        return max(0, min(100, base))

    @staticmethod
    def _build_rationale(statuses: list[SignalStatus], regime: RegimeCode) -> str:
        """Short rationale string from top 3 supporting signals."""
        supporting = [s for s in statuses if s.supports_regime == regime.value]
        if not supporting:
            return f"Regime: {regime.value} (no strongly-supporting signals)."
        parts = [f"{s.name}: {s.current_value:.2f} ({s.status})" for s in supporting[:3]]
        return f"Regime: {regime.value}. Supporting signals: {', '.join(parts)}"


__all__ = ["RegimeClassifier"]
