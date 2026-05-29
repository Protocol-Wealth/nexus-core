# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tatum multi-chain RPC client — anonymous native-balance lookups.

Tatum hosts JSON-RPC gateways for 60+ chains at
``https://{subdomain}.gateway.tatum.io`` (e.g. ``ethereum-mainnet``,
``solana-mainnet``), authenticated with an ``x-api-key`` header. This client
reads the **native-coin balance** of an arbitrary public address on a given
chain:

- EVM chains (Ethereum, Base, Polygon, Arbitrum, …): ``eth_getBalance`` returns
  wei (1e18 per coin).
- Solana: ``getBalance`` returns lamports (1e9 per SOL).

This is **anonymous public on-chain data** — the input is just an address and a
chain, the output is just a native balance. No identity, name, token-portfolio,
or client linkage (that breadth lives in :class:`DeBankClient`; this complements
it with native balances across chains DeBank does not cover, incl. Solana).
Requires ``TATUM_API_KEY``.

Built referencing pw-api conventions only (no copy); the Tatum gateway protocol
is plain JSON-RPC over HTTPS with an ``x-api-key`` header.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from .debank import is_evm_address

_GATEWAY = "https://{subdomain}.gateway.tatum.io"
_TIMEOUT = 15.0
# base58 alphabet (Bitcoin/Solana) — excludes 0, O, I, l.
_BASE58 = frozenset("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


@dataclass(frozen=True)
class _ChainMeta:
    subdomain: str  # gateway subdomain, e.g. "ethereum-mainnet"
    family: str  # "evm" | "solana"
    symbol: str  # native-coin ticker
    decimals: int  # native-coin decimals


# Curated subset of Tatum's chains where a native balance is a single RPC call.
# EVM → eth_getBalance (18 decimals); Solana → getBalance (9 decimals). Keep this
# to chains with a uniform balance call; bespoke UTXO/REST chains (BTC, XRP, TRON)
# are intentionally omitted until they earn their own adapter.
_CHAINS: dict[str, _ChainMeta] = {
    "ethereum": _ChainMeta("ethereum-mainnet", "evm", "ETH", 18),
    "base": _ChainMeta("base-mainnet", "evm", "ETH", 18),
    "polygon": _ChainMeta("polygon-mainnet", "evm", "POL", 18),
    "arbitrum": _ChainMeta("arbitrum-one-mainnet", "evm", "ETH", 18),
    "optimism": _ChainMeta("optimism-mainnet", "evm", "ETH", 18),
    "bsc": _ChainMeta("bsc-mainnet", "evm", "BNB", 18),
    "avalanche": _ChainMeta("avalanche-mainnet", "evm", "AVAX", 18),
    "celo": _ChainMeta("celo-mainnet", "evm", "CELO", 18),
    "gnosis": _ChainMeta("gnosis-mainnet", "evm", "XDAI", 18),
    "fantom": _ChainMeta("fantom-mainnet", "evm", "FTM", 18),
    "cronos": _ChainMeta("cronos-mainnet", "evm", "CRO", 18),
    "unichain": _ChainMeta("unichain-mainnet", "evm", "ETH", 18),
    "zksync": _ChainMeta("zksync-mainnet", "evm", "ETH", 18),
    "flare": _ChainMeta("flare-mainnet", "evm", "FLR", 18),
    "sonic": _ChainMeta("sonic-mainnet", "evm", "S", 18),
    "solana": _ChainMeta("solana-mainnet", "solana", "SOL", 9),
}

_EVM_CHAINS: tuple[str, ...] = tuple(k for k, v in _CHAINS.items() if v.family == "evm")

# Uniswap V3 NonfungiblePositionManager per chain (for uncollected-fee reads).
# Deterministic 0xC364… on most chains; Base deployed a different address.
_NFPM: dict[str, str] = {
    "ethereum": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    "arbitrum": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    "optimism": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    "polygon": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
    "base": "0x03a520b32C04BF3bEEf7BEb72E919cf822Ed34f1",
}
# positions(uint256) selector on the NonfungiblePositionManager.
_NFPM_POSITIONS_SELECTOR = "0x99fbab88"


def is_solana_address(address: str) -> bool:
    """True for a plausible Solana (base58, 32–44 char) public key."""
    return 32 <= len(address) <= 44 and all(c in _BASE58 for c in address)


@dataclass(frozen=True)
class NativeBalance:
    """A single chain's native-coin balance for an address."""

    chain: str
    symbol: str
    address: str
    balance: float  # native units (e.g. ETH, SOL)
    raw: int  # smallest unit (wei / lamports)


class TatumClient:
    """Anonymous native-balance lookups across Tatum's RPC gateways."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = _TIMEOUT,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.getenv("TATUM_API_KEY")
        self._http = http_client
        self._timeout = timeout

    def is_configured(self) -> bool:
        return bool(self._api_key)

    @staticmethod
    def supported_chains() -> tuple[str, ...]:
        """Chain keys this client can resolve a native balance for."""
        return tuple(_CHAINS)

    @staticmethod
    def chain_info(chain: str) -> dict[str, Any] | None:
        """Public metadata for a supported chain, or ``None`` if unsupported."""
        meta = _CHAINS.get(chain.lower())
        if meta is None:
            return None
        return {"chain": chain.lower(), "family": meta.family, "symbol": meta.symbol}

    def _rpc(self, meta: _ChainMeta, method: str, params: list[Any]) -> Any | None:
        """Issue a JSON-RPC call to a chain gateway; ``None`` on any failure."""
        if not self.is_configured():
            return None
        url = _GATEWAY.format(subdomain=meta.subdomain)
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        headers = {"x-api-key": self._api_key or ""}
        client = self._http or httpx.Client(timeout=self._timeout)
        try:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError):
            return None
        finally:
            if self._http is None:
                client.close()
        if not isinstance(data, dict) or "result" not in data:
            return None
        return data["result"]

    def native_balance(self, chain: str, address: str) -> NativeBalance | None:
        """Native-coin balance for ``address`` on ``chain`` (``None`` if absent/invalid)."""
        meta = _CHAINS.get(chain.lower())
        if meta is None:
            return None

        if meta.family == "evm":
            if not is_evm_address(address):
                return None
            result = self._rpc(meta, "eth_getBalance", [address, "latest"])
            if not isinstance(result, str):
                return None
            try:
                raw = int(result, 16)
            except ValueError:
                return None
        elif meta.family == "solana":
            if not is_solana_address(address):
                return None
            result = self._rpc(meta, "getBalance", [address])
            # Solana wraps the lamport count: {"context": ..., "value": <int>}.
            raw_val = result.get("value") if isinstance(result, dict) else result
            if not isinstance(raw_val, int) or isinstance(raw_val, bool):
                return None
            raw = raw_val
        else:  # pragma: no cover - guarded by _CHAINS contents
            return None

        return NativeBalance(
            chain=chain.lower(),
            symbol=meta.symbol,
            address=address,
            balance=raw / (10**meta.decimals),
            raw=raw,
        )

    def multi_chain_native(
        self, address: str, chains: tuple[str, ...] | None = None
    ) -> dict[str, NativeBalance]:
        """Native balances for an EVM ``address`` across EVM chains (non-zero only)."""
        if not is_evm_address(address):
            return {}
        out: dict[str, NativeBalance] = {}
        for chain in chains or _EVM_CHAINS:
            meta = _CHAINS.get(chain.lower())
            if meta is None or meta.family != "evm":
                continue
            balance = self.native_balance(chain, address)
            if balance is not None and balance.raw > 0:
                out[chain.lower()] = balance
        return out

    def eth_call(self, chain: str, to: str, data: str) -> str | None:
        """Raw ``eth_call`` against ``to`` with calldata ``data`` (hex result or None)."""
        meta = _CHAINS.get(chain.lower())
        if meta is None or meta.family != "evm":
            return None
        result = self._rpc(meta, "eth_call", [{"to": to, "data": data}, "latest"])
        return result if isinstance(result, str) else None

    def nfpm_tokens_owed(
        self, chain: str, token_id: str | int, *, decimals0: int = 18, decimals1: int = 18
    ) -> tuple[float, float] | None:
        """Uncollected fees (``tokensOwed0/1``) for a Uniswap V3 position NFT.

        Reads ``NonfungiblePositionManager.positions(tokenId)`` via ``eth_call``
        and decodes the last two return words (``tokensOwed0``, ``tokensOwed1``),
        scaled to human units. These are the fees owed as of the position's last
        interaction. Returns ``None`` on an unsupported chain or any RPC failure.
        """
        nfpm = _NFPM.get(chain.lower())
        if nfpm is None:
            return None
        try:
            token = int(token_id)
        except (TypeError, ValueError):
            return None
        result = self.eth_call(chain, nfpm, f"{_NFPM_POSITIONS_SELECTOR}{token:064x}")
        if result is None:
            return None
        body = result[2:] if result.startswith("0x") else result
        words = [body[i * 64 : (i + 1) * 64] for i in range(len(body) // 64)]
        if len(words) < 12:  # positions() returns 12 words; tokensOwed are [10], [11]
            return None
        try:
            owed0 = int(words[10], 16)
            owed1 = int(words[11], 16)
        except ValueError:
            return None
        return owed0 / (10**decimals0), owed1 / (10**decimals1)


__all__ = ["NativeBalance", "TatumClient", "is_solana_address"]
