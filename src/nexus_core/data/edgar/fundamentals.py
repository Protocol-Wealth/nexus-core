# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""SEC companyfacts fundamentals fetcher for the EMF CROIC + F-Score checks.

Turns a ticker into the ``fundamentals`` dict consumed by the EMF scoring
checks (:mod:`nexus_core.engine.scoring.emf.croic` and
:mod:`...emf.fscore`), computed entirely from the **free** SEC XBRL
``companyfacts`` API — no API key required.

Pipeline
--------
1. :func:`cik_for_ticker` — resolve a ticker to its CIK via the public
   ``company_tickers.json`` map.
2. :func:`fetch_company_facts` — pull the full XBRL fact set from
   ``data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json``.
3. :func:`build_fundamentals` — extract per-fiscal-year US-GAAP concepts into
   most-recent-first statement lists, precompute ``croic`` and ``f_score``, and
   return the dict the checks read.

Methodology is a faithful port of the private pw-nexus engine
(``app/services/sec_edgar.py`` for the companyfacts extraction + CROIC /
Piotroski computation, ``app/engine/sec_edgar.py`` for the XBRL tag fallback
chains). The two scoring checks accept *either* a precomputed scalar
(``croic`` / ``f_score``) *or* raw statement lists, so this builder populates
both for redundancy.

SEC fair-use policy **requires** a descriptive ``User-Agent`` on every request.
All requests in this module send :data:`SEC_USER_AGENT`.

Best-effort throughout: any missing data, network failure, or malformed
payload degrades to ``None`` / empty rather than raising. All outputs are
educational / analytical, derived from public SEC filings.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

#: SEC fair-use policy requires a descriptive User-Agent identifying the caller.
SEC_USER_AGENT = "nexus-core research@protocolwealthllc.com"

_HEADERS: dict[str, str] = {
    "User-Agent": SEC_USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Accept": "application/json",
}

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

_DEFAULT_TIMEOUT = 15.0

#: CROIC pass threshold used by the precomputed convenience flag. The nexus-core
#: ``CROICCheck`` re-evaluates its own threshold (8% baseline); this mirrors the
#: pw-nexus ``compute_croic`` 15% "strong" gate purely for the ``croic_passes``
#: annotation and is never used by the check itself.
_CROIC_STRONG_THRESHOLD = 0.15

#: Piotroski pass threshold (informational annotation only — the check owns its).
_FSCORE_THRESHOLD = 6


# =============================================================================
# US-GAAP XBRL concept fallback chains (ported from pw-nexus ALL_TAGS / XBRL_*)
# =============================================================================

#: Each logical metric maps to an ordered list of XBRL concept names to try,
#: with the unit key to read from. First present concept wins.
_TAGS: dict[str, tuple[tuple[str, ...], str]] = {
    "revenue": (
        (
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
        ),
        "USD",
    ),
    "net_income": (
        (
            "NetIncomeLoss",
            "ProfitLoss",
            "NetIncomeLossAvailableToCommonStockholdersBasic",
        ),
        "USD",
    ),
    "gross_profit": (("GrossProfit",), "USD"),
    "cost_of_revenue": (
        ("CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"),
        "USD",
    ),
    "total_assets": (("Assets",), "USD"),
    "total_current_assets": (("AssetsCurrent",), "USD"),
    "total_current_liabilities": (("LiabilitiesCurrent",), "USD"),
    "long_term_debt": (
        (
            "LongTermDebt",
            "LongTermDebtNoncurrent",
            "LongTermDebtAndCapitalLeaseObligations",
        ),
        "USD",
    ),
    "short_term_borrowings": (
        ("ShortTermBorrowings", "LongTermDebtCurrent", "DebtCurrent"),
        "USD",
    ),
    "total_stockholders_equity": (
        (
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ),
        "USD",
    ),
    "shares_outstanding": (
        (
            "CommonStockSharesOutstanding",
            "EntityCommonStockSharesOutstanding",
            "WeightedAverageNumberOfSharesOutstandingBasic",
            "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
            "CommonStockSharesIssued",
        ),
        "shares",
    ),
    "operating_cash_flow": (
        (
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ),
        "USD",
    ),
    "capital_expenditure": (
        (
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
        ),
        "USD",
    ),
}

#: 10-K plus the foreign-filer equivalent 20-F.
_ANNUAL_FORMS = frozenset({"10-K", "20-F"})


# =============================================================================
# CIK resolution
# =============================================================================


def cik_for_ticker(
    ticker: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> int | None:
    """Resolve ``ticker`` to its integer SEC CIK, or ``None``.

    Fetches the public ``company_tickers.json`` map. Ticker matching is
    case-insensitive and normalises ``.`` to ``-`` (e.g. ``BRK.B`` → ``BRK-B``)
    the way SEC publishes class-share tickers. Best-effort: any failure returns
    ``None``.
    """
    symbol = ticker.strip().upper()
    if not symbol:
        return None
    try:
        payload = fetch_json(
            _TICKERS_URL, headers=_HEADERS, client=client, timeout=timeout
        )
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("SEC ticker map fetch failed: %s", exc)
        return None

    if not isinstance(payload, dict):
        return None

    candidates = {symbol, symbol.replace(".", "-"), symbol.replace("-", ".")}
    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        entry_ticker = str(entry.get("ticker", "")).upper()
        if entry_ticker in candidates:
            cik_raw = entry.get("cik_str")
            try:
                return int(cik_raw)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
    logger.debug("CIK not found for ticker %s", symbol)
    return None


# =============================================================================
# companyfacts fetch
# =============================================================================


def fetch_company_facts(
    cik: int,
    *,
    client: httpx.Client | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any] | None:
    """Fetch the full XBRL companyfacts payload for ``cik``, or ``None``.

    Zero-pads the CIK to 10 digits per the SEC URL scheme. Best-effort: a 404
    (no XBRL data — common for ETFs / foreign issuers), any other HTTP error,
    or a malformed body returns ``None``.
    """
    url = _COMPANY_FACTS_URL.format(cik=cik)
    try:
        payload = fetch_json(url, headers=_HEADERS, client=client, timeout=timeout)
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("companyfacts fetch failed for CIK %010d: %s", cik, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


# =============================================================================
# XBRL extraction helpers
# =============================================================================


def _gaap_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Return the ``us-gaap`` concept block (falling back to ``ifrs-full``)."""
    block = facts.get("facts")
    if not isinstance(block, dict):
        return {}
    gaap = block.get("us-gaap")
    if isinstance(gaap, dict) and gaap:
        return gaap
    ifrs = block.get("ifrs-full")
    if isinstance(ifrs, dict):
        return ifrs
    return {}


def _annual_entries(concept: dict[str, Any], unit: str) -> list[dict[str, Any]]:
    """Return annual (FY 10-K/20-F) value entries for one XBRL concept."""
    units = concept.get("units")
    if not isinstance(units, dict):
        return []
    values = units.get(unit)
    if not values and unit == "shares":
        values = units.get("pure")
    if not isinstance(values, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in values:
        if not isinstance(entry, dict):
            continue
        if entry.get("form") not in _ANNUAL_FORMS:
            continue
        if entry.get("fp") != "FY":
            continue
        if entry.get("fy") is None or entry.get("val") is None:
            continue
        out.append(entry)
    return out


def _value_by_year(gaap: dict[str, Any], metric: str) -> dict[int, float]:
    """Map fiscal-year → value for ``metric``, using the tag fallback chain.

    For each fiscal year the entry with the latest ``filed`` date wins (handles
    restatements / amended filings). The first concept in the chain that yields
    a value for a given year is used; later concepts only fill years still
    missing.
    """
    tags, unit = _TAGS[metric]
    by_year: dict[int, float] = {}
    for tag in tags:
        concept = gaap.get(tag)
        if not isinstance(concept, dict):
            continue
        best_filed: dict[int, str] = {}
        for entry in _annual_entries(concept, unit):
            fy = entry.get("fy")
            if not isinstance(fy, int):
                continue
            if fy in by_year:
                continue  # already resolved by an earlier tag
            filed = str(entry.get("filed", ""))
            if fy not in best_filed or filed >= best_filed[fy]:
                try:
                    by_year[fy] = float(entry.get("val"))  # type: ignore[arg-type]
                    best_filed[fy] = filed
                except (TypeError, ValueError):
                    continue
    return by_year


def _detect_fiscal_years(gaap: dict[str, Any]) -> list[int]:
    """Return fiscal years with annual filings, most-recent first."""
    years: set[int] = set()
    for metric in ("total_assets", "revenue", "net_income", "total_stockholders_equity"):
        years.update(_value_by_year(gaap, metric).keys())
    return sorted(years, reverse=True)


# =============================================================================
# Statement-row assembly
# =============================================================================


def _statement_rows(gaap: dict[str, Any], years: list[int]) -> dict[str, list[dict[str, Any]]]:
    """Build most-recent-first statement lists keyed for the EMF checks.

    Each row carries snake_case field names matching the aliases both
    ``croic.py`` and ``fscore.py`` accept. ``gross_profit`` is derived from
    ``revenue - cost_of_revenue`` when not directly reported. ``total_debt`` is
    ``long_term_debt + short_term_borrowings``.
    """
    metrics = {m: _value_by_year(gaap, m) for m in _TAGS}

    income: list[dict[str, Any]] = []
    balance: list[dict[str, Any]] = []
    cash: list[dict[str, Any]] = []

    def _get(metric: str, year: int) -> float | None:
        return metrics[metric].get(year)

    for year in years:
        revenue = _get("revenue", year)
        gross_profit = _get("gross_profit", year)
        cost_of_revenue = _get("cost_of_revenue", year)
        if gross_profit is None and revenue is not None and cost_of_revenue is not None:
            gross_profit = revenue - cost_of_revenue

        income.append(
            {
                "fiscal_year": year,
                "revenue": revenue,
                "net_income": _get("net_income", year),
                "gross_profit": gross_profit,
            }
        )

        ltd = _get("long_term_debt", year)
        stb = _get("short_term_borrowings", year)
        total_debt = (ltd or 0.0) + (stb or 0.0) if (ltd is not None or stb is not None) else None
        balance.append(
            {
                "fiscal_year": year,
                "total_assets": _get("total_assets", year),
                "total_current_assets": _get("total_current_assets", year),
                "total_current_liabilities": _get("total_current_liabilities", year),
                "long_term_debt": ltd,
                "total_debt": total_debt,
                "total_stockholders_equity": _get("total_stockholders_equity", year),
                "shares_outstanding": _get("shares_outstanding", year),
            }
        )

        cash.append(
            {
                "fiscal_year": year,
                "operating_cash_flow": _get("operating_cash_flow", year),
                "capital_expenditure": _get("capital_expenditure", year),
            }
        )

    return {
        "income_statements": income,
        "balance_sheets": balance,
        "cash_flows": cash,
    }


# =============================================================================
# Precomputed scalars (faithful to pw-nexus)
# =============================================================================


def _precompute_croic(
    cash_flow: dict[str, Any], balance_sheet: dict[str, Any]
) -> float | None:
    """Precompute current-year CROIC = FCF / (equity + debt).

    Faithful to pw-nexus ``enhanced_metrics.calculate_croic`` and the nexus-core
    ``croic.compute_croic`` (Jan 2026 fix: cash is **not** subtracted from
    invested capital). Returns ``None`` when inputs are missing or invested
    capital is non-positive.
    """
    ocf_raw = cash_flow.get("operating_cash_flow")
    if ocf_raw is None:
        return None
    ocf = float(ocf_raw)
    capex_raw = cash_flow.get("capital_expenditure")
    # SEC reports CapEx as a positive payment magnitude → subtract it.
    fcf = ocf - abs(float(capex_raw)) if capex_raw is not None else ocf

    equity_raw = balance_sheet.get("total_stockholders_equity")
    if equity_raw is None or equity_raw <= 0:
        return None
    equity = float(equity_raw)
    debt = float(balance_sheet.get("total_debt") or 0.0)
    invested_capital = equity + debt
    if invested_capital <= 0:
        return None
    return round(fcf / invested_capital, 4)


def _safe_div(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _precompute_fscore(
    income: list[dict[str, Any]],
    balance: list[dict[str, Any]],
    cash: list[dict[str, Any]],
) -> int | None:
    """Precompute the 9-point Piotroski F-Score from two-year statement lists.

    Faithful to pw-nexus ``compute_piotroski`` (conservative: a missing signal
    scores 0; no-prior-data dilution check passes). Returns ``None`` with fewer
    than two annual income + balance periods.
    """
    if len(income) < 2 or len(balance) < 2:
        return None

    inc_c, inc_p = income[0], income[1]
    bs_c, bs_p = balance[0], balance[1]
    cf_c = cash[0] if cash else {}

    ni = inc_c.get("net_income")
    ni_p = inc_p.get("net_income")
    assets = bs_c.get("total_assets")
    assets_p = bs_p.get("total_assets")
    ocf = cf_c.get("operating_cash_flow")
    revenue = inc_c.get("revenue")
    revenue_p = inc_p.get("revenue")
    gp = inc_c.get("gross_profit")
    gp_p = inc_p.get("gross_profit")
    ltd = bs_c.get("long_term_debt") or 0.0
    ltd_p = bs_p.get("long_term_debt") or 0.0
    ca = bs_c.get("total_current_assets")
    ca_p = bs_p.get("total_current_assets")
    cl = bs_c.get("total_current_liabilities")
    cl_p = bs_p.get("total_current_liabilities")
    shares = bs_c.get("shares_outstanding")
    shares_p = bs_p.get("shares_outstanding")

    score = 0
    roa = _safe_div(ni, assets)
    roa_p = _safe_div(ni_p, assets_p)

    # 1. ROA positive
    if roa is not None and roa > 0:
        score += 1
    # 2. Operating cash flow positive
    if ocf is not None and ocf > 0:
        score += 1
    # 3. ROA improving
    if roa is not None and roa_p is not None and roa > roa_p:
        score += 1
    # 4. Accrual quality (OCF/assets > ROA)
    ocf_over_assets = _safe_div(ocf, assets)
    if ocf_over_assets is not None and roa is not None and ocf_over_assets > roa:
        score += 1
    # 5. Leverage decreasing (LTD/assets falling)
    lev_c = _safe_div(ltd, assets)
    lev_p = _safe_div(ltd_p, assets_p)
    if lev_c is not None and lev_p is not None:
        if lev_c <= lev_p:
            score += 1
    elif lev_c is not None and lev_c < 0.4:
        score += 1
    # 6. Current ratio improving
    cr_c = _safe_div(ca, cl)
    cr_p = _safe_div(ca_p, cl_p)
    if cr_c is not None and cr_p is not None and cr_c > cr_p:
        score += 1
    # 7. No dilution (1% tolerance; pass when no prior data)
    if shares is not None and shares_p is not None and shares_p > 0:
        if (shares - shares_p) / shares_p <= 0.01:
            score += 1
    elif shares is not None and shares_p is None:
        score += 1
    # 8. Gross margin improving
    gm_c = _safe_div(gp, revenue)
    gm_p = _safe_div(gp_p, revenue_p)
    if gm_c is not None and gm_p is not None and gm_c > gm_p:
        score += 1
    # 9. Asset turnover improving
    at_c = _safe_div(revenue, assets)
    at_p = _safe_div(revenue_p, assets_p)
    if at_c is not None and at_p is not None and at_c > at_p:
        score += 1

    return score


# =============================================================================
# Sector / industry (SEC submissions endpoint)
# =============================================================================

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

# SIC major group (first two digits) -> GICS-style sector label, matching the
# vocabulary the EMF sector / layer / ASAN checks consume. Coarse but adequate
# for sector-tailwind + layer assignment; high-value splits (semiconductors,
# software, pharma, autos vs aerospace, REITs) are handled by _SIC_OVERRIDES,
# which take precedence.
_SIC_MAJOR_SECTOR: dict[int, str] = {
    1: "basic materials", 2: "basic materials", 7: "basic materials", 9: "basic materials",
    10: "basic materials", 12: "basic materials", 14: "basic materials",
    13: "energy",
    15: "industrials", 16: "industrials", 17: "industrials",
    20: "consumer defensive", 21: "consumer defensive",
    22: "consumer cyclical", 23: "consumer cyclical",
    24: "basic materials", 25: "consumer cyclical", 26: "basic materials",
    27: "communication services",
    28: "basic materials",
    29: "energy",
    30: "consumer cyclical", 31: "consumer cyclical", 32: "basic materials",
    33: "basic materials", 34: "industrials",
    35: "industrials", 36: "technology",
    37: "consumer cyclical",
    38: "technology", 39: "consumer cyclical",
    40: "industrials", 41: "industrials", 42: "industrials", 44: "industrials",
    45: "industrials", 47: "industrials",
    48: "communication services",
    49: "utilities",
    50: "consumer cyclical", 51: "consumer cyclical",
    52: "consumer cyclical", 53: "consumer cyclical", 55: "consumer cyclical",
    56: "consumer cyclical", 57: "consumer cyclical", 59: "consumer cyclical",
    54: "consumer defensive",
    58: "consumer cyclical",
    60: "financials", 61: "financials", 62: "financials", 63: "financials",
    64: "financials", 67: "financials",
    65: "real estate",
    70: "consumer cyclical", 72: "consumer cyclical", 73: "technology",
    75: "consumer cyclical", 78: "communication services", 79: "consumer cyclical",
    80: "healthcare", 82: "communication services", 87: "industrials",
}

_SIC_OVERRIDES: tuple[tuple[int, int, str], ...] = (
    (2833, 2836, "healthcare"),  # pharmaceutical / biological products
    (3570, 3579, "technology"),  # computer & office equipment
    (3661, 3669, "technology"),  # communications equipment
    (3670, 3679, "technology"),  # semiconductors & electronic components
    (3840, 3851, "healthcare"),  # medical / surgical instruments & supplies
    (7370, 7379, "technology"),  # computer programming, software & data services
    (3710, 3716, "consumer cyclical"),  # motor vehicles & parts
    (3720, 3728, "industrials"),  # aircraft & aerospace
    (6798, 6798, "real estate"),  # REITs (within the 67xx financial group)
)


def _sic_to_sector(sic: int | None) -> str | None:
    """Map a SEC SIC code to the GICS-style sector label the EMF checks use."""
    if sic is None:
        return None
    for lo, hi, sector in _SIC_OVERRIDES:
        if lo <= sic <= hi:
            return sector
    return _SIC_MAJOR_SECTOR.get(sic // 100)


def fetch_company_submissions(
    cik: int,
    *,
    client: httpx.Client | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any] | None:
    """Fetch SEC submissions metadata for ``cik`` (carries ``sic`` + name), or ``None``."""
    url = _SUBMISSIONS_URL.format(cik=cik)
    try:
        payload = fetch_json(url, headers=_HEADERS, client=client, timeout=timeout)
    except (httpx.HTTPError, ValueError) as exc:
        logger.debug("SEC submissions fetch failed for CIK %s: %s", cik, exc)
        return None
    return payload if isinstance(payload, dict) else None


def _extract_sic(submissions: dict[str, Any] | None) -> tuple[int | None, str | None]:
    """Pull (sic_code, sic_description) from a submissions payload, best-effort."""
    if not isinstance(submissions, dict):
        return None, None
    raw = submissions.get("sic")
    sic: int | None = None
    if isinstance(raw, (int, str)) and str(raw).strip():
        try:
            sic = int(raw)
        except (TypeError, ValueError):
            sic = None
    return sic, submissions.get("sicDescription") or None


# =============================================================================
# Public entry point
# =============================================================================


def build_fundamentals(
    ticker: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any] | None:
    """Build the EMF ``fundamentals`` dict for ``ticker`` from SEC companyfacts.

    Returns a dict populating the exact keys the CROIC and F-Score checks read:

    * ``croic`` — precomputed current-year CROIC (float) or ``None``.
    * ``f_score`` — precomputed Piotroski 0-9 (int) or ``None``.
    * ``income_statements`` / ``balance_sheets`` / ``cash_flows`` — most-recent-
      first lists of per-fiscal-year statement rows in the field-name shape the
      checks accept (so they can recompute if the scalars are absent).

    Plus diagnostic keys ``ticker``, ``cik``, ``fiscal_years``, ``source``,
    ``croic_passes``, ``f_score_passes``.

    Best-effort: returns ``None`` if the ticker can't be resolved, the
    companyfacts payload is unavailable, or there is no annual GAAP data. Never
    raises.
    """
    cik = cik_for_ticker(ticker, client=client, timeout=timeout)
    if cik is None:
        return None

    facts = fetch_company_facts(cik, client=client, timeout=timeout)
    if facts is None:
        return None

    gaap = _gaap_facts(facts)
    if not gaap:
        return None

    years = _detect_fiscal_years(gaap)
    if not years:
        return None

    rows = _statement_rows(gaap, years)
    income = rows["income_statements"]
    balance = rows["balance_sheets"]
    cash = rows["cash_flows"]

    croic: float | None = None
    if cash and balance:
        croic = _precompute_croic(cash[0], balance[0])

    f_score = _precompute_fscore(income, balance, cash)

    # Sector / industry from the submissions endpoint (separate from companyfacts).
    # Best-effort: leaves sector None if unavailable, so the sector/regime/ASAN
    # checks simply report insufficient_data rather than misclassifying.
    sic, sic_description = _extract_sic(
        fetch_company_submissions(cik, client=client, timeout=timeout)
    )
    sector = _sic_to_sector(sic)

    return {
        "ticker": ticker.strip().upper(),
        "cik": cik,
        "source": "SEC EDGAR XBRL companyfacts",
        "fiscal_years": years,
        "sector": sector,
        "industry": sic_description,
        "sic": sic,
        "sic_description": sic_description,
        "croic": croic,
        "croic_passes": croic is not None and croic > _CROIC_STRONG_THRESHOLD,
        "f_score": f_score,
        "f_score_passes": f_score is not None and f_score >= _FSCORE_THRESHOLD,
        "income_statements": income,
        "balance_sheets": balance,
        "cash_flows": cash,
    }


__all__ = [
    "SEC_USER_AGENT",
    "build_fundamentals",
    "cik_for_ticker",
    "fetch_company_facts",
    "fetch_company_submissions",
]
