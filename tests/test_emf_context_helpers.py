# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Hermetic tests for the EMF context helpers.

No network. A fake market provider serves canned ``PriceBar`` history. Asserts
sector resolution, layer classification (MODEL_TICKERS + keyword + default +
UNCLASSIFIED), sector / SPY returns, and that ``populate_context`` fills the
exact ctx keys the Regime-Alignment, Sector-Tailwind, and Lambda checks read —
verified by then running those three checks live against the enriched context.
"""

from __future__ import annotations

from nexus_core.data.providers import PriceBar
from nexus_core.engine.scoring.checks import ScoringContext
from nexus_core.engine.scoring.emf.context_helpers import (
    UNCLASSIFIED,
    build_context_fields,
    compute_sector_return,
    compute_spy_return,
    layer_for,
    populate_context,
    sector_for_ticker,
)
from nexus_core.engine.scoring.emf.lambda_decay import LambdaCheck
from nexus_core.engine.scoring.emf.regime_alignment import RegimeAlignmentCheck
from nexus_core.engine.scoring.emf.sector_tailwind import SectorTailwindCheck


class FakeMarket:
    """Fake MarketDataProvider: serves canned price history per symbol.

    ``histories`` maps a symbol to a list of closes (oldest first); each close
    becomes a flat OHLCV ``PriceBar``. Unknown symbols return ``[]`` — exactly
    how the real providers degrade.
    """

    def __init__(self, histories: dict[str, list[float]]) -> None:
        self.histories = histories
        self.calls: list[tuple[str, int]] = []

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        self.calls.append((symbol, days))
        closes = self.histories.get(symbol)
        if closes is None:
            return []
        return [
            PriceBar(
                timestamp=f"2026-01-{i + 1:02d}T00:00:00+00:00",
                open=c,
                high=c,
                low=c,
                close=c,
                volume=1000.0,
            )
            for i, c in enumerate(closes)
        ]


class RaisingMarket:
    """Fake provider that raises — exercises the best-effort swallow path."""

    def get_price_history(
        self, symbol: str, *, days: int = 365, interval: str = "1d"
    ) -> list[PriceBar]:
        raise RuntimeError("boom")


class _Fund:
    """Object with ``.sector`` / ``.industry`` (pw-nexus fundamentals shape)."""

    def __init__(self, sector: str = "", industry: str = "") -> None:
        self.sector = sector
        self.industry = industry


# --- sector_for_ticker ------------------------------------------------------


def test_sector_for_ticker_from_dict() -> None:
    assert sector_for_ticker("NVDA", {"sector": "Technology"}) == "Technology"


def test_sector_for_ticker_from_object() -> None:
    assert sector_for_ticker("XOM", _Fund(sector="Energy")) == "Energy"


def test_sector_for_ticker_missing() -> None:
    assert sector_for_ticker("NVDA", {}) is None
    assert sector_for_ticker("NVDA", None) is None
    assert sector_for_ticker("NVDA", {"sector": ""}) is None


# --- layer_for: MODEL_TICKERS priority --------------------------------------


def test_layer_for_known_ticker_wins() -> None:
    # NVDA is L3 in MODEL_TICKERS even though its sector default would be L3 too;
    # CEG is L1; CRWD is L4. Ticker match takes priority over any sector signal.
    assert layer_for("NVDA") == "L3"
    assert layer_for("CEG") == "L1"
    assert layer_for("CRWD") == "L4"
    # Case-insensitive.
    assert layer_for("nvda") == "L3"


def test_layer_for_known_ticker_beats_conflicting_fundamentals() -> None:
    # CEG is L1 by ticker even if fundamentals say Technology (would be L3).
    assert layer_for("CEG", fundamentals={"sector": "Technology"}) == "L1"


# --- layer_for: keyword classification --------------------------------------


def test_layer_for_energy_sector_is_l1() -> None:
    assert layer_for("UNKN", fundamentals={"sector": "Energy"}) == "L1"


def test_layer_for_nuclear_industry_is_l1() -> None:
    assert layer_for("UNKN", fundamentals={"industry": "Nuclear Power Generation"}) == "L1"


def test_layer_for_utilities_is_l2() -> None:
    assert layer_for("UNKN", fundamentals={"sector": "Utilities"}) == "L2"


def test_layer_for_data_center_industry_is_l2() -> None:
    assert layer_for("UNKN", fundamentals={"industry": "Data Center REITs"}) == "L2"


def test_layer_for_semiconductor_is_l3() -> None:
    assert layer_for("UNKN", fundamentals={"industry": "Semiconductors"}) == "L3"


def test_layer_for_cyber_is_l4() -> None:
    assert layer_for("UNKN", fundamentals={"industry": "Cybersecurity Software"}) == "L4"


def test_layer_for_saas_is_l5() -> None:
    assert layer_for("UNKN", fundamentals={"industry": "Application Software"}) == "L5"


def test_layer_for_biotech_is_l6() -> None:
    assert layer_for("UNKN", fundamentals={"industry": "Biotechnology"}) == "L6"


# --- layer_for: sector defaults + unclassified ------------------------------


def test_layer_for_sector_default() -> None:
    # Healthcare with no specific industry keyword -> L6 default.
    assert layer_for("UNKN", fundamentals={"sector": "Healthcare"}) == "L6"
    assert layer_for("UNKN", fundamentals={"sector": "Financials"}) == "L4"


def test_layer_for_bare_sector_name() -> None:
    # No fundamentals: the bare token is treated as a sector name.
    assert layer_for("Energy") == "L1"
    assert layer_for("Technology") == "L3"


def test_layer_for_unclassified() -> None:
    assert layer_for("ZZZZ", fundamentals={"sector": "Crypto"}) == UNCLASSIFIED
    assert layer_for("", fundamentals={}) == UNCLASSIFIED


# --- D2-B: asset-class layer routing (crypto + sector/commodity ETFs) ---------


def test_layer_for_crypto() -> None:
    assert layer_for("BTC-USD") == "L1"  # Bitcoin — monetary foundation
    assert layer_for("ETH-USD") == "L2"  # Ethereum — settlement backbone
    assert layer_for("btc-usd") == "L1"  # case-insensitive


def test_layer_for_sector_and_commodity_etfs() -> None:
    assert layer_for("XLK") == "L3"  # technology
    assert layer_for("XLF") == "L4"  # financials
    assert layer_for("XLE") == "L1"  # energy
    assert layer_for("SLV") == "L1"  # silver


def test_layer_for_broad_market_etf_is_unclassified() -> None:
    # A diversified index has no single durability layer -> NOT APPLICABLE.
    assert layer_for("SPY") == UNCLASSIFIED
    assert layer_for("VTI") == UNCLASSIFIED


# --- compute_sector_return / compute_spy_return -----------------------------


def test_compute_sector_return_uses_etf_history() -> None:
    market = FakeMarket({"XLK": [100.0, 105.0, 110.0]})
    # ((110 - 100) / 100) * 100 == 10.0
    assert compute_sector_return(market, "Technology", days=90) == 10.0
    # The ETF, not the sector name, was requested, over the requested window.
    assert market.calls == [("XLK", 90)]


def test_compute_spy_return() -> None:
    market = FakeMarket({"SPY": [200.0, 210.0]})
    assert compute_spy_return(market, days=90) == 5.0
    assert market.calls == [("SPY", 90)]


def test_compute_sector_return_unmapped_sector() -> None:
    market = FakeMarket({"XLK": [100.0, 110.0]})
    assert compute_sector_return(market, "Crypto") is None
    assert market.calls == []  # never queried — sector unmapped


def test_compute_sector_return_no_market() -> None:
    assert compute_sector_return(None, "Technology") is None
    assert compute_spy_return(None) is None


def test_compute_sector_return_insufficient_history() -> None:
    market = FakeMarket({"XLK": [100.0]})  # one bar -> cannot compute
    assert compute_sector_return(market, "Technology") is None


def test_compute_sector_return_nonpositive_first_close() -> None:
    market = FakeMarket({"XLK": [0.0, 50.0]})
    assert compute_sector_return(market, "Technology") is None


def test_compute_sector_return_provider_raises_is_swallowed() -> None:
    assert compute_sector_return(RaisingMarket(), "Technology") is None
    assert compute_spy_return(RaisingMarket()) is None


# --- build_context_fields ---------------------------------------------------


def test_build_context_fields_full() -> None:
    market = FakeMarket({"XLK": [100.0, 112.0], "SPY": [100.0, 105.0]})
    fields = build_context_fields(
        "NVDA",
        {"sector": "Technology"},
        market=market,
        regime_code="GROWTH",
        days=90,
    )
    assert fields["code"] == "G"
    assert fields["sector"] == "Technology"
    assert fields["layer"] == "L3"
    assert fields["sector_change"] == 12.0
    assert fields["spy_change"] == 5.0


def test_build_context_fields_omits_unresolved() -> None:
    # No market, unknown sector, no regime -> only the layer (ticker match).
    fields = build_context_fields("CEG", {})
    assert fields == {"layer": "L1"}


def test_build_context_fields_returns_only_emitted_when_one_return_missing() -> None:
    # Sector mapped but SPY history absent -> neither return is emitted.
    market = FakeMarket({"XLK": [100.0, 110.0]})  # no SPY
    fields = build_context_fields("NVDA", {"sector": "Technology"}, market=market)
    assert "sector_change" not in fields
    assert "spy_change" not in fields
    assert fields["sector"] == "Technology"
    assert fields["layer"] == "L3"


def test_build_context_fields_unclassified_layer_omitted() -> None:
    fields = build_context_fields("ZZZZ", {"sector": "Crypto"})
    assert "layer" not in fields


# --- populate_context: the integration that matters -------------------------


def _bars(closes: list[float]) -> dict[str, list[float]]:
    return {"XLK": closes, "SPY": [100.0, 105.0]}


def test_populate_context_fills_keys_and_checks_go_live() -> None:
    market = FakeMarket(_bars([100.0, 120.0]))  # sector +20% vs SPY +5%
    ctx = ScoringContext(ticker="NVDA", fundamentals={"sector": "Technology"})

    returned = populate_context(ctx, market=market, regime_code="GROWTH", days=90)
    assert returned is ctx  # mutated in place, returned for chaining

    # Exact keys the three checks read are now present.
    assert ctx.regime["code"] == "G"
    assert ctx.extra["sector"] == "Technology"
    assert ctx.extra["layer"] == "L3"
    assert ctx.extra["sector_change"] == 20.0
    assert ctx.extra["spy_change"] == 5.0

    # Regime-Alignment now evaluates live: L3 in GROWTH carries 25% -> pass.
    ra = RegimeAlignmentCheck()(ctx)
    assert ra.passed is True
    assert ra.value == 25.0
    assert ra.signal == "GREEN"

    # Sector-Tailwind now evaluates live: +20% > +5% -> pass.
    st = SectorTailwindCheck()(ctx)
    assert st.passed is True
    assert st.value == 20.0
    assert st.threshold == 5.0
    assert st.details["sector_etf"] == "XLK"

    # Lambda now reads the layer from extra: NVDA -> λ 0.12 < L3 ceiling 0.20.
    la = LambdaCheck()(ctx)
    assert la.details["layer"] == "L3"
    assert la.passed is True
    assert la.value == 0.12


def test_populate_context_respects_existing_values() -> None:
    market = FakeMarket(_bars([100.0, 120.0]))
    ctx = ScoringContext(
        ticker="NVDA",
        fundamentals={"sector": "Technology"},
        regime={"code": "H"},  # caller-supplied regime must win
        extra={"layer": "L7", "sector_change": 1.0},  # caller-supplied must win
    )
    populate_context(ctx, market=market, regime_code="GROWTH")

    assert ctx.regime["code"] == "H"  # not overwritten
    assert ctx.extra["layer"] == "L7"  # not overwritten
    assert ctx.extra["sector_change"] == 1.0  # not overwritten
    # spy_change was absent -> it does get filled.
    assert ctx.extra["spy_change"] == 5.0


def test_populate_context_no_market_skips_returns_but_fills_rest() -> None:
    ctx = ScoringContext(ticker="CEG", fundamentals={"sector": "Energy"})
    populate_context(ctx, regime_code="HARD_ASSET")

    assert ctx.regime["code"] == "H"
    assert ctx.extra["sector"] == "Energy"
    assert ctx.extra["layer"] == "L1"  # CEG ticker match
    assert "sector_change" not in ctx.extra
    assert "spy_change" not in ctx.extra


def test_populate_context_unrecognized_regime_omits_code() -> None:
    ctx = ScoringContext(ticker="NVDA", fundamentals={"sector": "Technology"})
    populate_context(ctx, regime_code="NONSENSE")
    assert "code" not in ctx.regime


def test_populate_context_never_throws_on_garbage() -> None:
    ctx = ScoringContext(
        ticker="NVDA",
        fundamentals={"sector": object(), "industry": 123},  # type: ignore[dict-item]
    )
    # Must not raise; junk sector simply yields no sector / a layer fallback.
    populate_context(ctx, market=RaisingMarket(), regime_code=42)
    assert isinstance(ctx.extra, dict)


def test_populate_context_lambda_falls_back_to_sector_when_no_layer() -> None:
    # Unclassified layer is omitted; Lambda then estimates λ from the sector.
    market = FakeMarket(_bars([100.0, 120.0]))
    ctx = ScoringContext(ticker="ZZZZ", fundamentals={"sector": "Crypto"})
    populate_context(ctx, market=market, regime_code="GROWTH")
    assert "layer" not in ctx.extra
    # Crypto isn't in SECTOR_ETF_MAP, so no sector returns either.
    assert "sector_change" not in ctx.extra
