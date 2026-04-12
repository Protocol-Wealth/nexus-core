# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Protocol Wealth, LLC and contributors.
"""FinBERT wrapper for financial sentiment classification.

FinBERT (Apache 2.0) is a BERT model fine-tuned on financial text. This
wrapper provides:

    1. A single ``classify()`` entry point that returns a typed result
       instead of raw HuggingFace pipeline output.
    2. Optional PII-redaction hook (caller supplies redactor) — critical
       when running sentiment on advisor notes or meeting transcripts.
    3. Batch classification for long document runs.

Attribution:
    FinBERT — Copyright 2022 Prosus AI (Apache 2.0).
    https://github.com/ProsusAI/finBERT

Install::

    pip install nexus-core[ai]

The ``ai`` extra pulls in torch + transformers (~2GB). For lightweight
deployments consider calling a hosted inference endpoint instead.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

try:
    from transformers import pipeline as hf_pipeline
except ImportError:  # pragma: no cover
    hf_pipeline = None  # type: ignore[assignment]


@dataclass
class SentimentResult:
    """Output of a single sentiment classification.

    Attributes:
        label: ``positive``, ``negative``, or ``neutral``.
        score: Confidence in ``[0, 1]``.
        text: The input text (possibly redacted) for audit traceability.
        model: Identifier of the underlying model.
    """

    label: str
    score: float
    text: str
    model: str


#: Default model. Override by passing ``model_name`` to ``FinBERTClassifier``.
DEFAULT_MODEL = "ProsusAI/finbert"


#: A PII redactor takes raw text and returns redacted text. Pass None to skip.
Redactor = Callable[[str], str]


class FinBERTClassifier:
    """Stateful FinBERT classifier. Loads the model lazily on first use."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL,
        redactor: Redactor | None = None,
        device: int = -1,
    ) -> None:
        self.model_name = model_name
        self.redactor = redactor
        self.device = device
        self._pipeline: Any = None

    def _ensure_loaded(self) -> None:
        if self._pipeline is not None:
            return
        if hf_pipeline is None:
            raise ImportError(
                "transformers not installed. Install with: pip install nexus-core[ai]"
            )
        self._pipeline = hf_pipeline(
            "sentiment-analysis",
            model=self.model_name,
            device=self.device,
        )

    def classify(self, text: str) -> SentimentResult:
        """Classify a single text string."""
        self._ensure_loaded()
        redacted = self.redactor(text) if self.redactor else text
        output = self._pipeline(redacted, truncation=True)
        record = output[0] if isinstance(output, list) else output
        return SentimentResult(
            label=str(record["label"]).lower(),
            score=float(record["score"]),
            text=redacted,
            model=self.model_name,
        )

    def classify_batch(self, texts: list[str]) -> list[SentimentResult]:
        """Classify a list of texts. Runs redaction per-item (if configured)."""
        self._ensure_loaded()
        redacted_texts = [self.redactor(t) for t in texts] if self.redactor else list(texts)
        outputs = self._pipeline(redacted_texts, truncation=True)
        if not isinstance(outputs, list):
            outputs = [outputs]
        return [
            SentimentResult(
                label=str(record["label"]).lower(),
                score=float(record["score"]),
                text=text,
                model=self.model_name,
            )
            for record, text in zip(outputs, redacted_texts, strict=True)
        ]


def classify(text: str, *, redactor: Redactor | None = None) -> SentimentResult:
    """One-shot classification. Loads a fresh model each call — avoid for batch."""
    return FinBERTClassifier(redactor=redactor).classify(text)


__all__ = ["DEFAULT_MODEL", "FinBERTClassifier", "Redactor", "SentimentResult", "classify"]
