from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from bin_finder.models import FootageProject, SelectedClipRecord


@dataclass(frozen=True)
class AcceptancePolicy:
    min_duration_seconds: float = 60.0
    # None = no project-level upper duration limit (F019 production long-form policy).
    max_duration_seconds: float | None = 180.0
    min_final_score: float = 0.60
    require_all_scenes: bool = True
    require_clean_rotation: bool = True
    require_no_overlap: bool = True

    def validate(self) -> None:
        if self.min_duration_seconds < 0:
            raise ValueError("min_duration_seconds must be >= 0")
        if (self.max_duration_seconds is not None
                and self.max_duration_seconds < self.min_duration_seconds):
            raise ValueError("max_duration_seconds must be >= min_duration_seconds")
        if not 0.0 <= self.min_final_score <= 1.0:
            raise ValueError("min_final_score must be between 0 and 1")


def production_acceptance_policy() -> AcceptancePolicy:
    """F019 production policy: at least 60 s, no artificial upper ceiling.

    ``evaluate_project(project)`` keeps the historical F010 default (60-180 s). Every
    other gate (coverage, score, rotation, overlap) is identical.
    """
    return AcceptancePolicy(
        min_duration_seconds=60.0,
        max_duration_seconds=None,
        min_final_score=0.60,
        require_all_scenes=True,
        require_clean_rotation=True,
        require_no_overlap=True,
    )


@dataclass(frozen=True)
class SceneReadiness:
    scene_id: str
    scene_order: int
    selected: bool
    clip_id: str = ""
    final_score: float = 0.0
    ready: bool = False
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class AcceptanceReport:
    project_id: str
    ready: bool
    expected_duration_seconds: float
    selected_duration_seconds: float
    scene_count: int
    selected_count: int
    coverage_ratio: float
    average_final_score: float
    unresolved_scene_ids: tuple[str, ...]
    low_score_scene_ids: tuple[str, ...]
    source_rotation_issues: tuple[str, ...]
    overlap_issues: tuple[str, ...]
    duration_issue: str
    scenes: tuple[SceneReadiness, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scenes"] = [asdict(scene) for scene in self.scenes]
        return payload


def _clip_by_scene(project: FootageProject) -> dict[str, SelectedClipRecord]:
    ordered = sorted(
        project.selected_clips,
        key=lambda clip: (clip.scene_order, clip.scene_id, clip.clip_id),
    )
    result: dict[str, SelectedClipRecord] = {}
    for clip in ordered:
        result[clip.scene_id] = clip
    return result


def evaluate_project(
    project: FootageProject,
    policy: AcceptancePolicy | None = None,
) -> AcceptanceReport:
    policy = policy or AcceptancePolicy()
    policy.validate()

    clip_by_scene = _clip_by_scene(project)
    scene_reports: list[SceneReadiness] = []
    unresolved: list[str] = []
    low_score: list[str] = []

    for scene in sorted(project.scenes, key=lambda item: (item.order, item.scene_id)):
        clip = clip_by_scene.get(scene.scene_id)
        reasons: list[str] = []
        if clip is None:
            reasons.append("missing-footage")
            unresolved.append(scene.scene_id)
            scene_reports.append(
                SceneReadiness(
                    scene_id=scene.scene_id,
                    scene_order=scene.order,
                    selected=False,
                    ready=False,
                    reasons=tuple(reasons),
                )
            )
            continue

        if clip.final_score < policy.min_final_score:
            reasons.append("low-final-score")
            low_score.append(scene.scene_id)

        scene_reports.append(
            SceneReadiness(
                scene_id=scene.scene_id,
                scene_order=scene.order,
                selected=True,
                clip_id=clip.clip_id,
                final_score=round(float(clip.final_score), 6),
                ready=not reasons,
                reasons=tuple(reasons),
            )
        )

    expected_duration = round(
        sum(max(0.0, float(scene.target_duration)) for scene in project.scenes),
        6,
    )
    selected_duration = round(
        sum(max(0.0, float(clip.duration)) for clip in project.selected_clips),
        6,
    )
    duration_issue = ""
    if expected_duration < policy.min_duration_seconds:
        duration_issue = "expected-duration-below-minimum"
    elif (policy.max_duration_seconds is not None
          and expected_duration > policy.max_duration_seconds):
        duration_issue = "expected-duration-above-maximum"

    rotation_issues = tuple(project.validate_rotation())
    overlap_issues = tuple(project.validate_overlap())
    scene_count = len(project.scenes)
    selected_count = sum(1 for scene in project.scenes if scene.scene_id in clip_by_scene)
    coverage = round(selected_count / scene_count, 6) if scene_count else 0.0
    scores = [
        float(clip_by_scene[scene.scene_id].final_score)
        for scene in project.scenes
        if scene.scene_id in clip_by_scene
    ]
    average_score = round(sum(scores) / len(scores), 6) if scores else 0.0

    ready = True
    if policy.require_all_scenes and unresolved:
        ready = False
    if low_score:
        ready = False
    if duration_issue:
        ready = False
    if policy.require_clean_rotation and rotation_issues:
        ready = False
    if policy.require_no_overlap and overlap_issues:
        ready = False
    if scene_count == 0:
        ready = False

    return AcceptanceReport(
        project_id=project.project_id,
        ready=ready,
        expected_duration_seconds=expected_duration,
        selected_duration_seconds=selected_duration,
        scene_count=scene_count,
        selected_count=selected_count,
        coverage_ratio=coverage,
        average_final_score=average_score,
        unresolved_scene_ids=tuple(unresolved),
        low_score_scene_ids=tuple(low_score),
        source_rotation_issues=rotation_issues,
        overlap_issues=overlap_issues,
        duration_issue=duration_issue,
        scenes=tuple(scene_reports),
    )
