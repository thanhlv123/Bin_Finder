from __future__ import annotations

from dataclasses import dataclass

from bin_finder.verification.models import VerificationDimensions


@dataclass(frozen=True)
class VerificationWeights:
    subject_match: float = 0.22
    action_match: float = 0.22
    location_match: float = 0.18
    object_match: float = 0.14
    time_match: float = 0.08
    visual_quality: float = 0.16
    context_conflict_penalty: float = 0.45

    def validate(self) -> None:
        positives = (
            self.subject_match,
            self.action_match,
            self.location_match,
            self.object_match,
            self.time_match,
            self.visual_quality,
        )
        if any(value < 0 for value in positives):
            raise ValueError("Verification weights must be non-negative.")
        if self.context_conflict_penalty < 0:
            raise ValueError("Conflict penalty must be non-negative.")
        if sum(positives) <= 0:
            raise ValueError("At least one positive verification weight is required.")


def verification_score(
    dimensions: VerificationDimensions,
    *,
    weights: VerificationWeights | None = None,
) -> float | None:
    weights = weights or VerificationWeights()
    weights.validate()
    normalized = dimensions.normalized()

    components = (
        (normalized.subject_match, weights.subject_match),
        (normalized.action_match, weights.action_match),
        (normalized.location_match, weights.location_match),
        (normalized.object_match, weights.object_match),
        (normalized.time_match, weights.time_match),
        (normalized.visual_quality, weights.visual_quality),
    )
    available = [
        (score, weight)
        for score, weight in components
        if score is not None and weight > 0
    ]
    if not available:
        return None

    denominator = sum(weight for _, weight in available)
    positive = sum(float(score) * weight for score, weight in available) / denominator
    conflict = normalized.context_conflict or 0.0
    final = positive - conflict * weights.context_conflict_penalty
    return round(max(0.0, min(1.0, final)), 6)
