from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from bin_finder.analysis.models import CandidateAnalysis
from bin_finder.models import SceneRecord
from bin_finder.retrieval.lexical import BM25Ranker, exact_phrase_scores
from bin_finder.retrieval.models import RankedSegment, RetrievalScores, RetrievalUnit
from bin_finder.retrieval.providers import (
    NullVisualSimilarityProvider,
    TextSimilarityProvider,
    TokenCosineTextSimilarityProvider,
    VisualSimilarityProvider,
)
from bin_finder.retrieval.segments import (
    analysis_to_units,
    build_scene_query_text,
    exact_phrases,
)


@dataclass(frozen=True)
class ScoreWeights:
    bm25: float = 0.35
    exact: float = 0.15
    text_similarity: float = 0.30
    visual_similarity: float = 0.20

    def validate(self) -> None:
        values = (
            self.bm25,
            self.exact,
            self.text_similarity,
            self.visual_similarity,
        )
        if any(value < 0 for value in values):
            raise ValueError("Retrieval weights must be non-negative.")
        if sum(values) <= 0:
            raise ValueError("At least one retrieval weight must be positive.")


def _clamp(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


def _weighted_average(
    *,
    bm25: float,
    exact: float,
    text_similarity: float | None,
    visual_similarity: float | None,
    weights: ScoreWeights,
) -> float:
    components: list[tuple[float, float]] = [
        (bm25, weights.bm25),
        (exact, weights.exact),
    ]
    if text_similarity is not None:
        components.append((text_similarity, weights.text_similarity))
    if visual_similarity is not None:
        components.append((visual_similarity, weights.visual_similarity))

    denominator = sum(weight for _, weight in components if weight > 0)
    if denominator <= 0:
        return 0.0
    numerator = sum(
        score * weight
        for score, weight in components
        if weight > 0
    )
    return round(max(0.0, min(1.0, numerator / denominator)), 6)


class HybridRetrievalEngine:
    def __init__(
        self,
        *,
        text_provider: TextSimilarityProvider | None = None,
        visual_provider: VisualSimilarityProvider | None = None,
        weights: ScoreWeights | None = None,
    ):
        self.text_provider = text_provider or TokenCosineTextSimilarityProvider()
        self.visual_provider = visual_provider or NullVisualSimilarityProvider()
        self.weights = weights or ScoreWeights()
        self.weights.validate()

    def rank_units(
        self,
        scene: SceneRecord,
        units: Sequence[RetrievalUnit],
        *,
        limit: int | None = None,
    ) -> list[RankedSegment]:
        units = list(units)
        if not units:
            return []

        query = build_scene_query_text(scene)
        documents = [unit.searchable_text for unit in units]
        bm25_scores = BM25Ranker(documents).normalized_scores(query)
        exact_scores = exact_phrase_scores(exact_phrases(scene), documents)
        text_scores = self.text_provider.score(query, documents)
        visual_scores = self.visual_provider.score(query, units)

        if len(text_scores) != len(units):
            raise ValueError(
                "Text similarity provider returned an invalid score count."
            )
        if len(visual_scores) != len(units):
            raise ValueError(
                "Visual similarity provider returned an invalid score count."
            )

        ranked: list[RankedSegment] = []
        for index, unit in enumerate(units):
            text_score = _clamp(text_scores[index])
            visual_score = _clamp(visual_scores[index])
            bm25_score = _clamp(bm25_scores[index]) or 0.0
            exact_score = _clamp(exact_scores[index]) or 0.0
            final = _weighted_average(
                bm25=bm25_score,
                exact=exact_score,
                text_similarity=text_score,
                visual_similarity=visual_score,
                weights=self.weights,
            )
            ranked.append(
                RankedSegment(
                    unit=unit,
                    scores=RetrievalScores(
                        bm25=bm25_score,
                        exact=exact_score,
                        text_similarity=text_score,
                        visual_similarity=visual_score,
                        final=final,
                    ),
                )
            )

        ranked.sort(
            key=lambda item: (
                -item.scores.final,
                -item.scores.bm25,
                item.unit.start,
                item.unit.unit_id,
            )
        )
        if limit is not None:
            return ranked[: max(0, limit)]
        return ranked

    def rank_analysis(
        self,
        scene: SceneRecord,
        analysis: CandidateAnalysis,
        *,
        metadata_text: str = "",
        limit: int | None = None,
    ) -> list[RankedSegment]:
        return self.rank_units(
            scene,
            analysis_to_units(analysis, metadata_text=metadata_text),
            limit=limit,
        )
