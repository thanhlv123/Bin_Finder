from __future__ import annotations

from typing import Protocol, Sequence

from bin_finder.models import SceneRecord
from bin_finder.retrieval.models import RetrievalUnit
from bin_finder.verification.models import (
    VerificationDimensions,
    VerificationResult,
)


class VerificationProvider(Protocol):
    name: str

    def verify(
        self,
        scene: SceneRecord,
        units: Sequence[RetrievalUnit],
    ) -> list[VerificationResult | None]: ...


class NullVerificationProvider:
    name = "vlm-unavailable"

    def verify(
        self,
        scene: SceneRecord,
        units: Sequence[RetrievalUnit],
    ) -> list[VerificationResult | None]:
        return [None for _ in units]


def _phrase_coverage(phrases: tuple[str, ...], text: str) -> float | None:
    normalized = [
        " ".join(str(phrase).casefold().split())
        for phrase in phrases
        if str(phrase).strip()
    ]
    if not normalized:
        return None
    haystack = " ".join((text or "").casefold().split())
    matches = sum(1 for phrase in normalized if phrase in haystack)
    return round(matches / len(normalized), 6)


class HeuristicContextVerifier:
    """Text-only fallback that follows the VLM scoring contract."""

    name = "heuristic-context"

    def verify(
        self,
        scene: SceneRecord,
        units: Sequence[RetrievalUnit],
    ) -> list[VerificationResult | None]:
        results: list[VerificationResult | None] = []
        for unit in units:
            text = unit.searchable_text
            subject = _phrase_coverage(scene.context.subject, text)
            action = _phrase_coverage(scene.context.action, text)
            location = _phrase_coverage(scene.context.location, text)
            objects = _phrase_coverage(scene.context.objects, text)
            conflict = _phrase_coverage(scene.context.avoid, text)
            available = [
                value
                for value in (subject, action, location, objects)
                if value is not None
            ]
            confidence = (
                sum(available) / len(available)
                if available
                else (1.0 if text.strip() else 0.0)
            )
            results.append(
                VerificationResult(
                    unit_id=unit.unit_id,
                    provider=self.name,
                    dimensions=VerificationDimensions(
                        subject_match=subject,
                        action_match=action,
                        location_match=location,
                        object_match=objects,
                        context_conflict=conflict,
                    ),
                    confidence=round(confidence, 6),
                    explanation="Fallback verification from transcript/metadata only.",
                )
            )
        return results
