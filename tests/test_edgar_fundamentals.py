# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the SEC companyfacts fundamentals fetcher.

Hermetic — every request is served by an ``httpx.MockTransport`` handler; no
network, no API key. The companyfacts fixture is trimmed to the handful of
US-GAAP concepts the CROIC + F-Score checks consume, across two fiscal years,
and is also fed through the real ``CROICCheck`` / ``FScoreCheck`` to prove the
output dict lands on the exact keys those checks read.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from nexus_core.data.edgar.fundamentals import (
    SEC_USER_AGENT,
    _sic_to_sector,
    build_fundamentals,
    cik_for_ticker,
    fetch_company_facts,
    fetch_company_submissions,
)
from nexus_core.engine.scoring.checks import ScoringContext
from nexus_core.engine.scoring.emf.croic import CROICCheck
from nexus_core.engine.scoring.emf.fscore import FScoreCheck

# --- Fixtures ----------------------------------------------------------------

_TICKER_MAP: dict[str, Any] = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}


def _annual(fy: int, val: float, *, form: str = "10-K") -> dict[str, Any]:
    """One annual (FY) XBRL value entry."""
    return {"fy": fy, "fp": "FY", "form": form, "val": val, "filed": f"{fy + 1}-02-01"}


def _usd(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"units": {"USD": list(entries)}}


def _shares(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"units": {"shares": list(entries)}}


# Two fiscal years (2024 current, 2023 prior) chosen so the company:
#   CROIC: FCF = 110 - 10 = 100; invested capital = equity(500) + debt(200) = 700
#          -> 100/700 = 0.1429 (passes the check's 8% baseline, below 15% strong)
#   F-Score: strong fundamentals across most signals -> high score
_COMPANY_FACTS: dict[str, Any] = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Revenues": _usd(_annual(2024, 1000.0), _annual(2023, 900.0)),
            "NetIncomeLoss": _usd(_annual(2024, 120.0), _annual(2023, 80.0)),
            "GrossProfit": _usd(_annual(2024, 450.0), _annual(2023, 380.0)),
            "Assets": _usd(_annual(2024, 800.0), _annual(2023, 820.0)),
            "AssetsCurrent": _usd(_annual(2024, 300.0), _annual(2023, 250.0)),
            "LiabilitiesCurrent": _usd(_annual(2024, 150.0), _annual(2023, 160.0)),
            "LongTermDebt": _usd(_annual(2024, 200.0), _annual(2023, 260.0)),
            "StockholdersEquity": _usd(_annual(2024, 500.0), _annual(2023, 400.0)),
            "CommonStockSharesOutstanding": _shares(
                _annual(2024, 1_000.0), _annual(2023, 1_010.0)
            ),
            "NetCashProvidedByUsedInOperatingActivities": _usd(
                _annual(2024, 110.0), _annual(2023, 70.0)
            ),
            "PaymentsToAcquirePropertyPlantAndEquipment": _usd(
                _annual(2024, 10.0), _annual(2023, 12.0)
            ),
        }
    },
}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _full_handler(request: httpx.Request) -> httpx.Response:
    """Serve both the ticker map and the companyfacts payload."""
    url = str(request.url)
    # SEC requires a descriptive User-Agent on every request.
    assert request.headers.get("User-Agent") == SEC_USER_AGENT
    if "company_tickers.json" in url:
        return httpx.Response(200, json=_TICKER_MAP)
    if "companyfacts/CIK0000320193.json" in url:
        return httpx.Response(200, json=_COMPANY_FACTS)
    return httpx.Response(404, json={"error": "not found"})


# --- CIK lookup --------------------------------------------------------------


def test_cik_for_ticker_resolves() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "company_tickers.json" in str(request.url)
        return httpx.Response(200, json=_TICKER_MAP)

    assert cik_for_ticker("AAPL", client=_client(handler)) == 320193


def test_cik_for_ticker_case_insensitive_and_class_normalised() -> None:
    payload = {"0": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire"}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    # Lowercase and dot-notation both resolve to the SEC dash form.
    assert cik_for_ticker("brk.b", client=_client(handler)) == 1067983


def test_cik_for_ticker_unknown_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_TICKER_MAP)

    assert cik_for_ticker("NOPE", client=_client(handler)) is None


def test_cik_for_ticker_http_error_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    assert cik_for_ticker("AAPL", client=_client(handler)) is None


# --- companyfacts fetch ------------------------------------------------------


def test_fetch_company_facts_pads_cik() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # 320193 must be zero-padded to 10 digits in the URL.
        assert "companyfacts/CIK0000320193.json" in str(request.url)
        return httpx.Response(200, json=_COMPANY_FACTS)

    facts = fetch_company_facts(320193, client=_client(handler))
    assert facts is not None
    assert facts["entityName"] == "Apple Inc."


def test_fetch_company_facts_404_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "no xbrl"})

    assert fetch_company_facts(999, client=_client(handler)) is None


# --- build_fundamentals: shape + precomputed scalars -------------------------


def test_build_fundamentals_populates_expected_keys() -> None:
    fund = build_fundamentals("AAPL", client=_client(_full_handler))
    assert fund is not None

    # Diagnostic keys.
    assert fund["ticker"] == "AAPL"
    assert fund["cik"] == 320193
    assert fund["fiscal_years"] == [2024, 2023]

    # Precomputed scalars the checks read first.
    # CROIC = (110 - 10) / (500 + 200) = 100/700 = 0.1429
    assert fund["croic"] == pytest.approx(0.1429, abs=1e-4)
    assert isinstance(fund["f_score"], int)
    assert 0 <= fund["f_score"] <= 9

    # Raw statement lists, most-recent-first, with the field names the checks accept.
    inc = fund["income_statements"]
    bs = fund["balance_sheets"]
    cf = fund["cash_flows"]
    assert [r["fiscal_year"] for r in inc] == [2024, 2023]
    assert inc[0]["revenue"] == 1000.0
    assert inc[0]["net_income"] == 120.0
    assert inc[0]["gross_profit"] == 450.0
    assert bs[0]["total_stockholders_equity"] == 500.0
    assert bs[0]["total_debt"] == 200.0
    assert bs[0]["long_term_debt"] == 200.0
    assert bs[0]["shares_outstanding"] == 1_000.0
    assert cf[0]["operating_cash_flow"] == 110.0
    assert cf[0]["capital_expenditure"] == 10.0


def test_build_fundamentals_gross_profit_derived_when_absent() -> None:
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": _usd(_annual(2024, 1000.0), _annual(2023, 900.0)),
                "CostOfGoodsAndServicesSold": _usd(
                    _annual(2024, 600.0), _annual(2023, 520.0)
                ),
                "Assets": _usd(_annual(2024, 800.0), _annual(2023, 820.0)),
                "NetIncomeLoss": _usd(_annual(2024, 120.0), _annual(2023, 80.0)),
                "StockholdersEquity": _usd(_annual(2024, 500.0), _annual(2023, 400.0)),
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "company_tickers.json" in str(request.url):
            return httpx.Response(200, json=_TICKER_MAP)
        return httpx.Response(200, json=facts)

    fund = build_fundamentals("AAPL", client=_client(handler))
    assert fund is not None
    # gross_profit derived as revenue - cost_of_revenue = 1000 - 600 = 400.
    assert fund["income_statements"][0]["gross_profit"] == 400.0


# --- build_fundamentals feeds the real EMF checks ----------------------------


def test_output_drives_croic_check() -> None:
    fund = build_fundamentals("AAPL", client=_client(_full_handler))
    assert fund is not None
    result = CROICCheck()(ScoringContext(ticker="AAPL", fundamentals=fund))
    # 0.1429 > 0.08 baseline -> pass; below 0.15 -> "solid".
    assert result.value == pytest.approx(0.1429, abs=1e-4)
    assert result.passed is True
    assert result.signal == "solid"


def test_output_drives_fscore_check() -> None:
    fund = build_fundamentals("AAPL", client=_client(_full_handler))
    assert fund is not None
    result = FScoreCheck()(ScoringContext(ticker="AAPL", fundamentals=fund))
    # Precomputed scalar is read first; strong fundamentals -> >= threshold.
    assert result.value is not None
    assert result.passed is True
    assert result.value >= float(FScoreCheck().threshold)


def test_croic_check_recomputes_from_raw_when_scalar_missing() -> None:
    """The check must still work if only the raw statement lists survive."""
    fund = build_fundamentals("AAPL", client=_client(_full_handler))
    assert fund is not None
    fund.pop("croic")  # force the raw-statement compute path in croic.py
    result = CROICCheck()(ScoringContext(ticker="AAPL", fundamentals=fund))
    assert result.value == pytest.approx(0.1429, abs=1e-4)
    assert result.passed is True


# --- error paths -------------------------------------------------------------


def test_build_fundamentals_unknown_ticker_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_TICKER_MAP)

    assert build_fundamentals("NOPE", client=_client(handler)) is None


def test_build_fundamentals_no_xbrl_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "company_tickers.json" in str(request.url):
            return httpx.Response(200, json=_TICKER_MAP)
        return httpx.Response(404, json={"error": "no xbrl"})

    assert build_fundamentals("AAPL", client=_client(handler)) is None


def test_build_fundamentals_empty_gaap_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "company_tickers.json" in str(request.url):
            return httpx.Response(200, json=_TICKER_MAP)
        return httpx.Response(200, json={"facts": {}})

    assert build_fundamentals("AAPL", client=_client(handler)) is None


@pytest.mark.parametrize(
    ("sic", "sector"),
    [
        (3571, "technology"),  # electronic computers (AAPL)
        (3674, "technology"),  # semiconductors
        (7372, "technology"),  # prepackaged software
        (2834, "healthcare"),  # pharmaceutical preparations
        (3841, "healthcare"),  # surgical/medical instruments
        (1311, "energy"),  # crude petroleum & natural gas
        (6021, "financials"),  # national commercial banks
        (6798, "real estate"),  # REITs
        (5812, "consumer cyclical"),  # eating places
        (4911, "utilities"),  # electric services
        (3711, "consumer cyclical"),  # motor vehicles
        (3721, "industrials"),  # aircraft
        (None, None),
        (99, None),  # unmapped
    ],
)
def test_sic_to_sector(sic: int | None, sector: str | None) -> None:
    assert _sic_to_sector(sic) == sector


def test_fetch_company_submissions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "submissions/CIK0000320193.json" in str(request.url)
        return httpx.Response(200, json={"sic": "3571", "sicDescription": "Electronic Computers"})

    subs = fetch_company_submissions(320193, client=_client(handler))
    assert subs is not None
    assert subs["sic"] == "3571"


def _full_handler_with_submissions(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "company_tickers.json" in url:
        return httpx.Response(200, json=_TICKER_MAP)
    if "companyfacts/CIK0000320193.json" in url:
        return httpx.Response(200, json=_COMPANY_FACTS)
    if "submissions/CIK0000320193.json" in url:
        return httpx.Response(
            200, json={"sic": "3571", "sicDescription": "Electronic Computers"}
        )
    return httpx.Response(404, json={"error": "not found"})


def test_build_fundamentals_populates_sector() -> None:
    fund = build_fundamentals("AAPL", client=_client(_full_handler_with_submissions))
    assert fund is not None
    assert fund["sector"] == "technology"
    assert fund["industry"] == "Electronic Computers"
    assert fund["sic"] == 3571


def test_build_fundamentals_sector_none_when_submissions_unavailable() -> None:
    # _full_handler 404s the submissions URL → sector degrades to None, no break.
    fund = build_fundamentals("AAPL", client=_client(_full_handler))
    assert fund is not None
    assert fund["sector"] is None
