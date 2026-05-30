# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Aerodrome Slipstream LP position reader via on-chain RPC (Base, Tatum).

Aerodrome Slipstream is a direct Uniswap V3 fork (concentrated liquidity), so the
``engine.lp`` tick math is reused unchanged. Unlike Uniswap V3 there is no usable
Slipstream position/pool subgraph on The Graph (Aerodrome indexes via Envio), so
this adapter reads state **directly on-chain** through Tatum ``eth_call`` on Base:

    NonfungiblePositionManager.positions(tokenId)  → token0/1, tickSpacing, ticks,
                                                     liquidity, tokensOwed0/1
    CLFactory.getPool(token0, token1, tickSpacing) → pool address
    CLPool.slot0()                                 → sqrtPriceX96, current tick
    ERC20.decimals()/symbol()                      → token metadata

It returns the same :class:`RawV3Position` the Uniswap path produces (so the LP
router reuses ``analyze_uniswap_v3_position``), **plus** the uncollected fees
decoded from the same ``positions`` call. On-chain state cannot supply the
deposit history (→ no impermanent loss) or pool volume/TVL (→ no fee APR); the
route discloses this. Reward APR (AERO gauge emissions) is a separate follow-on.
"""

from __future__ import annotations

import logging

from .tatum import TatumClient
from .thegraph import RawV3Position

logger = logging.getLogger(__name__)

# Aerodrome Slipstream on Base (verified live via NFPM.factory()).
_NFPM = "0x827922686190790b37229fd06084350E74485b72"
_FACTORY = "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a"
_CHAIN = "base"

# Function selectors (4-byte). positions/slot0/decimals/symbol match Uniswap V3;
# getPool differs (int24 tickSpacing arg, not uint24 fee).
_SEL_POSITIONS = "0x99fbab88"  # positions(uint256)
_SEL_GET_POOL = "0x28af8d0b"  # getPool(address,address,int24)
_SEL_SLOT0 = "0x3850c7bd"  # slot0()
_SEL_DECIMALS = "0x313ce567"  # decimals()
_SEL_SYMBOL = "0x95d89b41"  # symbol()
_MASK256 = (1 << 256) - 1


def _words(hexstr: str) -> list[str]:
    body = hexstr[2:] if hexstr.startswith("0x") else hexstr
    return [body[i * 64 : (i + 1) * 64] for i in range(len(body) // 64)]


def _addr(word: str) -> str:
    return "0x" + word[-40:]


def _i24(word: str) -> int:
    """Decode a sign-extended int24 from a 32-byte word."""
    value = int(word, 16)
    return value - (1 << 256) if value >= (1 << 255) else value


class SlipstreamClient:
    """Aerodrome Slipstream position reader over Tatum ``eth_call`` (Base only).

    Args:
        tatum: A configured :class:`TatumClient` (provides ``eth_call`` + the key).
    """

    def __init__(self, tatum: TatumClient) -> None:
        self._tatum = tatum

    def is_configured(self) -> bool:
        return self._tatum.is_configured()

    def _call(self, to: str, data: str) -> str | None:
        result = self._tatum.eth_call(_CHAIN, to, data)
        return result if result not in (None, "", "0x") else None

    def _decimals(self, token: str) -> int:
        res = self._call(token, _SEL_DECIMALS)
        try:
            return int(res, 16) if res else 18
        except ValueError:
            return 18

    def _symbol(self, token: str) -> str:
        res = self._call(token, _SEL_SYMBOL)
        if not res:
            return token[:8]
        body = res[2:] if res.startswith("0x") else res
        try:
            if len(body) >= 128 and int(body[:64], 16) == 32:  # ABI string
                length = int(body[64:128], 16)
                decoded = bytes.fromhex(body[128 : 128 + length * 2]).decode("utf-8", "replace")
            else:  # bytes32 symbol (older tokens)
                decoded = bytes.fromhex(body[:64]).rstrip(b"\x00").decode("utf-8", "replace")
        except ValueError:
            return token[:8]
        return decoded.strip() or token[:8]

    def fetch_position(self, token_id: str) -> tuple[RawV3Position, float, float] | None:
        """Read a Slipstream position on-chain → ``(RawV3Position, owed0, owed1)``.

        ``None`` if unconfigured, the position/pool can't be read, or any call
        fails. ``deposited*`` and pool TVL/volume are 0 (unavailable on-chain) so
        the engine yields no IL and a 0 fee-APR estimate, as intended.
        """
        if not self.is_configured():
            return None
        try:
            token = int(token_id)
        except (TypeError, ValueError):
            return None

        pos = self._call(_NFPM, f"{_SEL_POSITIONS}{token:064x}")
        words = _words(pos) if pos else []
        if len(words) < 12:
            return None
        token0, token1 = _addr(words[2]), _addr(words[3])
        tick_spacing = _i24(words[4])
        tick_lower, tick_upper = _i24(words[5]), _i24(words[6])
        liquidity = int(words[7], 16)
        owed0_raw, owed1_raw = int(words[10], 16), int(words[11], 16)

        get_pool = (
            f"{_SEL_GET_POOL}{token0[2:].rjust(64, '0')}{token1[2:].rjust(64, '0')}"
            f"{tick_spacing & _MASK256:064x}"
        )
        pool_res = self._call(_FACTORY, get_pool)
        if pool_res is None or int(pool_res, 16) == 0:
            return None
        pool = _addr(_words(pool_res)[0])

        slot0 = _words(self._call(pool, _SEL_SLOT0) or "")
        if len(slot0) < 2:
            return None
        sqrt_price_x96 = int(slot0[0], 16)
        current_tick = _i24(slot0[1])

        decimals0, decimals1 = self._decimals(token0), self._decimals(token1)
        raw = RawV3Position(
            token_id=str(token_id),
            chain=_CHAIN,
            owner="",
            liquidity=liquidity,
            tick_lower=tick_lower,
            tick_upper=tick_upper,
            deposited0=0.0,  # not available on-chain (event-derived) → no IL
            deposited1=0.0,
            pool_address=pool,
            current_tick=current_tick,
            sqrt_price_x96=sqrt_price_x96,
            fee_tier=0,  # Slipstream keys by tickSpacing; fee APR is 0 (no pool volume on-chain)
            pool_liquidity=0,
            pool_tvl_usd=0.0,
            pool_avg_daily_volume_usd=0.0,
            token0_address=token0,
            token1_address=token1,
            token0_symbol=self._symbol(token0),
            token1_symbol=self._symbol(token1),
            decimals0=decimals0,
            decimals1=decimals1,
        )
        return raw, owed0_raw / (10**decimals0), owed1_raw / (10**decimals1)


__all__ = ["SlipstreamClient"]
