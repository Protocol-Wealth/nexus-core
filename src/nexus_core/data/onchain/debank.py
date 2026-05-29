# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""DeBank Pro client for anonymous EVM wallet balances.

Resolves an arbitrary public EVM address to its total USD balance and token
holdings via the DeBank Pro OpenAPI. This is **anonymous, public on-chain data**:
the input is just an address, the output is just balances — nothing here links
an address to a person, name, or any client record.

Auth is DeBank's custom ``AccessKey`` header (not ``Authorization``); the key
comes from ``DEBANK_API_KEY``. Without it, :meth:`is_configured` is ``False`` and
every getter returns ``None``.

Built by reading the shape of the private pw-api ``src/lib/debank.ts`` reference
(endpoints, params, response normalisation) and reimplementing in nexus-core's
sync house style — no code copied, no runtime call to pw-api. Best-effort: bad
address, missing key, or any failure degrades to ``None``/empty rather than raising.

Endpoints used (DeBank Pro v1):
    * ``/user/total_balance`` — total USD across chains.
    * ``/user/all_token_list`` — per-token balances (dust filtered).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from ..http import fetch_json

logger = logging.getLogger(__name__)

_BASE_URL = "https://pro-openapi.debank.com/v1"
_DEFAULT_TIMEOUT = 30.0
_DUST_USD = 0.01
_EVM_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


def is_evm_address(address: str) -> bool:
    """Whether ``address`` is a syntactically valid EVM address (0x + 40 hex)."""
    return bool(_EVM_ADDRESS_RE.match(address.strip()))


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class WalletToken:
    """One token holding in a wallet (USD-valued)."""

    id: str
    chain: str
    symbol: str
    name: str
    amount: float
    price: float
    usd_value: float


class DeBankClient:
    """Anonymous EVM wallet balance client (DeBank Pro OpenAPI).

    Args:
        api_key: DeBank Pro key. Falls back to the ``DEBANK_API_KEY`` env var.
        http_client: Optional ``httpx.Client`` for hermetic tests.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        import os

        self._api_key = api_key or os.environ.get("DEBANK_API_KEY") or None
        self._http_client = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        """Whether a DeBank API key is available."""
        return self._api_key is not None

    def _get(self, path: str, params: dict[str, Any]) -> Any | None:
        if self._api_key is None:
            return None
        try:
            return fetch_json(
                f"{_BASE_URL}{path}",
                params=params,
                headers={"AccessKey": self._api_key, "Accept": "application/json"},
                client=self._http_client,
                timeout=self._timeout,
            )
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("DeBank fetch %s failed: %s", path, exc)
            return None

    def get_total_balance(self, address: str) -> dict[str, Any] | None:
        """Total USD balance + per-chain breakdown for ``address``, or ``None``."""
        if not is_evm_address(address):
            return None
        payload = self._get("/user/total_balance", {"id": address.lower()})
        if not isinstance(payload, dict):
            return None
        chains = {
            c["id"]: _num(c.get("usd_value"))
            for c in payload.get("chain_list") or []
            if isinstance(c, dict) and c.get("id")
        }
        return {
            "total_usd_value": _num(payload.get("total_usd_value")),
            "chains": chains,
        }

    def get_tokens(self, address: str, *, limit: int = 50) -> list[WalletToken]:
        """Token holdings for ``address``, dust-filtered, sorted by USD value desc."""
        if not is_evm_address(address):
            return []
        payload = self._get(
            "/user/all_token_list", {"id": address.lower(), "is_all": "false"}
        )
        if isinstance(payload, dict):
            raw: list[Any] = [t for group in payload.values() if isinstance(group, list) for t in group]
        elif isinstance(payload, list):
            raw = payload
        else:
            return []

        tokens: list[WalletToken] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            amount = _num(entry.get("amount"))
            price = _num(entry.get("price"))
            usd = amount * price
            if usd < _DUST_USD:
                continue
            tokens.append(
                WalletToken(
                    id=entry.get("id") or "",
                    chain=entry.get("chain") or "",
                    symbol=entry.get("symbol") or "",
                    name=entry.get("name") or "",
                    amount=amount,
                    price=price,
                    usd_value=round(usd, 2),
                )
            )
        tokens.sort(key=lambda t: t.usd_value, reverse=True)
        return tokens[: max(0, limit)]

    def wallet_snapshot(self, address: str, *, top_n: int = 20) -> dict[str, Any] | None:
        """Anonymous balance snapshot for an EVM ``address``: total + top holdings.

        Returns ``None`` for an invalid address or when DeBank has no data. No
        identity, name, or client linkage — purely an address → balances view.
        """
        if not is_evm_address(address):
            return None
        balance = self.get_total_balance(address)
        if balance is None:
            return None
        tokens = self.get_tokens(address, limit=top_n)
        return {
            "address": address.lower(),
            "total_usd_value": balance["total_usd_value"],
            "chains": balance["chains"],
            "token_count": len(tokens),
            "top_tokens": [
                {"symbol": t.symbol, "chain": t.chain, "usd_value": t.usd_value} for t in tokens
            ],
        }


__all__ = ["DeBankClient", "WalletToken", "is_evm_address"]
