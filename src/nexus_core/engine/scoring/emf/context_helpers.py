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

from typing import Any, NamedTuple, Protocol, runtime_checkable

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

# Asset-class layer routing (D2-B) for instruments that are not individual
# operating companies. Broad-market ETFs (SPY/VOO/VTI/QQQ/IWM/DIA) are
# DELIBERATELY ABSENT — a diversified index has no single durability layer, so
# they fall through to UNCLASSIFIED (NOT APPLICABLE), which is the honest result.
CRYPTO_LAYER: dict[str, str] = {
    "BTC-USD": "L1",  # Bitcoin — monetary foundation (matches IBIT already in L1)
    "BTC": "L1",
    "ETH-USD": "L2",  # Ethereum — settlement backbone
    "ETH": "L2",
}
SECTOR_ETF_LAYER: dict[str, str] = {
    "XLK": "L3",  # technology
    "XLF": "L4",  # financials
    "XLV": "L6",  # healthcare
    "XLE": "L1",  # energy
    "XLB": "L1",  # basic materials
    "XLU": "L2",  # utilities
    "XLI": "L2",  # industrials
    "XLRE": "L2",  # real estate
    "XLP": "L5",  # consumer defensive
    "XLY": "L5",  # consumer cyclical
    "XLC": "L5",  # communication services
    "GLD": "L1",  # gold (also in MODEL_TICKERS L1)
    "SLV": "L1",  # silver
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


class LayerClassification(NamedTuple):
    """A layer assignment plus *why* the classifier landed there.

    Attributes:
        layer: Short code (``"L1"``..``"L7"``) or :data:`UNCLASSIFIED`.
        source: Which rule in the priority order produced the layer — one of
            ``ticker_map`` / ``asset_class_crypto`` / ``asset_class_sector_etf``
            / ``sector_industry_keyword`` / ``sector_default`` /
            ``unclassified``.
        matched_on: The token the matching rule fired on (the ticker, the
            sector name, or the ``industry:``/``sector:``-prefixed keyword), or
            ``None`` when nothing matched.
    """

    layer: str
    source: str
    matched_on: str | None


# Sector / industry keyword rules, in the exact priority order the upstream
# classifier applies them. Each entry is (layer, sector names, industry
# keywords) — a sector-name hit or an industry-keyword substring hit assigns
# the layer. Data-driven so the classification and its provenance can never
# drift apart.
_KEYWORD_RULES: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("L1", ("energy", "basic materials"), ("nuclear",)),
    ("L2", ("utilities",), ("data center", "infrastructure", "water")),
    ("L3", (), ("semiconductor", "chip")),
    ("L4", (), ("security", "cyber", "defense")),
    ("L5", (), ("software", "saas", "application", "e-commerce")),
    ("L6", (), ("biotech", "space", "quantum")),
)


def classify_layer(sector_or_ticker: str | None, *, fundamentals: Any = None) -> LayerClassification:
    """Classify into an EMF durability layer, reporting the deciding rule.

    The single implementation of the layer priority order (see :func:`layer_for`,
    which returns only the layer). Carrying the deciding rule out with the layer
    is what lets the public surfaces explain *why* an asset landed where it did.
    """
    token = _clean_str(sector_or_ticker)

    # 1. Known-ticker exact match (case-insensitive).
    if token:
        upper = token.upper()
        hit = _TICKER_TO_LAYER.get(upper)
        if hit is not None:
            return LayerClassification(hit, "ticker_map", upper)
        # 1b. Asset-class routing (D2-B): crypto + sector/commodity ETFs that
        # aren't individual operating companies. Broad-market ETFs are absent
        # here, so they continue to UNCLASSIFIED (NOT APPLICABLE).
        crypto_layer = CRYPTO_LAYER.get(upper)
        if crypto_layer is not None:
            return LayerClassification(crypto_layer, "asset_class_crypto", upper)
        etf_layer = SECTOR_ETF_LAYER.get(upper)
        if etf_layer is not None:
            return LayerClassification(etf_layer, "asset_class_sector_etf", upper)

    # Sector / industry come from fundamentals when present; otherwise treat
    # the bare token as a sector name (so ``layer_for("Energy")`` works).
    sector = _clean_str(_attr_or_key(fundamentals, "sector")) or (
        token if fundamentals is None else ""
    )
    industry = _clean_str(_attr_or_key(fundamentals, "industry"))
    sector_l = sector.lower()
    industry_l = industry.lower()

    # 2. Sector / industry keyword classification (order matters, per upstream).
    for layer, sectors, keywords in _KEYWORD_RULES:
        if sector_l in sectors:
            return LayerClassification(layer, "sector_industry_keyword", f"sector:{sector_l}")
        for keyword in keywords:
            if keyword in industry_l:
                return LayerClassification(
                    layer, "sector_industry_keyword", f"industry:{keyword}"
                )

    # 3. Matched a sector but no specific keyword — use the sector default.
    if sector_l:
        default = SECTOR_LAYER_DEFAULTS.get(sector_l)
        if default is not None:
            return LayerClassification(default, "sector_default", sector_l)

    # 4. No positive match.
    return LayerClassification(UNCLASSIFIED, "unclassified", None)


def layer_for(sector_or_ticker: str | None, *, fundamentals: Any = None) -> str:
    """Classify a ticker (or sector) into an EMF durability layer short code.

    Faithful port of ``PortfolioEngine._classify_layer`` priority order:

    1. ``MODEL_TICKERS`` exact ticker match.
    1b. Asset-class routing (D2-B): crypto (``BTC-USD``->L1, ``ETH-USD``->L2)
        and sector/commodity ETFs (``XLK``->L3, ``GLD``->L1, ...). Broad-market
        ETFs are intentionally not mapped, so they fall to ``UNCLASSIFIED``.
    2. Sector / industry keyword classification (from ``fundamentals``).
    3. ``SECTOR_LAYER_DEFAULTS`` for a matched-but-unspecific sector.
    4. ``UNCLASSIFIED`` — never a silent L5 default (emf-canonical §5.2).

    Returns a short code (``"L1"``..``"L7"``) understood by *both* consumers:
    ``normalize_layer`` (Regime-Alignment) and ``LAYER_DECAY_THRESHOLDS``
    (Lambda). The argument may be a ticker or a sector name; when it is a
    sector and no ``fundamentals`` are given, the sector is used directly for
    keyword / default classification.

    Thin wrapper over :func:`classify_layer` — same rules, same result, without
    the provenance.
    """
    return classify_layer(sector_or_ticker, fundamentals=fundamentals).layer


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
    "CRYPTO_LAYER",
    "DEFAULT_RETURN_DAYS",
    "MODEL_TICKERS",
    "SECTOR_ETF_LAYER",
    "SECTOR_LAYER_DEFAULTS",
    "SPY_SYMBOL",
    "UNCLASSIFIED",
    "LayerClassification",
    "build_context_fields",
    "classify_layer",
    "compute_sector_return",
    "compute_spy_return",
    "layer_for",
    "populate_context",
    "sector_for_ticker",
]
