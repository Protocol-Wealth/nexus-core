# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Planning tool handlers + registry.

Each handler takes the parsed request body (a ``dict``) and returns the response
payload (a ``dict``) — the gateway adds ``contractVersion`` and maps exceptions
to HTTP status codes. Handlers validate their own inputs and raise
:class:`PlanningInputError` / :class:`PlanningInfeasible` with human-readable
messages (the consumer shows them verbatim).

Tool ids are the wire contract and must match the consumer exactly. Tools are
added here as each iteration lands; the gateway 404s ids that aren't registered.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

from ...engine.planning import GlidePathShape, compute_glide_path
from .contract import PlanningInputError

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _require(body: dict[str, Any], key: str) -> Any:
    if key not in body:
        raise PlanningInputError(f"missing required field '{key}'")
    return body[key]


def _as_int(body: dict[str, Any], key: str) -> int:
    value = _require(body, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise PlanningInputError(f"field '{key}' must be a whole number; got {value!r}")
    return int(value)


def _as_number(body: dict[str, Any], key: str) -> float:
    value = _require(body, key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanningInputError(f"field '{key}' must be a number; got {value!r}")
    return float(value)


def _as_str(body: dict[str, Any], key: str) -> str:
    value = _require(body, key)
    if not isinstance(value, str):
        raise PlanningInputError(f"field '{key}' must be a string; got {value!r}")
    return value


def glide_path_tool(body: dict[str, Any]) -> dict[str, Any]:
    """``glide_path`` — equity weight by age across the planning horizon."""
    start = _as_number(body, "startEquityWeight")
    end = _as_number(body, "endEquityWeight")
    shape = _as_str(body, "shape")
    try:
        path = compute_glide_path(
            current_age=_as_int(body, "currentAge"),
            retirement_age=_as_int(body, "retirementAge"),
            horizon_age=_as_int(body, "horizonAge"),
            start_equity_weight=start,
            end_equity_weight=end,
            shape=cast(GlidePathShape, shape),
        )
    except ValueError as exc:
        raise PlanningInputError(str(exc)) from exc
    return {"equityWeightByAge": {str(age): round(weight, 4) for age, weight in path.items()}}


#: Wire-id -> handler. Extend per iteration; ids must match the consumer contract.
TOOL_HANDLERS: dict[str, ToolHandler] = {
    "glide_path": glide_path_tool,
}


def available_tools() -> list[str]:
    """Return the registered planning tool ids, sorted."""
    return sorted(TOOL_HANDLERS)


__all__ = ["TOOL_HANDLERS", "ToolHandler", "available_tools", "glide_path_tool"]
