# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""JSON-Schema for the RothConversionAnalysis output, derived from the dataclasses.

The output half of the planning ABI is as load-bearing as the input. Rather than
hand-maintain a second JSON file that could silently drift from
:mod:`.analysis`, this module *generates* the Draft-2020-12 schema directly from
the result dataclasses — so the dataclasses remain the single source of truth and
drift is structurally impossible. ``pw-api`` (and any adopter) can validate engine
responses against :func:`roth_conversion_analysis_schema`.

Handles exactly the type vocabulary the result dataclasses use: nested
dataclasses, the JSON primitives (``int``/``float``/``str``/``bool``),
``tuple[T, ...]`` homogeneous arrays, and ``T | None`` optionals. It deliberately
does not implement a general type→schema mapping.
"""

from __future__ import annotations

import dataclasses
import types
from typing import Any, Union, get_args, get_origin, get_type_hints

from .analysis import RothConversionAnalysis

_PRIMITIVES: dict[type, str] = {
    bool: "boolean",  # before int: bool is a subclass of int
    int: "integer",
    float: "number",
    str: "string",
}


def _is_optional(annotation: Any) -> tuple[bool, Any]:
    """If ``annotation`` is ``X | None``, return ``(True, X)``; else ``(False, ann)``."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1 and len(get_args(annotation)) == 2:
            return True, args[0]
    return False, annotation


def _allow_null(schema: dict[str, Any]) -> dict[str, Any]:
    """Widen a generated schema to also permit ``null``."""
    t = schema.get("type")
    if isinstance(t, str):
        return {**schema, "type": [t, "null"]}
    return {"anyOf": [schema, {"type": "null"}]}


def _type_to_schema(annotation: Any) -> dict[str, Any]:
    optional, inner = _is_optional(annotation)
    if optional:
        return _allow_null(_type_to_schema(inner))

    if dataclasses.is_dataclass(inner) and isinstance(inner, type):
        return _dataclass_to_schema(inner)

    origin = get_origin(inner)
    if origin is tuple:
        args = get_args(inner)
        if len(args) == 2 and args[1] is Ellipsis:
            return {"type": "array", "items": _type_to_schema(args[0])}
        raise TypeError(f"only homogeneous tuple[T, ...] is supported, got {inner!r}")

    if inner in _PRIMITIVES:
        return {"type": _PRIMITIVES[inner]}

    raise TypeError(f"unsupported annotation in result schema: {inner!r}")


def _dataclass_to_schema(cls: type) -> dict[str, Any]:
    hints = get_type_hints(cls)
    properties = {f.name: _type_to_schema(hints[f.name]) for f in dataclasses.fields(cls)}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


def roth_conversion_analysis_schema() -> dict[str, Any]:
    """Draft-2020-12 JSON-Schema for :class:`RothConversionAnalysis`."""
    schema = _dataclass_to_schema(RothConversionAnalysis)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://nexusmcp.site/schemas/roth-conversion-analysis-1.0.0.json"
    schema["title"] = "RothConversionAnalysis"
    schema["description"] = (
        "PII-free output of analyze_roth_conversion / sequence_conversions. "
        "Generated from the nexus-core result dataclasses (single source of truth)."
    )
    return schema


__all__ = ["roth_conversion_analysis_schema"]
