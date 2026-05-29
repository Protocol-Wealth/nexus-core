# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Blockchain / DeFi data integrations.

Concrete clients:

- :class:`DefiLlamaClient` — keyless DefiLlama REST client for protocol-,
  chain-, and stablecoin-level Total Value Locked (TVL). Public on-chain
  *market* data only; no wallet/account/client context.
- :class:`DeBankClient` — DeBank Pro client for **anonymous** EVM wallet
  balances (an arbitrary address → its total USD + token holdings). Public
  on-chain data; no identity, name, or client linkage. Requires ``DEBANK_API_KEY``.

Both need only the core ``httpx`` dependency. Reference libraries for richer
chain pipelines (``pip install nexus-core[onchain]``):

- Ethereum-ETL (MIT) — https://github.com/blockchain-etl/ethereum-etl
- web3.py (MIT) — https://github.com/ethereum/web3.py
"""

from .debank import DeBankClient, WalletToken, is_evm_address
from .defillama import DefiLlamaClient, DefiProtocol

__all__ = [
    "DeBankClient",
    "DefiLlamaClient",
    "DefiProtocol",
    "WalletToken",
    "is_evm_address",
]
