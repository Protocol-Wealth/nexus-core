# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""EMF context helpers — sector / layer / sector-return enrichment.

The Regime-Alignment (Check 6), Sector-Tailwind (Check 7), and Lambda (Check 4)
checks all degrade to ``passed=None`` until their supporting context is filled
in. This module produces exactly the ``ScoringContext`` fields those three
checks read, so they evaluate live instead of reporting ``insufficient_data``.

What each consumer reads (verified against the check modules):

* :class:`~nexus_core.engine.scoring.emf.regime_alignment.RegimeAlignmentCheck`
  reads the regime code from ``ctx.regime`` / ``ctx.extra`` (``code`` /
  ``regime`` / ``regime_code`` / ``current_regime``) and the durability layer
  from ``ctx.fundamentals`` / ``ctx.extra`` (``layer`` / ``layer_assignment`` /
  ``emf_layer``). Both are passed through ``normalize_regime`` /
  ``normalize_layer``, so a short layer code such as ``"L3"`` resolves fine.
* :class:`~nexus_core.engine.scoring.emf.sector_tailwind.SectorTailwindCheck`
  reads ``sector`` and the precomputed percent returns ``sector_change`` /
  ``spy_change`` (or raw ``sector_prices`` / ``spy_prices``) from ``ctx.extra``
  / ``ctx.fundamentals``.
* :class:`~nexus_core.engine.scoring.emf.lambda_decay.LambdaCheck`
  reads the durability layer from ``ctx.extra["layer"]`` / ``ctx.fundamentals
  ["layer"]`` (upper-cased, looked up in ``LAYER_DECAY_THRESHOLDS`` — i.e. the
  short codes ``L1``..``L7``) plus ``sector`` / ``industry`` for the λ estimate.

The single layer value this module emits is the **short code** (``"L3"``):
``normalize_layer("L3")`` resolves to ``L3_engine`` for Regime-Alignment, and
``LAYER_DECAY_THRESHOLDS["L3"]`` resolves for Lambda. One value, both checks.

Faithful port of the layer + sector-ETF + 3-month-return logic in pw-nexus
(``app/engine/portfolio_engine.py``): ``_classify_layer``, ``MODEL_TICKERS``,
``_SECTOR_ETF_MAP``, ``_calc_3mo_return``.

Best-effort throughout: missing/garbage data yields ``None`` / an empty dict
and never raises. All outputs are for educational and research purposes only —
not individualized investment advice.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ....data.providers import PriceBar
from ..checks import ScoringContext
from .lambda_decay import LAYER_DECAY_THRESHOLDS
from .regime_alignment import normalize_regime
from .sector_tailwind import sector_etf_for

# ---------------------------------------------------------------------------
# Known single-stock / ETF layer assignments.
# Ported verbatim from portfolio_engine.MODEL_TICKERS. Keyed by short layer
# code (L1..L7); values are uppercase tickers.
# ---------------------------------------------------------------------------
MODEL_TICKERS: dict[str, tuple[str, ...]] = {
    "L1": ("CEG", "VST", "NRG", "NUKZ", "GRID", "IBIT", "GLD", "ASML"),
    "L2": (
        "NEE", "DUK", "SO", "EQIX", "DLR", "AWK", "WMB", "LIN", "ETN", "PWR",
        "HUBB", "AGX", "POWL", "GEV", "FERG", "EME", "LRCX", "AMAT", "AVGO", "CCJ",
    ),
    "L3": (
        "SMH", "NVDA", "AMD", "TSM", "VRT", "VICR", "MU", "CRDO", "MRVL",
        "MPWR", "STRL", "IESC", "FIX",
    ),
    "L4": ("CRWD", "PANW", "PLTR", "LMT", "RTX", "SNOW", "ZS"),
    "L5": ("MSFT", "CRM", "NOW", "ADBE", "DDOG", "BE"),
    "L6": ("RKLB", "LUNR", "ASTS", "IONQ", "SMR"),
    "L7": ("VIXY", "BIL", "SGOV", "OKLO"),
}

# Reverse index: ticker -> short layer code (built once at import).
_TICKER_TO_LAYER: dict[str, str] = {
    ticker: layer for layer, tickers in MODEL_TICKERS.items() for ticker in tickers
}

# Sector -> default layer when no keyword matches (ported from
# portfolio_engine._classify_layer's ``sector_layer_defaults``). Keyed lower.
SECTOR_LAYER_DEFAULTS: dict[str, str] = {
    "technology": "L3",
    "healthcare": "L6",
    "financials": "L4",
    "consumer cyclical": "L5",
    "consumer defensive": "L5",
    "industrials": "L2",
    "communication services": "L5",
    "real estate": "L2",
}

#: Returned when a layer cannot be positively classified (never a silent L5
#: default, per emf-canonical §5.2). ``normalize_layer`` rejects this, so the
#: downstream checks correctly stay at ``insufficient_data``.
UNCLASSIFIED = "UNCLASSIFIED"

#: SPX proxy whose trailing return is the bar Sector-Tailwind compares against.
SPY_SYMBOL = "SPY"

#: Default trailing window for the sector-rotation return (~3 months).
DEFAULT_RETURN_DAYS = 90


@runtime_checkable
class _HistoryProvider(Protocol):
    """The slice of ``MarketDataProvider`` this module needs (price history)."""

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:  # pragma: no cover - protocol
        ...


def _attr_or_key(source: Any, name: str) -> Any:
    """Read ``name`` from a dict-like or attribute-bearing object, else ``None``.

    pw-nexus fundamentals are dataclass-ish objects (``.sector``); nexus-core
    contexts carry plain dicts. Support both so callers don't have to adapt.
    """
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(name)
    return getattr(source, name, None)


def _clean_str(value: Any) -> str:
    """Coerce a value to a stripped string ('' for None/empty/non-string)."""
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:  # pragma: no cover - defensive
        return ""


def sector_for_ticker(ticker: str | None, fundamentals: Any = None) -> str | None:
    """Resolve a GICS-style sector name for ``ticker``.

    Best-effort: reads ``sector`` from ``fundamentals`` (a dict or an object
    exposing ``.sector``). Returns ``None`` when no sector is available — the
    ticker argument is accepted for symmetry / future ticker-keyed maps but is
    not currently used as a fallback (mirrors pw-nexus, which only has the
    fundamentals-sourced sector here).
    """
    sector = _clean_str(_attr_or_key(fundamentals, "sector"))
    return sector or None


def layer_for(sector_or_ticker: str | None, *, fundamentals: Any = None) -> str:
    """Classify a ticker (or sector) into an EMF durability layer short code.

    Faithful port of ``PortfolioEngine._classify_layer`` priority order:

    1. ``MODEL_TICKERS`` exact ticker match.
    2. Sector / industry keyword classification (from ``fundamentals``).
    3. ``SECTOR_LAYER_DEFAULTS`` for a matched-but-unspecific sector.
    4. ``UNCLASSIFIED`` — never a silent L5 default (emf-canonical §5.2).

    Returns a short code (``"L1"``..``"L7"``) understood by *both* consumers:
    ``normalize_layer`` (Regime-Alignment) and ``LAYER_DECAY_THRESHOLDS``
    (Lambda). The argument may be a ticker or a sector name; when it is a
    sector and no ``fundamentals`` are given, the sector is used directly for
    keyword / default classification.
    """
    token = _clean_str(sector_or_ticker)

    # 1. Known-ticker exact match (case-insensitive).
    if token:
        hit = _TICKER_TO_LAYER.get(token.upper())
        if hit is not None:
            return hit

    # Sector / industry come from fundamentals when present; otherwise treat
    # the bare token as a sector name (so ``layer_for("Energy")`` works).
    sector = _clean_str(_attr_or_key(fundamentals, "sector")) or (
        token if fundamentals is None else ""
    )
    industry = _clean_str(_attr_or_key(fundamentals, "industry"))
    sector_l = sector.lower()
    industry_l = industry.lower()

    # 2. Sector / industry keyword classification (order matters, per upstream).
    if sector_l in ("energy", "basic materials") or "nuclear" in industry_l:
        return "L1"
    if sector_l == "utilities" or any(
        kw in industry_l for kw in ("data center", "infrastructure", "water")
    ):
        return "L2"
    if "semiconductor" in industry_l or "chip" in industry_l:
        return "L3"
    if any(kw in industry_l for kw in ("security", "cyber", "defense")):
        return "L4"
    if any(kw in industry_l for kw in ("software", "saas", "application", "e-commerce")):
        return "L5"
    if any(kw in industry_l for kw in ("biotech", "space", "quantum")):
        return "L6"

    # 3. Matched a sector but no specific keyword — use the sector default.
    if sector_l:
        default = SECTOR_LAYER_DEFAULTS.get(sector_l)
        if default is not None:
            return default

    # 4. No positive match.
    return UNCLASSIFIED


def _bars_period_return(bars: list[PriceBar]) -> float | None:
    """Percent return over a ``PriceBar`` window (faithful to ``_calc_3mo_return``).

    ``((last.close - first.close) / first.close) * 100``. Returns ``None`` for
    fewer than two bars or a non-positive first close.
    """
    if not bars or len(bars) < 2:
        return None
    first_close = float(bars[0].close)
    last_close = float(bars[-1].close)
    if first_close > 0:
        return ((last_close - first_close) / first_close) * 100.0
    return None


def compute_sector_return(
    market: _HistoryProvider | None,
    sector: str | None,
    *,
    days: int = DEFAULT_RETURN_DAYS,
) -> float | None:
    """Trailing ~3-month percent return of ``sector``'s SPDR ETF.

    Maps ``sector`` to its sector ETF (``sector_etf_for``), pulls the trailing
    ``days`` of price history via ``market.get_price_history``, and computes the
    period return. Best-effort: returns ``None`` when the market provider is
    absent, the sector is unmapped, history is too short, or the provider
    raises.
    """
    if market is None:
        return None
    etf = sector_etf_for(_clean_str(sector))
    if etf is None:
        return None
    try:
        bars = market.get_price_history(etf, days=days)
    except Exception:
        return None
    return _bars_period_return(bars)


def compute_spy_return(
    market: _HistoryProvider | None,
    *,
    days: int = DEFAULT_RETURN_DAYS,
) -> float | None:
    """Trailing ~3-month percent return of SPY (the SPX proxy bar)."""
    if market is None:
        return None
    try:
        bars = market.get_price_history(SPY_SYMBOL, days=days)
    except Exception:
        return None
    return _bars_period_return(bars)


def build_context_fields(
    ticker: str | None,
    fundamentals: Any = None,
    *,
    market: _HistoryProvider | None = None,
    regime_code: Any = None,
    days: int = DEFAULT_RETURN_DAYS,
) -> dict[str, Any]:
    """Compute the enrichment fields the three checks read, as a plain dict.

    The returned dict carries only the keys that could be resolved (best-effort
    — absent data is simply omitted so the relevant check stays at
    ``insufficient_data`` rather than receiving ``None`` it must special-case):

    * ``code`` — normalized regime single-letter code (Regime-Alignment).
    * ``layer`` — short durability-layer code, omitted when ``UNCLASSIFIED``
      (Regime-Alignment + Lambda).
    * ``sector`` — GICS sector name (Sector-Tailwind + Lambda λ estimate).
    * ``sector_change`` / ``spy_change`` — trailing ~3-month percent returns
      (Sector-Tailwind). Both are emitted only when *both* resolve, since the
      check needs the pair to compare.

    Suitable for ``ctx.extra.update(build_context_fields(...))``. The ``layer``
    short code is keyed for both ``ctx.extra`` (Lambda reads ``extra['layer']``
    first) and would satisfy Regime-Alignment's ``extra['layer_assignment']``
    fallback — emitting it under ``layer`` covers both, since Regime-Alignment
    also checks ``layer``.
    """
    fields: dict[str, Any] = {}

    code = normalize_regime(regime_code)
    if code is not None:
        fields["code"] = code

    sector = sector_for_ticker(ticker, fundamentals)
    if sector is not None:
        fields["sector"] = sector

    layer = layer_for(ticker, fundamentals=fundamentals)
    if layer != UNCLASSIFIED and layer in LAYER_DECAY_THRESHOLDS:
        fields["layer"] = layer

    sector_change = compute_sector_return(market, sector, days=days)
    spy_change = compute_spy_return(market, days=days)
    if sector_change is not None and spy_change is not None:
        fields["sector_change"] = sector_change
        fields["spy_change"] = spy_change

    return fields


def populate_context(
    ctx: ScoringContext,
    *,
    market: _HistoryProvider | None = None,
    regime_code: Any = None,
    days: int = DEFAULT_RETURN_DAYS,
) -> ScoringContext:
    """Fill ``ctx`` in place with the fields the three checks read, then return it.

    Regime code is written to ``ctx.regime['code']`` (the primary location
    Regime-Alignment checks). ``sector`` / ``layer`` / ``sector_change`` /
    ``spy_change`` go to ``ctx.extra`` — where Lambda reads ``layer`` first and
    Sector-Tailwind reads ``sector`` / returns first. Existing values are not
    overwritten (caller-supplied context wins). Best-effort: only resolved
    fields are written.

    Args:
        ctx: The context to enrich (mutated in place).
        market: Price-history provider for the sector / SPY returns. When
            ``None``, the return fields are skipped.
        regime_code: Current regime (any spelling ``normalize_regime`` accepts).
        days: Trailing window for the sector-rotation returns.
    """
    fundamentals = ctx.fundamentals or {}
    fields = build_context_fields(
        ctx.ticker,
        fundamentals,
        market=market,
        regime_code=regime_code,
        days=days,
    )

    code = fields.pop("code", None)
    if code is not None and not ctx.regime.get("code"):
        ctx.regime["code"] = code

    for key, value in fields.items():
        if ctx.extra.get(key) in (None, ""):
            ctx.extra[key] = value

    return ctx


__all__ = [
    "DEFAULT_RETURN_DAYS",
    "MODEL_TICKERS",
    "SECTOR_LAYER_DEFAULTS",
    "SPY_SYMBOL",
    "UNCLASSIFIED",
    "build_context_fields",
    "compute_sector_return",
    "compute_spy_return",
    "layer_for",
    "populate_context",
    "sector_for_ticker",
]
