from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SceneContext:
    subject: tuple[str, ...] = ()
    action: tuple[str, ...] = ()
    location: tuple[str, ...] = ()
    objects: tuple[str, ...] = ()
    mood: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    suggested_sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneRecord:
    scene_id: str
    order: int
    english_text: str
    vietnamese_text: str = ""
    target_duration: float = 5.0
    status: str = "unselected"
    context: SceneContext = field(default_factory=SceneContext)


@dataclass(frozen=True)
class CandidateRecord:
    candidate_id: str
    scene_id: str
    provider: str
    source_id: str
    title: str
    duration: float
    score: float
    rights_status: str = "unknown"
    resolution: str = ""
    source_url: str = ""
    proposed_start: float | None = None
    proposed_end: float | None = None
    thumbnail_url: str = ""
    preview_url: str = ""
    creator: str = ""
    description: str = ""
    published_at: str = ""
    source_metadata: dict[str, Any] = field(default_factory=dict)
    acquisition_manifest: str = ""


@dataclass(frozen=True)
class SelectedClipRecord:
    clip_id: str
    scene_id: str
    scene_order: int
    provider: str
    source_id: str
    title: str
    local_file: str
    start: float
    end: float
    duration: float
    semantic_score: float
    vlm_score: float
    final_score: float
    rights_status: str
    source_url: str = ""
    creator: str = ""
    source_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FootageProject:
    project_id: str
    output_dir: Path
    scenes: list[SceneRecord] = field(default_factory=list)
    selected_clips: list[SelectedClipRecord] = field(default_factory=list)

    def validate_rotation(self) -> list[str]:
        issues: list[str] = []
        ordered = sorted(self.selected_clips, key=lambda item: item.scene_order)
        for previous, current in zip(ordered, ordered[1:]):
            if previous.source_id and previous.source_id == current.source_id:
                issues.append(
                    f"{previous.scene_id}->{current.scene_id}: adjacent clips reuse source {current.source_id}"
                )
        return issues

    def validate_overlap(self) -> list[str]:
        issues: list[str] = []
        by_source: dict[str, list[SelectedClipRecord]] = {}
        for clip in self.selected_clips:
            by_source.setdefault(clip.source_id, []).append(clip)
        for source_id, clips in by_source.items():
            clips = sorted(clips, key=lambda item: item.start)
            for left, right in zip(clips, clips[1:]):
                if right.start < left.end:
                    issues.append(
                        f"{source_id}: {left.clip_id} overlaps {right.clip_id}"
                    )
        return issues

    def to_manifest(self) -> dict[str, Any]:
        return {
            "format": "bin_finder_footage_manifest_v1",
            "project_id": self.project_id,
            "scene_count": len(self.scenes),
            "selected_count": len(self.selected_clips),
            "scenes": [
                {**asdict(scene), "context": asdict(scene.context)}
                for scene in self.scenes
            ],
            "clips": [asdict(clip) for clip in self.selected_clips],
            "validation": {
                "source_rotation_issues": self.validate_rotation(),
                "overlap_issues": self.validate_overlap(),
            },
        }
