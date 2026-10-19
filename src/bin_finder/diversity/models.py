from __future__ import annotations

from dataclasses import dataclass

from bin_finder.models import CandidateRecord


@dataclass(frozen=True)
class DiversityPolicy:
    source_cooldown: int = 1
    max_score_drop: float = 0.18
    min_score: float = 0.0
    overlap_tolerance: float = 0.0
    duplicate_iou_threshold: float = 0.80

    def validate(self) -> None:
        if self.source_cooldown < 0:
            raise ValueError("source_cooldown must be >= 0")
        if not 0.0 <= self.max_score_drop <= 1.0:
            raise ValueError("max_score_drop must be between 0 and 1")
        if not 0.0 <= self.min_score <= 1.0:
            raise ValueError("min_score must be between 0 and 1")
        if self.overlap_tolerance < 0:
            raise ValueError("overlap_tolerance must be >= 0")
        if not 0.0 <= self.duplicate_iou_threshold <= 1.0:
            raise ValueError("duplicate_iou_threshold must be between 0 and 1")


@dataclass(frozen=True)
class DiversityCandidate:
    candidate_id: str
    scene_id: str
    scene_order: int
    source_id: str
    start: float
    end: float
    score: float
    provider: str = ""
    duplicate_group: str = ""

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @classmethod
    def from_candidate_record(
        cls,
        candidate: CandidateRecord,
        *,
        scene_order: int,
        start: float | None = None,
        end: float | None = None,
        duplicate_group: str = "",
    ) -> "DiversityCandidate":
        resolved_start = (
            candidate.proposed_start
            if start is None
            else start
        )
        resolved_end = (
            candidate.proposed_end
            if end is None
            else end
        )
        return cls(
            candidate_id=candidate.candidate_id,
            scene_id=candidate.scene_id,
            scene_order=scene_order,
            source_id=candidate.source_id,
            start=float(resolved_start or 0.0),
            end=float(
                resolved_end
                if resolved_end is not None
                else (resolved_start or 0.0) + max(0.0, candidate.duration)
            ),
            score=max(0.0, min(1.0, float(candidate.score))),
            provider=candidate.provider,
            duplicate_group=duplicate_group,
        )


@dataclass(frozen=True)
class SelectionDecision:
    scene_id: str
    scene_order: int
    candidate: DiversityCandidate | None
    status: str
    reason: str
    best_score: float | None = None
    selected_score: float | None = None
    score_drop: float | None = None
    considered_count: int = 0


@dataclass(frozen=True)
class DiversitySelectionResult:
    decisions: tuple[SelectionDecision, ...]

    @property
    def selected(self) -> tuple[DiversityCandidate, ...]:
        return tuple(
            decision.candidate
            for decision in self.decisions
            if decision.candidate is not None
        )

    @property
    def unresolved_scene_ids(self) -> tuple[str, ...]:
        return tuple(
            decision.scene_id
            for decision in self.decisions
            if decision.candidate is None
        )
