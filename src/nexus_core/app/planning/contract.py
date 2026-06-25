# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Wire contract for the planning tool gateway.

Defines the versioned contract shared with the pwplan-core consumer:

- ``CONTRACT_VERSION`` — echoed in every successful response; the client rejects
  a mismatch.
- PII rejection — the public engine is **PII-free by construction**. It accepts
  only de-identified planning inputs (age, not date of birth). Any identity-
  shaped key anywhere in a request body is rejected fail-closed.
- Error types — :class:`PlanningInputError` (HTTP 400, malformed/invalid input)
  and :class:`PlanningInfeasibleError` (HTTP 422, a well-formed but unsatisfiable
  plan). Their ``public_message`` values are surfaced in the consumer's UI, so
  they are written to be human-readable and defensively sanitized.
"""

from __future__ import annotations

from typing import Any

#: The planning contract version. Bump on any breaking request/response change.
CONTRACT_VERSION = "0.1.0"

_MAX_PUBLIC_ERROR_CHARS = 500
_TRACEBACK_MARKERS = (
    "Traceback (most recent call last):",
    "\n  File ",
    "\n    ",
)

#: Identity-shaped keys the engine refuses (case-insensitive, separators ignored).
#: Planning is done on age, not date of birth; no name, contact, or government id
#: is ever needed.
IDENTITY_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "firstname",
        "lastname",
        "fullname",
        "dob",
        "dateofbirth",
        "birthdate",
        "ssn",
        "taxid",
        "email",
        "phone",
        "address",
    }
)


def _public_error_message(message: object, *, fallback: str) -> str:
    if not isinstance(message, str):
        return fallback
    if any(marker in message for marker in _TRACEBACK_MARKERS):
        return fallback
    text = " ".join(message.split()).strip()
    if not text:
        return fallback
    if len(text) > _MAX_PUBLIC_ERROR_CHARS:
        return f"{text[: _MAX_PUBLIC_ERROR_CHARS - 3].rstrip()}..."
    return text


class PlanningInputError(Exception):
    """A malformed or invalid request (maps to HTTP 400)."""

    def __init__(self, message: str) -> None:
        self.public_message = _public_error_message(message, fallback="invalid planning request")
        super().__init__(self.public_message)


class PlanningInfeasibleError(Exception):
    """A well-formed request whose plan cannot be satisfied (maps to HTTP 422)."""

    def __init__(self, message: str) -> None:
        self.public_message = _public_error_message(message, fallback="planning request infeasible")
        super().__init__(self.public_message)


def find_identity_keys(payload: Any) -> list[str]:
    """Return any identity-shaped keys found anywhere in ``payload``.

    Recurses through nested dicts and lists. Matching is case-insensitive and
    ignores non-alphanumeric separators (so ``date_of_birth`` and ``dateOfBirth``
    both match ``dateofbirth``). The original key spelling is returned for the
    error message.
    """
    found: list[str] = []
    _scan(payload, found)
    return found


def _normalise_key(key: str) -> str:
    return "".join(ch for ch in key.lower() if ch.isalnum())


def _scan(node: Any, found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(key, str) and _normalise_key(key) in IDENTITY_KEYS:
                found.append(key)
            _scan(value, found)
    elif isinstance(node, list):
        for item in node:
            _scan(item, found)


__all__ = [
    "CONTRACT_VERSION",
    "IDENTITY_KEYS",
    "PlanningInfeasibleError",
    "PlanningInputError",
    "find_identity_keys",
]
