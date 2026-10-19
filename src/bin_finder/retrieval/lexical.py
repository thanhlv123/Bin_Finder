from __future__ import annotations

import math
import re
from collections import Counter


_TOKEN_RE = re.compile(r"[A-Za-z0-9À-ỹ]+", re.UNICODE)


def tokenize(value: str) -> list[str]:
    return [token.casefold() for token in _TOKEN_RE.findall(value or "") if len(token) > 1]


class BM25Ranker:
    def __init__(self, documents: list[str], *, k1: float = 1.5, b: float = 0.75):
        self.documents = documents
        self.k1 = k1
        self.b = b
        self.tokens = [tokenize(document) for document in documents]
        self.term_counts = [Counter(tokens) for tokens in self.tokens]
        self.lengths = [len(tokens) for tokens in self.tokens]
        self.avg_length = (
            sum(self.lengths) / len(self.lengths) if self.lengths else 0.0
        )
        self.doc_frequency: Counter[str] = Counter()
        for tokens in self.tokens:
            self.doc_frequency.update(set(tokens))

    def _idf(self, term: str) -> float:
        document_count = len(self.documents)
        if document_count == 0:
            return 0.0
        frequency = self.doc_frequency.get(term, 0)
        return math.log(1.0 + (document_count - frequency + 0.5) / (frequency + 0.5))

    def raw_scores(self, query: str) -> list[float]:
        query_terms = tokenize(query)
        if not query_terms or not self.documents:
            return [0.0 for _ in self.documents]
        scores: list[float] = []
        for counts, length in zip(self.term_counts, self.lengths):
            score = 0.0
            for term in query_terms:
                frequency = counts.get(term, 0)
                if frequency <= 0:
                    continue
                norm = 1.0
                if self.avg_length > 0:
                    norm = 1.0 - self.b + self.b * (length / self.avg_length)
                denominator = frequency + self.k1 * norm
                score += self._idf(term) * ((frequency * (self.k1 + 1.0)) / denominator)
            scores.append(score)
        return scores

    def normalized_scores(self, query: str) -> list[float]:
        raw = self.raw_scores(query)
        maximum = max(raw, default=0.0)
        if maximum <= 0:
            return [0.0 for _ in raw]
        return [round(min(1.0, score / maximum), 6) for score in raw]


def exact_phrase_scores(phrases: tuple[str, ...], documents: list[str]) -> list[float]:
    if not phrases:
        return [0.0 for _ in documents]
    normalized_phrases = [
        " ".join(phrase.casefold().split())
        for phrase in phrases
        if phrase.strip()
    ]
    if not normalized_phrases:
        return [0.0 for _ in documents]
    scores: list[float] = []
    for document in documents:
        haystack = " ".join((document or "").casefold().split())
        matches = sum(1 for phrase in normalized_phrases if phrase in haystack)
        scores.append(round(matches / len(normalized_phrases), 6))
    return scores
