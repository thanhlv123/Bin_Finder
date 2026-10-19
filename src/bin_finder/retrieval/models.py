from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalUnit:
    unit_id: str
    source_path: str
    start: float
    end: float
    transcript_text: str = ""
    metadata_text: str = ""
    transcript_coverage: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def searchable_text(self) -> str:
        return " ".join(
            part.strip()
            for part in (self.transcript_text, self.metadata_text)
            if part and part.strip()
        ).strip()


@dataclass(frozen=True)
class RetrievalScores:
    bm25: float
    exact: float
    text_similarity: float | None
    visual_similarity: float | None
    final: float


@dataclass(frozen=True)
class RankedSegment:
    unit: RetrievalUnit
    scores: RetrievalScores
