# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Deribit public options client.

A keyless client over the Deribit public v2 REST API
(https://www.deribit.com/api/v2). Deribit speaks JSON-RPC-over-REST: every
public method is reachable as ``GET /public/<method>`` and wraps its payload in
a top-level ``{"result": ...}`` envelope. This client unwraps ``result`` and
exposes the option-instrument list, per-instrument ticker (mark price, implied
vol, greeks, top-of-book), and the spot index price for the supported
currencies (BTC, ETH, SOL).

Every input is a *public* market parameter — a currency code or an exchange
instrument name (e.g. ``BTC-27JUN25-100000-C``). Nothing here takes an account,
wallet, or per-person context, and nothing here is advice: it is an educational
view of publicly listed option structures and their observable market data.

Like every REST adapter in :mod:`nexus_core.data`, requests flow through
:func:`nexus_core.data.http.fetch_json`, so an injected ``httpx.Client`` wired
to an ``httpx.MockTransport`` makes the client hermetically testable with no
network and no credentials.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.deribit.com/api/v2"
_DEFAULT_TIMEOUT = 10.0

#: Currencies this client supports, mapped to their Deribit spot index name.
_INDEX_NAMES: dict[str, str] = {
    "BTC": "btc_usd",
    "ETH": "eth_usd",
    "SOL": "sol_usd",
}

#: Educational-framing disclaimer attached to structured option outputs.
DISCLAIMER = "Educational illustration only — not investment advice."


@dataclass
class OptionTicker:
    """Observable market data for one listed option instrument.

    Every field is public exchange market data for the named instrument; this
    is a descriptive snapshot of an option *structure*, not a recommendation.

    Attributes:
        instrument_name: Deribit instrument name (e.g. ``BTC-27JUN25-100000-C``).
        mark_price: Exchange mark price, in units of the underlying (Deribit
            quotes option prices in coin terms). ``None`` if unavailable.
        mark_iv: Mark implied volatility, in percent (Deribit convention).
        underlying_price: Underlying / futures price used for marking.
        delta: Option delta.
        gamma: Option gamma.
        theta: Option theta.
        vega: Option vega.
        rho: Option rho.
        bid_price: Best bid, in units of the underlying.
        ask_price: Best ask, in units of the underlying.
        open_interest: Open interest in contracts.
        disclaimer: Educational-framing disclaimer.
    """

    instrument_name: str
    mark_price: float | None = None
    mark_iv: float | None = None
    underlying_price: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None
    bid_price: float | None = None
    ask_price: float | None = None
    open_interest: float | None = None
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_name": self.instrument_name,
            "mark_price": self.mark_price,
            "mark_iv": self.mark_iv,
            "underlying_price": self.underlying_price,
            "greeks": {
                "delta": self.delta,
                "gamma": self.gamma,
                "theta": self.theta,
                "vega": self.vega,
                "rho": self.rho,
            },
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
            "open_interest": self.open_interest,
            "disclaimer": self.disclaimer,
        }


@dataclass
class OptionInstrument:
    """Static contract specification for one listed option instrument.

    Attributes:
        instrument_name: Deribit instrument name.
        base_currency: Base currency (BTC / ETH / SOL).
        option_type: ``call`` or ``put``.
        strike: Strike price.
        expiration_timestamp: Expiry as Unix epoch milliseconds.
        is_active: Whether the instrument is currently tradeable.
        details: Remaining raw instrument fields, for callers that need them.
    """

    instrument_name: str
    base_currency: str
    option_type: str | None = None
    strike: float | None = None
    expiration_timestamp: int | None = None
    is_active: bool | None = None
    details: dict[str, Any] = field(default_factory=dict)


class DeribitClient:
    """Public options client backed by the keyless Deribit v2 REST API.

    Args:
        http_client: Optional ``httpx.Client`` for hermetic tests. Inject one
            wired to an ``httpx.MockTransport`` to avoid network access.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._http_client = http_client
        self._timeout = timeout

    def _get_result(self, endpoint: str, params: dict[str, Any] | None = None) -> Any | None:
        """GET a public method and return the unwrapped ``result`` payload.

        Returns ``None`` on transport failure, a non-2xx response, malformed
        JSON, or a JSON-RPC error envelope.
        """
        try:
            payload = fetch_json(
                f"{_BASE_URL}{endpoint}",
                params=params,
                headers={"Accept": "application/json"},
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("Deribit fetch %s failed: %s", endpoint, exc)
            return None
        if not isinstance(payload, dict):
            return None
        if "error" in payload and payload.get("error"):
            logger.debug("Deribit error envelope for %s: %s", endpoint, payload.get("error"))
            return None
        return payload.get("result")

    @staticmethod
    def _as_float(value: Any) -> float | None:
        """Coerce a JSON value to ``float``; Deribit sends ``null`` freely."""
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _normalise_currency(currency: str) -> str | None:
        """Return the supported upper-cased currency code, or ``None``."""
        if not isinstance(currency, str):
            return None
        code = currency.strip().upper()
        return code if code in _INDEX_NAMES else None

    def list_option_instruments(self, currency: str) -> list[OptionInstrument]:
        """Return active option instruments for ``currency`` (BTC / ETH / SOL).

        Backs ``GET /public/get_instruments?currency=...&kind=option&expired=false``.
        Returns an empty list for an unsupported currency or on failure.
        """
        code = self._normalise_currency(currency)
        if code is None:
            return []
        result = self._get_result(
            "/public/get_instruments",
            # ``expired`` must be the lowercase JSON literal Deribit expects;
            # passing Python ``False`` would serialise to the string "False".
            params={"currency": code, "kind": "option", "expired": "false"},
        )
        if not isinstance(result, list):
            return []
        instruments: list[OptionInstrument] = []
        for entry in result:
            if not isinstance(entry, dict):
                continue
            name = entry.get("instrument_name")
            if not isinstance(name, str) or not name:
                continue
            expiry = entry.get("expiration_timestamp")
            instruments.append(
                OptionInstrument(
                    instrument_name=name,
                    base_currency=entry.get("base_currency") or code,
                    option_type=entry.get("option_type"),
                    strike=self._as_float(entry.get("strike")),
                    expiration_timestamp=int(expiry) if isinstance(expiry, (int, float)) else None,
                    is_active=entry.get("is_active")
                    if isinstance(entry.get("is_active"), bool)
                    else None,
                    details=entry,
                )
            )
        return instruments

    def get_option_ticker(self, instrument_name: str) -> OptionTicker | None:
        """Return the market-data ticker for one option ``instrument_name``.

        Backs ``GET /public/ticker?instrument_name=...``. Returns ``None`` for a
        blank instrument name or on failure.
        """
        if not isinstance(instrument_name, str) or not instrument_name.strip():
            return None
        result = self._get_result(
            "/public/ticker",
            params={"instrument_name": instrument_name},
        )
        if not isinstance(result, dict):
            return None
        greeks = result.get("greeks")
        greeks = greeks if isinstance(greeks, dict) else {}
        return OptionTicker(
            instrument_name=result.get("instrument_name") or instrument_name,
            mark_price=self._as_float(result.get("mark_price")),
            mark_iv=self._as_float(result.get("mark_iv")),
            underlying_price=self._as_float(result.get("underlying_price")),
            delta=self._as_float(greeks.get("delta")),
            gamma=self._as_float(greeks.get("gamma")),
            theta=self._as_float(greeks.get("theta")),
            vega=self._as_float(greeks.get("vega")),
            rho=self._as_float(greeks.get("rho")),
            bid_price=self._as_float(result.get("best_bid_price")),
            ask_price=self._as_float(result.get("best_ask_price")),
            open_interest=self._as_float(result.get("open_interest")),
        )

    def get_index_price(self, currency: str) -> float | None:
        """Return the spot index price for ``currency`` (BTC / ETH / SOL).

        Backs ``GET /public/get_index_price?index_name=btc_usd`` (the currency
        is mapped to its ``<code>_usd`` index name). Returns ``None`` for an
        unsupported currency or on failure.
        """
        code = self._normalise_currency(currency)
        if code is None:
            return None
        result = self._get_result(
            "/public/get_index_price",
            params={"index_name": _INDEX_NAMES[code]},
        )
        if not isinstance(result, dict):
            return None
        return self._as_float(result.get("index_price"))


__all__ = ["DISCLAIMER", "DeribitClient", "OptionInstrument", "OptionTicker"]

