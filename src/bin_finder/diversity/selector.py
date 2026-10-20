from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from bin_finder.diversity.models import (
    DiversityCandidate,
    DiversityPolicy,
    DiversitySelectionResult,
    SelectionDecision,
)


def _overlap_seconds(
    left: DiversityCandidate,
    right: DiversityCandidate,
) -> float:
    return max(0.0, min(left.end, right.end) - max(left.start, right.start))


def _temporal_iou(
    left: DiversityCandidate,
    right: DiversityCandidate,
) -> float:
    overlap = _overlap_seconds(left, right)
    if overlap <= 0:
        return 0.0
    union = max(left.end, right.end) - min(left.start, right.start)
    if union <= 0:
        return 0.0
    return overlap / union


def suppress_scene_duplicates(
    candidates: Iterable[DiversityCandidate],
    *,
    iou_threshold: float,
) -> list[DiversityCandidate]:
    ordered = sorted(
        candidates,
        key=lambda item: (
            -item.score,
            item.source_id,
            item.start,
            item.end,
            item.candidate_id,
        ),
    )
    kept: list[DiversityCandidate] = []
    seen_candidate_ids: set[str] = set()
    seen_duplicate_groups: set[str] = set()

    for candidate in ordered:
        if candidate.candidate_id in seen_candidate_ids:
            continue
        seen_candidate_ids.add(candidate.candidate_id)

        if (
            candidate.duplicate_group
            and candidate.duplicate_group in seen_duplicate_groups
        ):
            continue

        duplicate_range = any(
            kept_item.source_id == candidate.source_id
            and _temporal_iou(kept_item, candidate) >= iou_threshold
            for kept_item in kept
        )
        if duplicate_range:
            continue

        kept.append(candidate)
        if candidate.duplicate_group:
            seen_duplicate_groups.add(candidate.duplicate_group)

    return kept


class SourceDiversitySelector:
    def __init__(self, policy: DiversityPolicy | None = None):
        self.policy = policy or DiversityPolicy()
        self.policy.validate()

    def _conflict_reason(
        self,
        candidate: DiversityCandidate,
        selected: list[DiversityCandidate],
    ) -> str | None:
        if not candidate.source_id:
            return "missing-source-id"
        if candidate.duration <= 0:
            return "invalid-range"

        if self.policy.source_cooldown > 0:
            recent_sources = {
                item.source_id
                for item in selected[-self.policy.source_cooldown :]
            }
            if candidate.source_id in recent_sources:
                return "source-cooldown"

        if candidate.duplicate_group:
            if any(
                item.duplicate_group
                and item.duplicate_group == candidate.duplicate_group
                for item in selected
            ):
                return "duplicate-reuse"

        for previous in selected:
            if previous.source_id != candidate.source_id:
                continue
            overlap = _overlap_seconds(previous, candidate)
            if overlap > self.policy.overlap_tolerance:
                return "source-overlap"

        return None

    def select(
        self,
        candidates: Iterable[DiversityCandidate],
        *,
        expected_scenes: Iterable[tuple[int, str]] | None = None,
    ) -> DiversitySelectionResult:
        grouped: dict[tuple[int, str], list[DiversityCandidate]] = defaultdict(list)
        for candidate in candidates:
            grouped[(candidate.scene_order, candidate.scene_id)].append(candidate)

        scene_keys = set(grouped)
        if expected_scenes is not None:
            scene_keys.update(
                (int(scene_order), str(scene_id))
                for scene_order, scene_id in expected_scenes
            )

        selected: list[DiversityCandidate] = []
        decisions: list[SelectionDecision] = []

        for scene_order, scene_id in sorted(scene_keys):
            scene_candidates = suppress_scene_duplicates(
                grouped.get((scene_order, scene_id), ()),
                iou_threshold=self.policy.duplicate_iou_threshold,
            )
            if not scene_candidates:
                decisions.append(
                    SelectionDecision(
                        scene_id=scene_id,
                        scene_order=scene_order,
                        candidate=None,
                        status="unresolved",
                        reason="no-candidates",
                    )
                )
                continue

            best_score = scene_candidates[0].score
            quality_floor = max(
                self.policy.min_score,
                best_score - self.policy.max_score_drop,
            )

            chosen: DiversityCandidate | None = None
            conflict_reasons: list[str] = []
            low_quality_available = False

            for candidate in scene_candidates:
                conflict = self._conflict_reason(candidate, selected)
                if conflict is not None:
                    conflict_reasons.append(conflict)
                    continue
                if candidate.score < quality_floor:
                    low_quality_available = True
                    continue
                chosen = candidate
                break

            if chosen is not None:
                selected.append(chosen)
                drop = round(max(0.0, best_score - chosen.score), 6)
                decisions.append(
                    SelectionDecision(
                        scene_id=scene_id,
                        scene_order=scene_order,
                        candidate=chosen,
                        status="selected",
                        reason=(
                            "best-candidate"
                            if drop == 0
                            else "diversity-alternative"
                        ),
                        best_score=best_score,
                        selected_score=chosen.score,
                        score_drop=drop,
                        considered_count=len(scene_candidates),
                    )
                )
                continue

            if low_quality_available:
                reason = "low-context-match"
            elif conflict_reasons:
                reason = "diversity-conflict"
            else:
                reason = "no-eligible-candidate"

            decisions.append(
                SelectionDecision(
                    scene_id=scene_id,
                    scene_order=scene_order,
                    candidate=None,
                    status="unresolved",
                    reason=reason,
                    best_score=best_score,
                    considered_count=len(scene_candidates),
                    conflict_reasons=tuple(dict.fromkeys(conflict_reasons)),
                )
            )

        return DiversitySelectionResult(tuple(decisions))
