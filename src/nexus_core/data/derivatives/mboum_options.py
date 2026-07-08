# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""MBOUM equity option chain client.

A keyed client over the MBOUM Financial Data API's options endpoint
(``GET https://api.mboum.com/v3/markets/options?ticker=X``), which proxies the
Yahoo Finance listed-equity option board. Requires an API key — set
``MBOUM_API_KEY`` or pass ``api_key``; without one every method returns
``None`` so the REST routes can degrade to ``503`` (matching the repo-wide
"every provider key optional; endpoints degrade, never fake 200s" convention).

The upstream envelope is ``{"meta": {"expirations": {"weekly": [...],
"monthly": [...]}}, "body": {"Call": [rows], "Put": [rows]}}`` where every row
field is a DISPLAY-FORMATTED string: ``strikePrice`` ``"70.00"``, prices with a
possible ``"$"`` prefix, ``openInterest`` with thousands separators
(``"7,299"``), ``volatility`` as a percent string (``"28.19%"``), and dates as
``"08/21/26"`` or ``"07/28/2026"``. Sentinel values (``"unch"``, ``"N/A"``,
``"--"``, ``""``) appear freely. This client normalizes all of that into plain
floats/ints/ISO dates and whitelists the fields it returns — nothing beyond
:class:`EquityOptionQuote`'s fields ever crosses to a caller.

Every input is a *public* market parameter — a ticker symbol and a listed
expiration date. Nothing here takes an account, wallet, or per-person context,
and nothing here is advice: it is an educational view of publicly listed
option structures and their observable market data.

Like every REST adapter in :mod:`nexus_core.data`, requests flow through
:func:`nexus_core.data.http.fetch_json`, so an injected ``httpx.Client`` wired
to an ``httpx.MockTransport`` makes the client hermetically testable with no
network and no credentials.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.mboum.com"
#: MBOUM recommends generous timeouts (see the market-data provider).
_DEFAULT_TIMEOUT = 30.0

#: Display-string sentinels MBOUM emits for "no value" (case-insensitive).
_SENTINELS = frozenset({"", "unch", "n/a", "--", "-"})

#: Accepted upstream date renderings, tried in order. MBOUM mixes 2- and
#: 4-digit years ("08/21/26" and "07/28/2026"); ISO is accepted defensively.
_DATE_FORMATS = ("%m/%d/%y", "%m/%d/%Y", "%Y-%m-%d")

#: Expiration bucket labels used by both the vendor and this client's output.
_EXPIRATION_BUCKETS = ("monthly", "weekly")

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class EquityOptionQuote:
    """One normalized option row (a single strike on one side of the board).

    Every field is public exchange market data for the listed contract; this is
    a descriptive snapshot of an option *structure*, not a recommendation. All
    display formatting from the vendor ("$", thousands separators, "%",
    ``unch``/``N/A`` sentinels, US-style dates) has been parsed away.

    Attributes:
        strike: Strike price.
        bid: Best bid, or ``None`` when unquoted.
        ask: Best ask, or ``None`` when unquoted.
        mid: Bid/ask midpoint as reported upstream.
        last: Last traded price.
        volume: Day volume in contracts.
        open_interest: Open interest in contracts.
        iv: Implied volatility as a decimal fraction (``0.2819`` for 28.19%).
        delta: Option delta.
        expiration: Contract expiration date (ISO ``YYYY-MM-DD``).
        expiration_type: ``"weekly"`` or ``"monthly"``.
        next_earnings: Underlier's next earnings date (ISO), when reported.
        ex_div: Underlier's ex-dividend date (ISO), when reported.
    """

    strike: float
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    last: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    iv: float | None = None
    delta: float | None = None
    expiration: str | None = None
    expiration_type: str | None = None
    next_earnings: str | None = None
    ex_div: str | None = None


@dataclass
class EquityOptionChain:
    """Normalized single-expiration option chain for one underlier.

    Attributes:
        symbol: Underlying ticker.
        expiration: The requested expiration date (ISO ``YYYY-MM-DD``).
        calls: Call rows, sorted by strike ascending.
        puts: Put rows, sorted by strike ascending.
    """

    symbol: str
    expiration: str
    calls: list[EquityOptionQuote] = field(default_factory=list)
    puts: list[EquityOptionQuote] = field(default_factory=list)


def _as_float(value: Any) -> float | None:
    """Parse a display-formatted number to ``float``.

    Handles plain JSON numbers, ``"$"`` prefixes, thousands separators, and the
    MBOUM sentinels (``"unch"``, ``"N/A"``, ``"--"``, ``""``) — sentinels and
    anything unparseable return ``None``.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower() in _SENTINELS:
        return None
    text = text.replace("$", "").replace(",", "")
    try:
        return float(text)
    except ValueError:
        return None


def _as_int(value: Any) -> int | None:
    """Parse a display-formatted count ("7,299") to ``int``; ``None`` otherwise."""
    number = _as_float(value)
    return int(number) if number is not None else None


def _as_iv_fraction(value: Any) -> float | None:
    """Parse the vendor's percent-formatted implied vol to a decimal fraction.

    MBOUM renders ``volatility`` in percent terms (``"28.19%"``), so the value
    is divided by 100 whether or not the ``%`` suffix survives serialization.
    """
    if isinstance(value, str):
        value = value.strip().removesuffix("%")
    number = _as_float(value)
    if number is None or number < 0.0:
        return None
    return number / 100.0


def _as_iso_date(value: Any) -> str | None:
    """Parse an upstream date string ("08/21/26", "07/28/2026") to ISO, or ``None``."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower() in _SENTINELS:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_row(row: Any) -> EquityOptionQuote | None:
    """Normalize one vendor row; ``None`` when the strike is missing/invalid.

    Whitelist extraction: only the :class:`EquityOptionQuote` fields are read —
    any other vendor field (display strings, quote links, symbols of the OCC
    contract, execution-adjacent extras) is dropped here.
    """
    if not isinstance(row, dict):
        return None
    strike = _as_float(row.get("strikePrice"))
    if strike is None or strike <= 0.0:
        return None
    expiration_type = row.get("expirationType")
    if expiration_type not in _EXPIRATION_BUCKETS:
        expiration_type = None
    return EquityOptionQuote(
        strike=strike,
        bid=_as_float(row.get("bidPrice")),
        ask=_as_float(row.get("askPrice")),
        mid=_as_float(row.get("midpoint")),
        last=_as_float(row.get("lastPrice")),
        volume=_as_int(row.get("volume")),
        open_interest=_as_int(row.get("openInterest")),
        iv=_as_iv_fraction(row.get("volatility")),
        delta=_as_float(row.get("delta")),
        expiration=_as_iso_date(row.get("expirationDate")),
        expiration_type=expiration_type,
        next_earnings=_as_iso_date(row.get("baseNextEarningsDate")),
        ex_div=_as_iso_date(row.get("dividendExDate")),
    )


def _parse_side(rows: Any) -> list[EquityOptionQuote]:
    """Parse one side ("Call"/"Put") of the board, sorted by strike ascending."""
    if not isinstance(rows, list):
        return []
    parsed = [quote for row in rows if (quote := _parse_row(row)) is not None]
    parsed.sort(key=lambda q: q.strike)
    return parsed


class MboumOptionsClient:
    """Equity option chain client backed by the keyed MBOUM options API.

    Args:
        api_key: MBOUM bearer token. Falls back to the ``MBOUM_API_KEY`` env
            var (the same key the MBOUM market-data provider uses). Without a
            key the client reports unconfigured and every fetch returns
            ``None`` — callers degrade instead of faking data.
        http_client: Optional ``httpx.Client`` for hermetic tests. Inject one
            wired to an ``httpx.MockTransport`` to avoid network access.
        timeout: Per-request timeout in seconds (MBOUM recommends >= 30s).
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key or os.environ.get("MBOUM_API_KEY") or None
        self._http_client = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        """Whether an API key is available."""
        return self._api_key is not None

    def _fetch(self, symbol: str, expiration: str | None = None) -> dict[str, Any] | None:
        """GET the options envelope for ``symbol`` (optionally one expiration).

        Returns ``None`` when unconfigured, on transport failure, a non-2xx
        response, or a malformed (non-object) payload.
        """
        if self._api_key is None:
            return None
        params: dict[str, Any] = {"ticker": symbol}
        if expiration is not None:
            params["expiration"] = expiration
        try:
            payload = fetch_json(
                f"{_BASE_URL}/v3/markets/options",
                params=params,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("MBOUM options fetch for %s failed: %s", symbol, exc)
            return None
        return payload if isinstance(payload, dict) else None

    def list_expirations(self, symbol: str) -> dict[str, list[str]] | None:
        """Return the listed expiration dates for ``symbol`` by bucket.

        Backs ``GET /v3/markets/options?ticker=X`` and reads
        ``meta.expirations``. Returns ``{"monthly": [...], "weekly": [...]}``
        with ISO dates sorted ascending (buckets may be empty for an underlier
        with no listed options), or ``None`` when the client is unconfigured or
        the upstream fetch/payload fails.
        """
        payload = self._fetch(symbol)
        if payload is None:
            return None
        meta = payload.get("meta")
        expirations = meta.get("expirations") if isinstance(meta, dict) else None
        if not isinstance(expirations, dict):
            return None
        out: dict[str, list[str]] = {}
        for bucket in _EXPIRATION_BUCKETS:
            raw = expirations.get(bucket)
            if not isinstance(raw, list):
                out[bucket] = []
                continue
            out[bucket] = sorted(
                {d.strip() for d in raw if isinstance(d, str) and _ISO_DATE_RE.match(d.strip())}
            )
        return out

    def get_chain(self, symbol: str, expiration: str) -> EquityOptionChain | None:
        """Return the normalized option chain for ``symbol`` at one ``expiration``.

        Backs ``GET /v3/markets/options?ticker=X&expiration=YYYY-MM-DD`` — the
        expiration is always sent so a request never pulls the full multi-expiry
        board. Rows are normalized to floats/ints/ISO dates, whitelisted to
        :class:`EquityOptionQuote`'s fields, and sorted by strike. Returns
        ``None`` when the client is unconfigured or the upstream fetch/payload
        fails; a well-formed response with no rows yields an empty chain (the
        caller decides whether that is a 404).
        """
        payload = self._fetch(symbol, expiration=expiration)
        if payload is None:
            return None
        body = payload.get("body")
        if not isinstance(body, dict):
            return None
        return EquityOptionChain(
            symbol=symbol,
            expiration=expiration,
            calls=_parse_side(body.get("Call")),
            puts=_parse_side(body.get("Put")),
        )


__all__ = ["EquityOptionChain", "EquityOptionQuote", "MboumOptionsClient"]
