# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Onchain-accounting tool gateway (epic nexus-core#248).

PII-free cost-basis / decoding / price-history / realized-PnL tools over a
de-identified event ledger. Phase 0 ships the gateway scaffold, the contract
version, and the event-ledger schema.
"""

from __future__ import annotations

from .contract import ACCOUNTING_CONTRACT_VERSION, EventLedger
from .gateway import build_accounting_router

__all__ = ["ACCOUNTING_CONTRACT_VERSION", "EventLedger", "build_accounting_router"]
