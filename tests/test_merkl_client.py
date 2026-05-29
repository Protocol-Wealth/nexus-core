# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Tests for the keyless Merkl v4 reward-incentive client (hermetic)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from nexus_core.data.onchain import MerklClient

_POOL = "0xPoolAddressABC"
_OPPS = [
    {
        "identifier": _POOL,
        "name": "Reward A",
        "chainId": 1,
        "apr": 3.27,
        "tvl": 1_000_000,
        "protocol": {"name": "morpho"},
        "status": "LIVE",
    },
    {
        "identifier": _POOL.lower(),  # second campaign on same pool, higher apr
        "name": "Reward B",
        "chainId": 1,
        "apr": 5.5,
        "tvl": 500_000,
        "protocol": {"name": "uniswap"},
        "status": "LIVE",
    },
    {
        "identifier": "0xOtherPool",
        "name": "Other",
        "chainId": 1,
        "apr": 9.9,
        "status": "LIVE",
    },
]


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_opportunities_parse_and_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v4/opportunities"
        assert request.url.params["chainId"] == "1"
        assert request.url.params["status"] == "LIVE"
        return httpx.Response(200, json=_OPPS)

    opps = MerklClient(http_client=_client(handler)).opportunities(1)
    assert len(opps) == 3
    assert opps[0].apr == pytest.approx(3.27)
    assert opps[0].protocol == "morpho"


def test_reward_apr_for_pool_returns_max_case_insensitive() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_OPPS)

    # Two campaigns on the pool (3.27 and 5.5) → max, case-insensitive match.
    apr = MerklClient(http_client=_client(handler)).reward_apr_for_pool(1, _POOL.upper())
    assert apr == pytest.approx(5.5)


def test_reward_apr_no_match_returns_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_OPPS)

    assert MerklClient(http_client=_client(handler)).reward_apr_for_pool(1, "0xNope") == 0.0


def test_empty_pool_address_returns_zero() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no request needed for empty address")

    assert MerklClient(http_client=_client(handler)).reward_apr_for_pool(1, "") == 0.0


def test_non_list_payload_degrades() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not": "a list"})

    assert MerklClient(http_client=_client(handler)).opportunities(1) == []


def test_http_error_degrades() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="err")

    assert MerklClient(http_client=_client(handler)).reward_apr_for_pool(1, _POOL) == 0.0
