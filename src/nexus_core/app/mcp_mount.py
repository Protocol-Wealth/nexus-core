# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""MCP-over-HTTP sub-application for the FastAPI deployment.

Isolates the optional ``fastmcp`` dependency: importing this module is always
safe, but :func:`build_mcp_app` raises :class:`ImportError` if ``fastmcp`` is
not installed. The application factory treats that as "serve REST only".
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from ..data.derivatives import DeribitClient
from ..data.onchain import DefiLlamaClient
from ..data.providers import MacroDataProvider, MarketDataProvider
from ..disclaimers import MC_DISCLAIMER, TERSE
from ..engine.regime import RegimeEngine
from ..mcp.server import build_server
from .planning.contract import (
    CONTRACT_VERSION as PLANNING_CONTRACT_VERSION,
)
from .planning.contract import (
    PlanningInfeasibleError,
    PlanningInputError,
    find_identity_keys,
)
from .planning.tools import build_tool_handlers
from .scoring import build_scoring_context, build_scoring_framework

#: One-line native-MCP descriptions for the planning tools. The full request
#: shapes live in the pwplan-core wire contract; the tool takes the request as a
#: JSON object in ``body``.
_PLANNING_TOOL_DESCRIPTIONS = {
    "monte_carlo_decumulation": (
        "Monte Carlo retirement decumulation simulation across return models "
        "(incl. live-regime-aware). Pass the planning request as a JSON object in `body`."
    ),
    "glide_path": "Equity-weight glide path by age across the horizon. JSON request object in `body`.",
    "tax_aware_withdrawal": (
        "RMD-first, tax-efficient withdrawal sequencing. JSON request object in `body`."
    ),
    "correlation_matrix": (
        "Real-data return correlation across asset classes (Ledoit-Wolf shrinkage). "
        "JSON request object in `body`."
    ),
    "capital_market_assumptions": (
        "Forward return/volatility/correlation assumptions per asset class. "
        "JSON request object in `body`."
    ),
    "regime_return_generator": (
        "Live macro regime + transition matrix + path cache key for regime-aware "
        "return generation. JSON request object in `body`."
    ),
    "roth_conversion": (
        "Roth conversion calculator: convert-now vs. leave-pre-tax after-tax "
        "comparison with the true incremental (bracket-creep) federal tax and a "
        "breakeven retirement rate. JSON request object in `body`."
    ),
    "sequence_of_returns_stress": (
        "Sequence-of-returns stress: replay one return set worst-first / "
        "best-first / as-given to isolate the ordering effect on a withdrawal "
        "plan. JSON request object in `body`."
    ),
    "rmd": (
        "Required Minimum Distribution: IRS Uniform Lifetime Table RMD for a "
        "traditional account given age + prior-year-end balance. JSON request "
        "object in `body`."
    ),
    "tax_bracket_headroom": (
        "Tax-bracket headroom / Roth-fill: marginal bracket + ordinary-income "
        "room before the next federal rate (or up to a target rate). JSON request "
        "object in `body`."
    ),
    "social_security_claiming": (
        "Social Security claiming-age: benefit at each claim age 62-70 from the "
        "PIA + breakeven ages between strategies. JSON request object in `body`."
    ),
    "regime_conditioned_swr": (
        "Regime-conditioned safe withdrawal rate: a base SWR adjusted for the "
        "LIVE macro regime (illustrative overlay). JSON request object in `body`."
    ),
    "portfolio_xray": (
        "Portfolio X-ray: regime-aware structural diagnostics (concentration, "
        "diversification, tax-location mix, and EMF regime sensitivity vs the live "
        "regime) for a de-identified portfolio. JSON request object in `body`."
    ),
    "fire": (
        "FIRE / Coast-FIRE: the FIRE number (spend ÷ safe withdrawal rate), the "
        "coast number needed today, and years/age to financial independence with "
        "level contributions. JSON request object in `body`."
    ),
    "risk_metrics": (
        "Return-series risk metrics: annualized return/volatility, Sharpe, Sortino, "
        "max drawdown, and historical VaR/CVaR for a supplied periodic return "
        "series. JSON request object in `body`."
    ),
    "rebalance": (
        "Rebalance-to-target: per-asset drift from target weights and the "
        "self-financing trade list (with one-way turnover) for the blended "
        "portfolio. JSON request object in `body`."
    ),
    "irmaa_headroom": (
        "IRMAA headroom: room before the next *projected* Medicare Part B+D "
        "income-surcharge cliff in a target premium year (the 2-year MAGI "
        "lookback), with a safety buffer below the projected floor. Pass "
        "target_premium_year, magi_ex_conversion, per_person, inflation, buffer, "
        "and either irmaa_table or filing_status. JSON request object in `body`."
    ),
    "analyze_roth_conversion": (
        "Composite multi-year Roth-conversion analysis: sizes the conversion under "
        "BOTH the tax-bracket ceiling and the projected-IRMAA ceiling (IRMAA "
        "usually binds for a 60-something retiree), with pro-rata basis, the "
        "Social-Security torpedo, LTCG stacking, NIIT, state treatment, the "
        "liquidity gate, and the do-nothing RMD drag. Pass a PII-free "
        "PlanningContract under `contract` (+ optional injected tables). JSON "
        "request object in `body`."
    ),
    "sequence_conversions": (
        "Multi-year Roth-conversion sequencer: the per-year split + totals across "
        "the intent years against both ceilings (the roll-up only; "
        "analyze_roth_conversion returns the same split with full detail). Pass a "
        "PlanningContract under `contract`. JSON request object in `body`."
    ),
}


def _build_planning_mcp_tools(
    market: MarketDataProvider, regime_engine: RegimeEngine
) -> list[tuple[str, str, Callable[[dict[str, Any]], str]]]:
    """Adapt the planning gateway handlers into native-MCP tool callables.

    Reuses :func:`build_tool_handlers` verbatim (zero logic duplication) and
    mirrors the REST gateway's contract: a fail-closed PII scan, ``contractVersion``
    echo, and human-readable validation errors surfaced as ``ToolError`` (the
    canonical MCP error channel). Returned as ``(name, description, fn)`` triples
    for :func:`build_server`'s generic ``extra_tools`` registration.
    """
    from fastmcp.exceptions import ToolError

    handlers = build_tool_handlers(market=market, regime_engine=regime_engine)
    specs: list[tuple[str, str, Callable[[dict[str, Any]], str]]] = []

    def _adapt(
        handler: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> Callable[[dict[str, Any]], str]:
        def _run(body: dict[str, Any]) -> str:
            if not isinstance(body, dict):
                raise ToolError("request body must be a JSON object")
            offenders = find_identity_keys(body)
            if offenders:
                raise ToolError(
                    "identity fields are not accepted by this PII-free engine: "
                    f"{', '.join(sorted(set(offenders)))}. "
                    "Planning uses age, not date of birth."
                )
            try:
                payload = handler(body)
            except (PlanningInputError, PlanningInfeasibleError) as exc:
                raise ToolError(str(exc)) from exc
            payload.setdefault("contractVersion", PLANNING_CONTRACT_VERSION)
            payload.setdefault("disclaimer", MC_DISCLAIMER)
            return json.dumps(payload, indent=2)

        return _run

    for tool_id, handler in handlers.items():
        specs.append((tool_id, _PLANNING_TOOL_DESCRIPTIONS[tool_id], _adapt(handler)))
    return specs


def build_configured_server(
    regime_engine: RegimeEngine,
    market: MarketDataProvider,
    macro: MacroDataProvider,
) -> Any:
    """Build the fully-wired nexus-core MCP server (shared by HTTP + stdio).

    Wires the full educational tool set — regime (current_regime, regime_signals),
    the EMF ``score_asset`` (sharing the REST ``/api/score`` context builder +
    framework, so MCP and REST return identical scores), market quotes/history,
    FRED economic series, DefiLlama TVL, the options pricing/overlay + Deribit
    crypto-option tools, and the 19 planning tools (monte_carlo_decumulation,
    glide_path, tax_aware_withdrawal, correlation_matrix, regime_return_generator,
    capital_market_assumptions, roth_conversion, sequence_of_returns_stress, rmd,
    tax_bracket_headroom, social_security_claiming, regime_conditioned_swr,
    portfolio_xray, fire, risk_metrics, rebalance, plus the composite Roth/IRMAA
    trio analyze_roth_conversion, sequence_conversions, irmaa_headroom) — the same
    handlers the REST planning gateway serves, so the MCP transport and
    ``POST /mcp/tools/{id}`` stay in lock-step.

    Both transports build from here so the stdio server (``nexus-core mcp``,
    for Claude Desktop) and the HTTP server (``/mcp``) expose an identical set
    of tools.

    Args:
        regime_engine: Configured regime engine.
        market: Market data provider (scoring context + market/options tools).
        macro: Macro data provider (FRED economic-series tool).

    Raises:
        ImportError: If ``fastmcp`` is not installed (``build_server`` guards).
    """
    return build_server(
        name="nexus-core",
        regime_engine=regime_engine,
        scoring_framework=build_scoring_framework(),
        score_context_factory=lambda ticker: build_scoring_context(
            ticker, market=market, regime_engine=regime_engine
        ),
        market=market,
        macro=macro,
        deribit=DeribitClient(),
        defillama=DefiLlamaClient(),
        disclaimer=TERSE,
        extra_tools=_build_planning_mcp_tools(market, regime_engine),
    )


def build_mcp_app(
    regime_engine: RegimeEngine,
    market: MarketDataProvider,
    macro: MacroDataProvider,
) -> Any:
    """Return a Starlette ASGI app exposing the nexus-core MCP server over HTTP.

    The returned app carries a ``.lifespan`` the parent FastAPI app must adopt
    for the MCP session manager to initialise. See :func:`build_configured_server`
    for the tool set.

    Raises:
        ImportError: If ``fastmcp`` is not installed (``build_server`` guards).
    """
    return build_configured_server(regime_engine, market, macro).http_app(path="/")


__all__ = ["build_configured_server", "build_mcp_app"]
