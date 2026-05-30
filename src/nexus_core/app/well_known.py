# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""``/.well-known/security.txt`` (RFC 9116) for the public deployment.

Served as ``text/plain`` from an in-process route, mirroring how the landing
page and MCP guide are served. The contact + policy mirror the repository's
``SECURITY.md`` exactly (security@protocolwealthllc.com); this only advertises
that channel, it does not introduce different terms.

RFC 9116 requires an ``Expires`` field that must be kept current — a stale
``security.txt`` signals an unmaintained contact. To avoid that failure mode
without a recurring manual step, ``Expires`` is computed at render time as a
rolling window (~180 days out), so it is always fresh.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

#: How far ahead the rolling Expires is set (RFC 9116 recommends < 1 year).
_EXPIRES_DAYS = 180

_CONTACT = "mailto:security@protocolwealthllc.com"
_POLICY = "https://github.com/Protocol-Wealth/nexus-core/blob/main/SECURITY.md"
_CANONICAL = "https://nexusmcp.site/.well-known/security.txt"


def render_security_txt() -> str:
    """Return the RFC 9116 ``security.txt`` body (text/plain).

    ``Expires`` is a rolling ~180-day window computed now, so the file never
    goes stale. Aligned to ``SECURITY.md`` (responsible disclosure to
    security@protocolwealthllc.com).
    """
    expires = (datetime.now(UTC) + timedelta(days=_EXPIRES_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        "# Security contact for nexus-core (https://nexusmcp.site),\n"
        "# operated by Protocol Wealth, LLC. See Policy for the full\n"
        "# responsible-disclosure process. Do not open public issues.\n"
        f"Contact: {_CONTACT}\n"
        f"Expires: {expires}\n"
        "Preferred-Languages: en\n"
        f"Canonical: {_CANONICAL}\n"
        f"Policy: {_POLICY}\n"
    )


__all__ = ["render_security_txt"]
