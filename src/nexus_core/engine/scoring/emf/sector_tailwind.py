# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF Check #7 — Sector Tailwind.

Faithful port of ``_check_sector_tailwind`` from the Protocol Wealth research
engine (``app/engine/portfolio_engine.py``). The check asks a single question:

    Is this asset's sector outperforming the broad market (SPX) over the
    trailing 3 months?

Method (relative strength / sector rotation):

1. Map the asset's sector to its SPDR sector ETF (``_SECTOR_ETF_MAP``).
2. Compute the trailing ~3-month (90-day) total return of that sector ETF.
3. Compute the trailing ~3-month return of SPY (the SPX proxy).
4. ``passed = sector_return > spy_return``.

Returns are expressed as percentages: ``((last - first) / first) * 100`` over
the price window — identical to the upstream ``_calc_3mo_return``.

The threshold is *relative*: the sector must simply beat SPY. In the
``CheckResult`` the numeric ``threshold`` field carries the SPY 3-month return
(the bar the sector return is compared against); the descriptive label
("Sector outperforming SPX 3-month") is preserved in ``details``.

Upstream note: the original fetches sector-ETF and SPY price history through a
live ``DataClient``. nexus-core has no data client in the scoring context, so
this check reads precomputed returns (or raw price bars) from the
``ScoringContext`` and degrades to ``passed=None`` when neither is present.
"""

from __future__ import annotations

from typing import Any

from nexus_core.engine.scoring.checks import CheckResult, ScoringContext

# SPDR sector ETF map — keyed by lowercase sector name. Mirrors the upstream
# ``_SECTOR_ETF_MAP`` exactly (synonyms included).
SECTOR_ETF_MAP: dict[str, str] = {
    "technology": "XLK",
    "financial services": "XLF",
    "financials": "XLF",
    "healthcare": "XLV",
    "consumer cyclical": "XLY",
    "consumer discretionary": "XLY",
    "communication services": "XLC",
    "industrials": "XLI",
    "energy": "XLE",
    "consumer defensive": "XLP",
    "consumer staples": "XLP",
    "utilities": "XLU",
    "real estate": "XLRE",
    "basic materials": "XLB",
}

THRESHOLD_DESC = "Sector outperforming SPX 3-month"


def sector_etf_for(sector: str) -> str | None:
    """Return the SPDR sector ETF ticker for a sector name (case-insensitive)."""
    if not sector:
        return None
    return SECTOR_ETF_MAP.get(sector.strip().lower())


def compute_period_return(bars: list[dict[str, Any]]) -> float | None:
    """Compute percent return over a price window (faithful to ``_calc_3mo_return``).

    ``bars`` is an ordered list of price dicts (oldest first), each carrying a
    ``close`` (or ``c``) field. Return is ``((last - first) / first) * 100``.
    Returns ``None`` if there are fewer than two usable bars or the first close
    is non-positive.
    """
    if not bars or len(bars) < 2:
        return None

    def _close(bar: dict[str, Any]) -> float | None:
        raw = bar.get("close", bar.get("c"))
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    first_close = _close(bars[0])
    last_close = _close(bars[-1])
    if first_close is None or last_close is None or first_close <= 0:
        return None
    return ((last_close - first_close) / first_close) * 100.0


def _coerce_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class SectorTailwindCheck:
    """EMF Check #7: sector momentum (relative strength vs SPX, 3-month).

    Input resolution (first available wins), all read from the context:

    * Precomputed returns — ``sector_change`` / ``spy_change`` (percent),
      looked up in ``ctx.extra`` then ``ctx.fundamentals``.
    * Raw price windows — ``sector_prices`` / ``spy_prices`` (lists of price
      bars), from which the helper recomputes the 3-month returns.

    The sector name is read from ``ctx.fundamentals['sector']`` (or
    ``ctx.extra['sector']``) and mapped to a SPDR sector ETF, mirroring the
    upstream behaviour. When neither precomputed returns nor raw prices are
    available the check returns ``passed=None`` / ``signal="insufficient_data"``
    so it is safe to register before the upstream data plumbing exists.
    """

    def __init__(self, check_number: int = 7) -> None:
        self.check_number = check_number

    def _resolve_sector(self, ctx: ScoringContext) -> str:
        sector = ctx.fundamentals.get("sector") or ctx.extra.get("sector") or ""
        return str(sector)

    def _resolve_returns(self, ctx: ScoringContext) -> tuple[float | None, float | None]:
        # 1) Precomputed percent returns take priority.
        sector_return = _coerce_float(
            ctx.extra.get("sector_change", ctx.fundamentals.get("sector_change"))
        )
        spy_return = _coerce_float(ctx.extra.get("spy_change", ctx.fundamentals.get("spy_change")))
        if sector_return is not None and spy_return is not None:
            return sector_return, spy_return

        # 2) Fall back to recomputing from raw price windows.
        sector_prices = ctx.extra.get("sector_prices")
        spy_prices = ctx.extra.get("spy_prices")
        if isinstance(sector_prices, list) and isinstance(spy_prices, list):
            return (
                compute_period_return(sector_prices),
                compute_period_return(spy_prices),
            )
        return sector_return, spy_return

    def __call__(self, ctx: ScoringContext) -> CheckResult:
        sector = self._resolve_sector(ctx)
        sector_etf = sector_etf_for(sector)
        sector_return, spy_return = self._resolve_returns(ctx)

        details: dict[str, Any] = {
            "sector": sector,
            "sector_etf": sector_etf,
            "sector_change": sector_return,
            "spy_change": spy_return,
            "threshold_desc": THRESHOLD_DESC,
        }

        if sector_return is not None and spy_return is not None:
            passed = sector_return > spy_return
            if passed:
                signal = "green"
                interp = (
                    f"{sector or 'Sector'} outperforming SPX 3-month "
                    f"({sector_return:+.1f}% vs {spy_return:+.1f}%)"
                )
            else:
                signal = "red"
                interp = (
                    f"{sector or 'Sector'} underperforming SPX 3-month "
                    f"({sector_return:+.1f}% vs {spy_return:+.1f}%)"
                )
            return CheckResult(
                check_number=self.check_number,
                name="Sector Tailwind",
                value=sector_return,
                threshold=spy_return,
                passed=passed,
                signal=signal,
                interpretation=interp,
                details=details,
            )

        # Insufficient data — best-effort, never throw.
        if sector and sector_etf is None:
            interp = f"Sector '{sector}' not mapped to a sector ETF"
        elif sector:
            interp = f"Sector performance data unavailable for {sector}"
        else:
            interp = "Sector not identified"
        return CheckResult(
            check_number=self.check_number,
            name="Sector Tailwind",
            value=sector_return,
            threshold=spy_return,
            passed=None,
            signal="insufficient_data",
            interpretation=interp,
            details=details,
        )


__all__ = [
    "SECTOR_ETF_MAP",
    "THRESHOLD_DESC",
    "SectorTailwindCheck",
    "compute_period_return",
    "sector_etf_for",
]

