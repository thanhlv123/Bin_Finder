from __future__ import annotations

from dataclasses import dataclass

from bin_finder.retrieval.models import RankedSegment


def clamp_score(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class VerificationDimensions:
    subject_match: float | None = None
    action_match: float | None = None
    location_match: float | None = None
    object_match: float | None = None
    time_match: float | None = None
    visual_quality: float | None = None
    context_conflict: float | None = None

    def normalized(self) -> "VerificationDimensions":
        return VerificationDimensions(
            subject_match=clamp_score(self.subject_match),
            action_match=clamp_score(self.action_match),
            location_match=clamp_score(self.location_match),
            object_match=clamp_score(self.object_match),
            time_match=clamp_score(self.time_match),
            visual_quality=clamp_score(self.visual_quality),
            context_conflict=clamp_score(self.context_conflict),
        )


@dataclass(frozen=True)
class VerificationResult:
    unit_id: str
    provider: str
    dimensions: VerificationDimensions
    confidence: float = 1.0
    explanation: str = ""

    def normalized(self) -> "VerificationResult":
        return VerificationResult(
            unit_id=self.unit_id,
            provider=self.provider,
            dimensions=self.dimensions.normalized(),
            confidence=clamp_score(self.confidence) or 0.0,
            explanation=self.explanation,
        )


@dataclass(frozen=True)
class VerifiedSegment:
    segment: RankedSegment
    verification: VerificationResult | None
    verification_score: float | None
    final_score: float
    status: str
