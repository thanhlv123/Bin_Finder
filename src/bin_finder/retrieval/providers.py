from __future__ import annotations

import math
from collections import Counter
from typing import Protocol, Sequence

from bin_finder.retrieval.lexical import tokenize
from bin_finder.retrieval.models import RetrievalUnit


class TextSimilarityProvider(Protocol):
    name: str

    def score(self, query: str, texts: Sequence[str]) -> list[float | None]: ...


class VisualSimilarityProvider(Protocol):
    name: str

    def score(
        self,
        query: str,
        units: Sequence[RetrievalUnit],
    ) -> list[float | None]: ...


class TokenCosineTextSimilarityProvider:
    """Dependency-free baseline; replaceable by an embedding provider later."""

    name = "token-cosine-baseline"

    def score(self, query: str, texts: Sequence[str]) -> list[float | None]:
        query_counts = Counter(tokenize(query))
        query_norm = math.sqrt(sum(value * value for value in query_counts.values()))
        if query_norm <= 0:
            return [0.0 for _ in texts]

        result: list[float | None] = []
        for text in texts:
            doc_counts = Counter(tokenize(text))
            doc_norm = math.sqrt(sum(value * value for value in doc_counts.values()))
            if doc_norm <= 0:
                result.append(0.0)
                continue
            dot = sum(
                query_counts[token] * doc_counts.get(token, 0)
                for token in query_counts
            )
            result.append(
                round(
                    max(0.0, min(1.0, dot / (query_norm * doc_norm))),
                    6,
                )
            )
        return result


class NullVisualSimilarityProvider:
    name = "visual-unavailable"

    def score(
        self,
        query: str,
        units: Sequence[RetrievalUnit],
    ) -> list[float | None]:
        return [None for _ in units]
