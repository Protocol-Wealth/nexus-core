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
  plan). Their messages are surfaced verbatim in the consumer's UI, so they are
  written to be human-readable.
"""

from __future__ import annotations

from typing import Any

#: The planning contract version. Bump on any breaking request/response change.
CONTRACT_VERSION = "0.1.0"

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


class PlanningInputError(Exception):
    """A malformed or invalid request (maps to HTTP 400)."""


class PlanningInfeasibleError(Exception):
    """A well-formed request whose plan cannot be satisfied (maps to HTTP 422)."""


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
