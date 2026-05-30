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
- :class:`TatumClient` — Tatum multi-chain RPC client for **anonymous**
  native-coin balances (EVM ``eth_getBalance`` + Solana ``getBalance``) and
  Uniswap V3 ``tokensOwed`` reads via ``eth_call``. Requires ``TATUM_API_KEY``.
- :class:`TheGraphClient` — The Graph gateway reader for Uniswap V3 LP
  positions/pools (feeds ``engine.lp``). Requires ``THEGRAPH_API_KEY``.
- :class:`MerklClient` — keyless Merkl v4 reader for liquidity-incentive
  (reward) APR by pool/vault — the incentive layer on top of LP fee APR.
- :class:`JupiterClient` — keyless Jupiter v3 price client for Solana SPL token
  USD prices (by mint) — the practical price source for tokens outside
  CoinGecko's coin-id catalogue.

All need only the core ``httpx`` dependency. Reference libraries for richer
chain pipelines (``pip install nexus-core[onchain]``):

- Ethereum-ETL (MIT) — https://github.com/blockchain-etl/ethereum-etl
- web3.py (MIT) — https://github.com/ethereum/web3.py
"""

from .debank import DeBankClient, WalletToken, is_evm_address
from .defillama import DefiLlamaClient, DefiProtocol
from .jupiter import JupiterClient, JupiterPrice, is_solana_mint
from .merkl import MerklClient, RewardOpportunity
from .tatum import NativeBalance, TatumClient, is_solana_address
from .thegraph import CHAIN_IDS, RawV3Position, TheGraphClient
from .vaultsfyi import Vault, VaultsFyiClient, chain_alias, is_supported_chain

__all__ = [
    "CHAIN_IDS",
    "DeBankClient",
    "DefiLlamaClient",
    "DefiProtocol",
    "JupiterClient",
    "JupiterPrice",
    "MerklClient",
    "NativeBalance",
    "RawV3Position",
    "RewardOpportunity",
    "TatumClient",
    "TheGraphClient",
    "Vault",
    "VaultsFyiClient",
    "WalletToken",
    "chain_alias",
    "is_evm_address",
    "is_solana_mint",
    "is_solana_address",
    "is_supported_chain",
]
