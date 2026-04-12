# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Signal fetching helpers.

Separated from the classifier because fetching is I/O-bound and provider-
specific, while classification is pure. Users who already have signal data
in hand (from a cache, a database, or another system) can bypass this module
entirely and feed ``RegimeSignals`` straight to the ``RegimeClassifier``.

The implementations here assume:
    - Gold price via ``GC=F`` futures (fall back to ``GLD * 10``).
    - S&P 500 via ``SPY * 10``.
    - DXY via FRED ``DTWEXBGS`` (trade-weighted broad) with a caller-supplied
      conversion factor, with ``UUP`` ETF as cross-validation fallback.
    - Real rates via FRED ``DFII10`` (10Y TIPS).
    - Credit spreads via FRED ``BAMLC0A4CBBB`` (BBB OAS).
    - VIX via quote provider first (intraday), FRED ``VIXCLS`` as fallback.

If you use different sources, subclass ``SignalFetcher`` and override the
``_fetch_*`` methods you need to customize.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ...data.providers import MacroDataProvider, MarketDataProvider
from .signals import RegimeSignals

logger = logging.getLogger(__name__)


class SignalFetcher:
    """Fetches raw signals from configured data providers.

    Every fetch is best-effort: a failed provider returns ``None`` and the
    caller decides whether to substitute a neutral fallback. Neutral defaults
    should sit near the middle of the threshold range to avoid producing a
    confident classification when data is unavailable.

    .. warning::

        Default values below are illustrative mid-range fallbacks, not a
        current market snapshot. **Subclass and override them** with your
        own neutral priors — or better, set provider sources so the fallback
        path is never taken in production.
    """

    #: Neutral real-rate fallback when FRED is unavailable.
    default_real_rates: float = 1.5

    #: Neutral DXY fallback (~100 is the rough long-run midpoint).
    default_dxy: float = 100.0

    #: Neutral VIX fallback (~20 is the rough long-run median).
    default_vix: float = 20.0

    #: Neutral credit-spread fallback in bps.
    default_credit_spreads: float = 150.0

    #: Gold/SPX 200WMA fallback used when insufficient price history exists.
    #: A round-number mid-range value; tune against your own data.
    default_gold_spx_200wma: float = 0.50

    #: Gold and SPX absolute-level fallbacks used only to compute a ratio
    #: when quote providers fail. Override with current prices in production.
    default_gold: float = 2400.0
    default_spx: float = 5000.0

    #: FRED ``DTWEXBGS`` is trade-weighted and differs from ICE DXY; this
    #: scale factor approximately converts one to the other, but the mapping
    #: drifts over time. Validate against current DXY periodically and
    #: override this class attribute with your fitted value.
    dxy_conversion_factor: float = 0.85

    def __init__(
        self,
        market_data: MarketDataProvider | None = None,
        macro_data: MacroDataProvider | None = None,
    ) -> None:
        self.market = market_data
        self.macro = macro_data

    # ------------------------------------------------------------------ public

    def fetch(self) -> RegimeSignals:
        """Fetch all signals and return a populated ``RegimeSignals`` instance.

        This is a convenience wrapper — for more control, call the individual
        ``fetch_*`` methods and build ``RegimeSignals`` yourself.
        """
        gold = self._fetch_gold_price() or self.default_gold
        spx = self._fetch_spx_price() or self.default_spx
        gold_spx_ratio = gold / spx if spx > 0 else 0.45
        gold_spx_200wma = self.default_gold_spx_200wma

        if gold_spx_ratio > gold_spx_200wma * 1.05:
            vs_wma = "above"
        elif gold_spx_ratio < gold_spx_200wma * 0.95:
            vs_wma = "below"
        else:
            vs_wma = "testing"

        bond_futures = self._fetch_bond_futures_30y()
        yield_curve_spread, yield_curve_status = self._fetch_yield_curve_slope()

        return RegimeSignals(
            gold_spx_ratio=round(gold_spx_ratio, 4),
            gold_spx_200wma=round(gold_spx_200wma, 4),
            gold_spx_vs_wma=vs_wma,
            real_rates=self._fetch_real_rates() or self.default_real_rates,
            dxy=self._fetch_dxy() or self.default_dxy,
            vix=self._fetch_vix() or self.default_vix,
            credit_spreads=self._fetch_credit_spreads() or self.default_credit_spreads,
            hy_credit_spreads=self._fetch_hy_credit_spreads(),
            breadth=None,
            bond_futures_30y=round(bond_futures, 2) if bond_futures else None,
            yield_curve_2s10s=(
                round(yield_curve_spread, 2) if yield_curve_spread is not None else None
            ),
            yield_curve_status=yield_curve_status,
            timestamp=datetime.now(UTC),
        )

    # ---------------------------------------------------------------- per-signal

    def _fetch_gold_price(self) -> float | None:
        if self.market is None:
            return None
        for sym in ("GC=F", "GLD"):
            try:
                q = self.market.get_quote(sym)
                if q and q.price > 0:
                    # GLD tracks ~1/10 oz of gold; scale up to match GC=F.
                    return q.price * 10 if sym == "GLD" else q.price
            except Exception as e:  # pragma: no cover
                logger.debug("gold fetch via %s failed: %s", sym, e)
        return None

    def _fetch_spx_price(self) -> float | None:
        if self.market is None:
            return None
        try:
            q = self.market.get_quote("SPY")
            if q and q.price > 0:
                return q.price * 10  # SPY is ~1/10 of SPX
        except Exception as e:  # pragma: no cover
            logger.debug("spx fetch failed: %s", e)
        return None

    def _fetch_real_rates(self) -> float | None:
        if self.macro is None or not self.macro.is_configured():
            return None
        try:
            val = self.macro.get_series("DFII10")
            if val is not None:
                return round(val, 2)
            # Fallback: 10Y nominal - 5Y breakeven inflation.
            dgs10 = self.macro.get_series("DGS10")
            t5yie = self.macro.get_series("T5YIE")
            if dgs10 is not None and t5yie is not None:
                return round(dgs10 - t5yie, 2)
        except Exception as e:  # pragma: no cover
            logger.debug("real rates fetch failed: %s", e)
        return None

    def _fetch_dxy(self) -> float | None:
        """Fetch DXY via FRED with UUP cross-validation."""
        fred_dxy: float | None = None
        uup_dxy: float | None = None

        # 1. FRED (preferred)
        if self.macro is not None and self.macro.is_configured():
            try:
                dtwexbgs = self.macro.get_series("DTWEXBGS")
                if dtwexbgs is not None:
                    fred_dxy = round(dtwexbgs * self.dxy_conversion_factor, 1)
            except Exception as e:  # pragma: no cover
                logger.debug("FRED DXY fetch failed: %s", e)

        # 2. UUP ETF cross-validation
        if self.market is not None:
            try:
                q = self.market.get_quote("UUP")
                if q and q.price > 10:
                    estimate = round(q.price * 3.6 + 5.0, 1)
                    if 80 <= estimate <= 130:
                        uup_dxy = estimate
            except Exception as e:  # pragma: no cover
                logger.debug("UUP DXY fetch failed: %s", e)

        if fred_dxy is not None and uup_dxy is not None and abs(fred_dxy - uup_dxy) > 3.0:
            logger.warning(
                "DXY source discrepancy: FRED=%s, UUP=%s — using FRED.",
                fred_dxy,
                uup_dxy,
            )
        return fred_dxy if fred_dxy is not None else uup_dxy

    def _fetch_vix(self) -> float | None:
        """Prefer intraday quote, fall back to FRED end-of-day."""
        if self.market is not None:
            for sym in ("^VIX", "VIX"):
                try:
                    q = self.market.get_quote(sym)
                    if q and q.price > 0:
                        return q.price
                except Exception:  # pragma: no cover
                    continue
        if self.macro is not None and self.macro.is_configured():
            try:
                vix = self.macro.get_series("VIXCLS")
                if vix is not None:
                    return float(vix)
            except Exception as e:  # pragma: no cover
                logger.debug("FRED VIX fetch failed: %s", e)
        return None

    def _fetch_credit_spreads(self) -> float | None:
        """BBB OAS in bps (primary regime input)."""
        if self.macro is None or not self.macro.is_configured():
            return None
        try:
            oas = self.macro.get_series("BAMLC0A4CBBB")
            if oas is not None:
                return round(oas * 100, 0)  # percent → bps
            # Fallback: HY OAS, divide by ~3 to approximate IG equivalent.
            hy = self.macro.get_series("BAMLH0A0HYM2")
            if hy is not None:
                return round(hy * 100 / 3, 0)
        except Exception as e:  # pragma: no cover
            logger.debug("credit spreads fetch failed: %s", e)
        return None

    def _fetch_hy_credit_spreads(self) -> float | None:
        if self.macro is None or not self.macro.is_configured():
            return None
        try:
            hy = self.macro.get_series("BAMLH0A0HYM2")
            if hy is not None:
                return round(hy * 100, 0)
        except Exception as e:  # pragma: no cover
            logger.debug("HY spreads fetch failed: %s", e)
        return None

    def _fetch_bond_futures_30y(self) -> float | None:
        if self.market is None:
            return None
        try:
            q = self.market.get_quote("ZB=F")
            if q and q.price > 0:
                return q.price
            # Fallback: TLT proxy (long treasury ETF).
            q = self.market.get_quote("TLT")
            if q and q.price > 0:
                return q.price * 1.25
        except Exception as e:  # pragma: no cover
            logger.debug("bond futures fetch failed: %s", e)
        return None

    def _fetch_yield_curve_slope(self) -> tuple[float | None, str | None]:
        """Return (10Y - 2Y spread, status string)."""
        if self.macro is None or not self.macro.is_configured():
            return None, None
        try:
            dgs10 = self.macro.get_series("DGS10")
            dgs2 = self.macro.get_series("DGS2")
            if dgs10 is None or dgs2 is None:
                return None, None
            spread = round(dgs10 - dgs2, 2)
            if spread > 0.5:
                status = "normal"
            elif spread > 0:
                status = "flattening"
            else:
                status = "inverted"
            return spread, status
        except Exception as e:  # pragma: no cover
            logger.debug("yield curve fetch failed: %s", e)
            return None, None


__all__ = ["SignalFetcher"]
