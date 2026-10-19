from __future__ import annotations

from dataclasses import dataclass

from bin_finder.models import SceneRecord
from bin_finder.retrieval.models import RankedSegment
from bin_finder.verification.models import VerifiedSegment
from bin_finder.verification.providers import (
    HeuristicContextVerifier,
    VerificationProvider,
)
from bin_finder.verification.scoring import VerificationWeights, verification_score


@dataclass(frozen=True)
class RerankWeights:
    retrieval: float = 0.45
    verification: float = 0.55

    def validate(self) -> None:
        if self.retrieval < 0 or self.verification < 0:
            raise ValueError("Rerank weights must be non-negative.")
        if self.retrieval + self.verification <= 0:
            raise ValueError("At least one rerank weight must be positive.")


class VerificationReranker:
    def __init__(
        self,
        provider: VerificationProvider | None = None,
        *,
        top_n: int = 8,
        min_confidence: float = 0.0,
        rerank_weights: RerankWeights | None = None,
        verification_weights: VerificationWeights | None = None,
    ):
        self.provider = provider or HeuristicContextVerifier()
        self.top_n = max(1, int(top_n))
        self.min_confidence = max(0.0, min(1.0, float(min_confidence)))
        self.rerank_weights = rerank_weights or RerankWeights()
        self.rerank_weights.validate()
        self.verification_weights = verification_weights or VerificationWeights()
        self.verification_weights.validate()

    def rerank(
        self,
        scene: SceneRecord,
        ranked: list[RankedSegment],
    ) -> list[VerifiedSegment]:
        if not ranked:
            return []

        head = ranked[: self.top_n]
        tail = ranked[self.top_n :]
        units = [item.unit for item in head]

        try:
            verification = self.provider.verify(scene, units)
        except Exception:
            verification = [None for _ in head]
            provider_failed = True
        else:
            provider_failed = len(verification) != len(head)
            if provider_failed:
                verification = [None for _ in head]

        verified_head: list[VerifiedSegment] = []
        for item, result in zip(head, verification):
            base = item.scores.final
            if result is None:
                verified_head.append(
                    VerifiedSegment(
                        segment=item,
                        verification=None,
                        verification_score=None,
                        final_score=base,
                        status="provider-fallback" if provider_failed else "not-verified",
                    )
                )
                continue

            normalized = result.normalized()
            score = verification_score(
                normalized.dimensions,
                weights=self.verification_weights,
            )
            if score is None or normalized.confidence < self.min_confidence:
                verified_head.append(
                    VerifiedSegment(
                        segment=item,
                        verification=normalized,
                        verification_score=score,
                        final_score=base,
                        status="low-confidence",
                    )
                )
                continue

            denominator = (
                self.rerank_weights.retrieval
                + self.rerank_weights.verification
            )
            fused = (
                base * self.rerank_weights.retrieval
                + score * self.rerank_weights.verification
            ) / denominator
            verified_head.append(
                VerifiedSegment(
                    segment=item,
                    verification=normalized,
                    verification_score=score,
                    final_score=round(max(0.0, min(1.0, fused)), 6),
                    status="verified",
                )
            )

        verified_head.sort(
            key=lambda item: (
                -item.final_score,
                -item.segment.scores.final,
                item.segment.unit.start,
            )
        )

        untouched_tail = [
            VerifiedSegment(
                segment=item,
                verification=None,
                verification_score=None,
                final_score=item.scores.final,
                status="outside-top-n",
            )
            for item in tail
        ]
        return [*verified_head, *untouched_tail]
