# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""FastMCP server scaffold for nexus-core.

Wraps the regime and scoring engines as MCP tools so Claude, Cursor, and any
other MCP-compatible client can call them directly.

The minimum to stand up a server:

    from nexus_core.mcp.server import build_server
    from nexus_core.engine.regime import RegimeEngine

    engine = RegimeEngine(market_data=my_market, macro_data=my_macro)
    server = build_server(regime_engine=engine)
    server.run()

This is a reference scaffold — production deployments typically add
authentication (OAuth resource server), rate limiting, audit logging, and
response filtering. The ``filters`` parameter lets you wire those in without
modifying this module.

Requires ``fastmcp>=2.0.0``. Install via::

    pip install nexus-core[mcp]
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Protocol

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover
    FastMCP = None  # type: ignore[assignment,misc]

from ...engine.regime import RegimeEngine, RegimeResult
from ...engine.scoring import ScoringFramework, format_structured


class ResponseFilter(Protocol):
    """Post-process a tool response before it leaves the server.

    Typical uses: PII redaction, tier-based response scrubbing, audit logging.
    Filters are composable — register multiple and they run in sequence.
    """

    def __call__(
        self,
        tool_name: str,
        response: dict[str, Any],
        *,
        auth_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


def build_server(
    *,
    name: str = "nexus-core",
    regime_engine: RegimeEngine | None = None,
    scoring_framework: ScoringFramework | None = None,
    score_context_factory: Callable[[str], Any] | None = None,
    filters: list[ResponseFilter] | None = None,
    disclaimer: str | None = None,
) -> Any:
    """Build a FastMCP server with regime + scoring tools.

    Args:
        name: MCP server name.
        regime_engine: Pre-configured ``RegimeEngine``. If None, regime tools
            are not registered.
        scoring_framework: Pre-configured ``ScoringFramework``. If None,
            scoring tools are not registered.
        score_context_factory: Callable mapping a ticker to a scoring context.
            Required if ``scoring_framework`` is passed.
        filters: Response post-processors applied before return.
        disclaimer: Appended to every financial-content tool response. Keep
            this aligned with your regulator's disclosure requirements.

    Returns:
        A configured ``FastMCP`` instance. Call ``.run()`` to start.
    """
    if FastMCP is None:
        raise ImportError("fastmcp is required. Install with: pip install nexus-core[mcp]")

    mcp = FastMCP(name)
    filters = filters or []
    disclaimer = disclaimer or (
        "For educational and research purposes only. Not investment advice. "
        "Past performance is not indicative of future results. Consult a "
        "qualified advisor before making investment decisions."
    )

    # --------------------------- Regime tools ---------------------------

    if regime_engine is not None:

        @mcp.tool()
        def current_regime() -> str:
            """Get the current macro regime classification.

            Returns the regime code, confidence, days in regime, and the
            rationale supporting the classification.
            """
            result = regime_engine.classify()
            response = _serialize_regime(result, disclaimer)
            response = _apply_filters("current_regime", response, filters, {})
            return json.dumps(response, indent=2)

        @mcp.tool()
        def regime_signals() -> str:
            """Get the raw signal readings used for regime classification."""
            signals = regime_engine.fetch_signals()
            response = {"signals": signals.to_dict(), "disclaimer": disclaimer}
            response = _apply_filters("regime_signals", response, filters, {})
            return json.dumps(response, indent=2)

    # --------------------------- Scoring tools ---------------------------

    if scoring_framework is not None and score_context_factory is not None:

        @mcp.tool()
        def score_asset(ticker: str) -> str:
            """Score an asset using the configured N-check framework.

            Args:
                ticker: Asset identifier (e.g. "AAPL", "BTC-USD").

            Returns tier, passed count, per-check results, and any enhancements.
            """
            ctx = score_context_factory(ticker)
            result = scoring_framework.score(ctx, subject=ticker)
            response = format_structured(result)
            response["disclaimer"] = disclaimer
            response = _apply_filters("score_asset", response, filters, {})
            return json.dumps(response, indent=2)

    return mcp


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


def _apply_filters(
    tool_name: str,
    response: dict[str, Any],
    filters: list[ResponseFilter],
    auth_context: dict[str, Any],
) -> dict[str, Any]:
    for f in filters:
        response = f(tool_name, response, auth_context=auth_context)
    return response


def _serialize_regime(result: RegimeResult, disclaimer: str) -> dict[str, Any]:
    out = result.to_dict()
    out["disclaimer"] = disclaimer
    return out


__all__ = ["ResponseFilter", "build_server"]
