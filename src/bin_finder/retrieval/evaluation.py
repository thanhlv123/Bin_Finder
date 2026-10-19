from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from bin_finder.models import SceneRecord
from bin_finder.retrieval.engine import HybridRetrievalEngine
from bin_finder.retrieval.models import RetrievalUnit


@dataclass(frozen=True)
class RetrievalEvalCase:
    case_id: str
    scene: SceneRecord
    units: tuple[RetrievalUnit, ...]
    relevant_unit_ids: frozenset[str]


@dataclass(frozen=True)
class RetrievalEvalSummary:
    case_count: int
    top1_accuracy: float
    recall_at_k: float
    mean_reciprocal_rank: float


def evaluate_retrieval(
    engine: HybridRetrievalEngine,
    cases: Sequence[RetrievalEvalCase],
    *,
    k: int = 3,
) -> RetrievalEvalSummary:
    if k <= 0:
        raise ValueError("k must be positive.")
    if not cases:
        return RetrievalEvalSummary(0, 0.0, 0.0, 0.0)

    top1_hits = 0
    recall_hits = 0
    reciprocal_rank_total = 0.0

    for case in cases:
        if not case.relevant_unit_ids:
            raise ValueError(
                f"Evaluation case {case.case_id!r} has no relevant unit ids."
            )
        ranked = engine.rank_units(case.scene, case.units)
        ranked_ids = [item.unit.unit_id for item in ranked]

        if ranked_ids and ranked_ids[0] in case.relevant_unit_ids:
            top1_hits += 1

        if any(unit_id in case.relevant_unit_ids for unit_id in ranked_ids[:k]):
            recall_hits += 1

        for rank, unit_id in enumerate(ranked_ids, start=1):
            if unit_id in case.relevant_unit_ids:
                reciprocal_rank_total += 1.0 / rank
                break

    total = len(cases)
    return RetrievalEvalSummary(
        case_count=total,
        top1_accuracy=round(top1_hits / total, 6),
        recall_at_k=round(recall_hits / total, 6),
        mean_reciprocal_rank=round(reciprocal_rank_total / total, 6),
    )
