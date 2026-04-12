# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""Financial Sentiment Classification.

Wraps FinBERT for financial sentiment analysis with PII-redacted inputs.

Third-party library:
    - FinBERT (Apache 2.0) — https://github.com/ProsusAI/finBERT

Install with: ``pip install nexus-core[ai]``
"""

from __future__ import annotations

try:
    from .finbert_wrapper import (
        DEFAULT_MODEL,
        FinBERTClassifier,
        Redactor,
        SentimentResult,
        classify,
    )

    __all__ = [
        "DEFAULT_MODEL",
        "FinBERTClassifier",
        "Redactor",
        "SentimentResult",
        "classify",
    ]
except ImportError:  # pragma: no cover
    __all__ = []
