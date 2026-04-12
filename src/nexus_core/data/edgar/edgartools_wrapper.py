# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""edgartools wrapper — structured SEC filing access.

edgartools already ships its own MCP server (accepted into Anthropic's Claude
for Open Source program). This wrapper adapts its output to the nexus-core
``Filing`` dataclass so it composes with the scoring framework and regime
engine without leaking library-specific types.

Typical use::

    from nexus_core.data.edgar import get_latest_filing

    tenk = get_latest_filing("AAPL", form="10-K")
    print(tenk.filed_at, tenk.accession_number)
    for item in tenk.items:
        print(item.title[:80])

Install::

    pip install nexus-core[edgar]

Attribution:
    edgartools — Copyright 2023+ Dwight Gunning (MIT).
    https://github.com/dgunning/edgartools
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

try:
    from edgar import Company, set_identity
except ImportError:  # pragma: no cover
    Company = set_identity = None  # type: ignore[assignment,misc]


@dataclass
class FilingItem:
    """A single item in a filing (e.g., Item 1A Risk Factors)."""

    number: str
    title: str
    body: str


@dataclass
class Filing:
    """SEC filing record.

    Attributes:
        ticker: Requesting ticker (may differ from company name).
        form: Filing form type ("10-K", "10-Q", "8-K", "DEF 14A", etc.).
        accession_number: SEC accession number.
        filed_at: Date filed with SEC.
        period_of_report: Fiscal period covered (if applicable).
        company_name: Registrant name.
        cik: SEC CIK number.
        url: Filing index URL.
        items: Parsed items, if extraction succeeded.
        extra: Library-native payload for callers needing more detail.
    """

    ticker: str
    form: str
    accession_number: str
    filed_at: date
    company_name: str
    cik: str
    period_of_report: date | None = None
    url: str | None = None
    items: list[FilingItem] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def configure_identity(name: str, email: str) -> None:
    """Register the caller's identity with SEC (required by EDGAR fair-use policy).

    Must be called once before any EDGAR request. SEC tracks bulk traffic by
    user-agent; compliance with the fair-use policy prevents IP blocks.
    """
    if set_identity is None:
        raise ImportError("edgartools not installed. Install with: pip install nexus-core[edgar]")
    set_identity(f"{name} {email}")


def get_latest_filing(ticker: str, *, form: str = "10-K") -> Filing | None:
    """Return the most recent filing of ``form`` type for ``ticker`` or None.

    Args:
        ticker: Stock ticker (e.g., "AAPL", "MSFT").
        form: SEC form code. Common: ``10-K``, ``10-Q``, ``8-K``, ``DEF 14A``.
    """
    if Company is None:
        raise ImportError("edgartools not installed. Install with: pip install nexus-core[edgar]")

    company = Company(ticker)
    filings = company.get_filings(form=form)
    if not filings or len(filings) == 0:
        return None

    raw = filings.latest(1)[0]
    return _to_filing(ticker, raw)


def get_filings(ticker: str, *, form: str = "10-K", limit: int = 10) -> list[Filing]:
    """Return up to ``limit`` filings for ``ticker`` of the given form type."""
    if Company is None:
        raise ImportError("edgartools not installed. Install with: pip install nexus-core[edgar]")

    company = Company(ticker)
    filings = company.get_filings(form=form)
    if not filings:
        return []

    latest_batch = filings.latest(limit) if hasattr(filings, "latest") else filings
    return [_to_filing(ticker, f) for f in latest_batch]


def _to_filing(ticker: str, raw: Any) -> Filing:
    """Adapt an edgartools filing into our ``Filing`` dataclass."""
    items: list[FilingItem] = []
    try:
        for item in getattr(raw, "items", []) or []:
            items.append(
                FilingItem(
                    number=str(getattr(item, "item", "")),
                    title=str(getattr(item, "title", "")),
                    body=str(getattr(item, "text", ""))[:10000],  # cap long bodies
                )
            )
    except Exception:  # pragma: no cover
        pass

    return Filing(
        ticker=ticker,
        form=str(getattr(raw, "form", "")),
        accession_number=str(getattr(raw, "accession_no", "")),
        filed_at=getattr(raw, "filing_date", None),
        period_of_report=getattr(raw, "period_of_report", None),
        company_name=str(getattr(raw, "company", "")),
        cik=str(getattr(raw, "cik", "")),
        url=str(getattr(raw, "homepage_url", "")) or None,
        items=items,
        extra={"raw_type": type(raw).__name__},
    )


__all__ = [
    "Filing",
    "FilingItem",
    "configure_identity",
    "get_filings",
    "get_latest_filing",
]
