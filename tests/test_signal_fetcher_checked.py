# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""``SignalFetcher.fetch_checked`` — which readings were OBSERVED vs. INVENTED.

Every reading resolves as ``fetched or default``, so an unreachable provider or a
key that is present but invalid / expired / rate-limited silently yields neutral
priors instead of an error. Deliberate on the serving path; unacceptable on any
path that PERSISTS the classification. These pin that the fetcher tells the truth
about which is which — an ``is_configured()`` check cannot, because a dead key is
configured.
"""

from __future__ import annotations

from typing import Any

from nexus_core.engine.regime.signal_fetcher import SignalFetcher


class _DeadMacro:
    """A key IS configured — it just doesn't work. The case is_configured() misses."""

    def is_configured(self) -> bool:
        return True

    def get_series(self, *_a: Any, **_k: Any) -> None:
        return None

    def get_latest(self, *_a: Any, **_k: Any) -> None:
        return None


class _DeadMarket:
    def get_quote(self, *_a: Any, **_k: Any) -> None:
        return None

    def get_history(self, *_a: Any, **_k: Any) -> list[Any]:
        return []


class _LiveMacro:
    _SERIES = {
        "DFII10": 1.83,
        "DTWEXBGS": 122.4,
        "VIXCLS": 14.2,
        "BAMLC0A4CBBB": 0.95,
        "DGS10": 4.1,
        "T5YIE": 2.3,
        "DGS2": 3.9,
    }

    def is_configured(self) -> bool:
        return True

    def get_series(self, series_id: str, *_a: Any, **_k: Any) -> float | None:
        return self._SERIES.get(series_id)

    def get_latest(self, series_id: str, *_a: Any, **_k: Any) -> float | None:
        return self._SERIES.get(series_id)


def test_dead_but_configured_macro_key_is_reported_as_defaulted() -> None:
    """The exact case an is_configured() guard cannot catch."""
    fetcher = SignalFetcher(market_data=_DeadMarket(), macro_data=_DeadMacro())  # type: ignore[arg-type]

    signals, defaulted = fetcher.fetch_checked()

    # The macro key is "configured" and returns nothing — every macro reading is invented.
    assert {"real_rates", "dxy", "vix", "credit_spreads"} <= defaulted
    # And the value handed back is the neutral prior, which looks perfectly plausible.
    assert signals.real_rates == fetcher.default_real_rates
    assert signals.vix == fetcher.default_vix


def test_dead_market_defaults_the_anchor_that_decides_the_regime() -> None:
    """Gold/SPX alone selects the base regime. If it is invented, nothing is trustworthy."""
    fetcher = SignalFetcher(market_data=_DeadMarket(), macro_data=_LiveMacro())  # type: ignore[arg-type]

    _, defaulted = fetcher.fetch_checked()

    assert "gold_spx_ratio" in defaulted


def test_no_macro_provider_at_all_is_reported() -> None:
    fetcher = SignalFetcher(market_data=_DeadMarket(), macro_data=None)

    _, defaulted = fetcher.fetch_checked()

    assert {"real_rates", "dxy", "credit_spreads"} <= defaulted


def test_fetch_delegates_to_fetch_checked_unchanged() -> None:
    """The serving path keeps its old shape: signals out, no error, defaults applied."""
    fetcher = SignalFetcher(market_data=_DeadMarket(), macro_data=_DeadMacro())  # type: ignore[arg-type]

    signals = fetcher.fetch()

    assert signals.real_rates == fetcher.default_real_rates
    assert signals.dxy == fetcher.default_dxy
    assert signals.credit_spreads == fetcher.default_credit_spreads
