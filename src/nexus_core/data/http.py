# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Shared HTTP helper for REST-backed data-provider adapters.

A single place for the "GET JSON, optionally through an injected client"
pattern every REST provider in :mod:`nexus_core.data` uses. The injected-client
seam is what makes the providers hermetically testable with
``httpx.MockTransport`` — no network, no API keys in the test suite.
"""

from __future__ import annotations

from typing import Any

import httpx

#: Default per-request timeout in seconds.
DEFAULT_TIMEOUT = 10.0


def fetch_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    client: httpx.Client | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """GET ``url`` and return the parsed JSON body.

    Args:
        url: Fully-qualified request URL.
        params: Query-string parameters.
        headers: Request headers.
        client: Optional pre-built ``httpx.Client``. Inject one wired to an
            ``httpx.MockTransport`` for hermetic tests. When omitted, a client
            is created and closed for the single request.
        timeout: Per-request timeout in seconds.

    Raises:
        httpx.HTTPError: On transport failure or a non-2xx response. Provider
            adapters are expected to catch this and degrade gracefully.
    """
    if client is not None:
        response = client.get(url, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        return response.json()
    with httpx.Client(timeout=timeout) as owned:
        response = owned.get(url, params=params, headers=headers)
        response.raise_for_status()
        return response.json()


__all__ = ["DEFAULT_TIMEOUT", "fetch_json"]
