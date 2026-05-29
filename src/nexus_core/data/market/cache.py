# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""In-process caching + usage tracking for market data providers.

Two thin :class:`~nexus_core.data.providers.MarketDataProvider` wrappers:

- :class:`CachedMarketData` — a per-instance TTL cache over an inner provider
  (typically the composite). Repeated quote/history requests for the same key
  are served from memory, which sharply cuts upstream calls to the quota-limited
  keyed providers (MBOUM, MarketStack). Only *successful* results are cached, so
  a transient miss retries rather than sticking. Thread-safe (FastAPI runs the
  sync providers in a threadpool).
- :class:`UsageTrackingMarketData` — counts calls reaching a specific provider,
  so the deployment can monitor how much quota MBOUM / MarketStack are actually
  consuming (the per-provider usage tracking; a hard outbound cap is deferred).

``CachedMarketData.usage_report()`` aggregates the cache hit-rate and the tracked
providers' call counts for a monitoring endpoint.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Sequence

from ..providers import MarketDataProvider, PriceBar, Quote

#: Default cache lifetimes (seconds): quotes are short-lived, history slow.
_DEFAULT_QUOTE_TTL = 300.0
_DEFAULT_HISTORY_TTL = 3600.0


class UsageTrackingMarketData:
    """Wrap a provider and count the calls reaching it (for quota monitoring)."""

    def __init__(self, inner: MarketDataProvider, name: str) -> None:
        self._inner = inner
        self._name = name
        self._lock = threading.Lock()
        self._quote_calls = 0
        self._history_calls = 0

    def get_quote(self, symbol: str) -> Quote | None:
        with self._lock:
            self._quote_calls += 1
        return self._inner.get_quote(symbol)

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        with self._lock:
            self._history_calls += 1
        return self._inner.get_price_history(symbol, days=days, interval=interval)

    @property
    def usage(self) -> dict[str, object]:
        with self._lock:
            return {
                "provider": self._name,
                "get_quote": self._quote_calls,
                "get_price_history": self._history_calls,
            }


class CachedMarketData:
    """TTL cache over an inner provider; caches only successful results.

    Args:
        inner: The wrapped provider (e.g. the composite).
        quote_ttl: Quote cache lifetime in seconds.
        history_ttl: Price-history cache lifetime in seconds.
        tracked: Optional usage-tracking wrappers to surface in
            :meth:`usage_report` (typically the MBOUM / MarketStack trackers).
    """

    def __init__(
        self,
        inner: MarketDataProvider,
        *,
        quote_ttl: float = _DEFAULT_QUOTE_TTL,
        history_ttl: float = _DEFAULT_HISTORY_TTL,
        tracked: Sequence[UsageTrackingMarketData] = (),
    ) -> None:
        self._inner = inner
        self._quote_ttl = quote_ttl
        self._history_ttl = history_ttl
        self._tracked = list(tracked)
        self._lock = threading.Lock()
        self._quotes: dict[str, tuple[float, Quote]] = {}
        self._history: dict[tuple[str, int, str], tuple[float, list[PriceBar]]] = {}
        self._hits = 0
        self._misses = 0

    def get_quote(self, symbol: str) -> Quote | None:
        now = time.monotonic()
        with self._lock:
            entry = self._quotes.get(symbol)
            if entry is not None and now - entry[0] < self._quote_ttl:
                self._hits += 1
                return entry[1]
            self._misses += 1
        quote = self._inner.get_quote(symbol)
        if quote is not None:
            with self._lock:
                self._quotes[symbol] = (now, quote)
        return quote

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        key = (symbol, days, interval)
        now = time.monotonic()
        with self._lock:
            entry = self._history.get(key)
            if entry is not None and now - entry[0] < self._history_ttl:
                self._hits += 1
                return entry[1]
            self._misses += 1
        bars = self._inner.get_price_history(symbol, days=days, interval=interval)
        if bars:
            with self._lock:
                self._history[key] = (now, bars)
        return bars

    def usage_report(self) -> dict[str, object]:
        """Cache hit-rate + tracked-provider call counts, for monitoring."""
        with self._lock:
            hits, misses = self._hits, self._misses
        total = hits + misses
        return {
            "cache": {
                "hits": hits,
                "misses": misses,
                "hit_rate": round(hits / total, 3) if total else None,
                "cached_quotes": len(self._quotes),
                "cached_histories": len(self._history),
            },
            "tracked_providers": [t.usage for t in self._tracked],
        }


__all__ = ["CachedMarketData", "UsageTrackingMarketData"]
