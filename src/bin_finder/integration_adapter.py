from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bin_finder.acceptance import AcceptanceReport
from bin_finder.models import FootageProject


FORMAT = "ai_video_editor_bin_finder_adapter_v1"


class IntegrationExportError(RuntimeError):
    pass


def build_ai_video_editor_manifest(
    project: FootageProject,
    report: AcceptanceReport,
) -> dict[str, Any]:
    clip_by_scene = {
        clip.scene_id: clip
        for clip in sorted(
            project.selected_clips,
            key=lambda item: (item.scene_order, item.scene_id, item.clip_id),
        )
    }
    scenes: list[dict[str, Any]] = []
    for scene in sorted(project.scenes, key=lambda item: (item.order, item.scene_id)):
        clip = clip_by_scene.get(scene.scene_id)
        scenes.append(
            {
                "scene_id": scene.scene_id,
                "scene_order": scene.order,
                "script_text": scene.english_text,
                "vietnamese_text": scene.vietnamese_text,
                "target_duration_seconds": scene.target_duration,
                "footage": (
                    None
                    if clip is None
                    else {
                        "clip_id": clip.clip_id,
                        "provider": clip.provider,
                        "source_id": clip.source_id,
                        "title": clip.title,
                        "path": clip.local_file,
                        "source_start_seconds": clip.start,
                        "source_end_seconds": clip.end,
                        "duration_seconds": clip.duration,
                        "semantic_score": clip.semantic_score,
                        "vlm_score": clip.vlm_score,
                        "final_score": clip.final_score,
                        "rights_status": clip.rights_status,
                        "source_url": clip.source_url,
                        "creator": clip.creator,
                        "source_metadata": clip.source_metadata,
                    }
                ),
            }
        )

    return {
        "format": FORMAT,
        "producer": "Bin Finder",
        "project_id": project.project_id,
        "ready": report.ready,
        "expected_duration_seconds": report.expected_duration_seconds,
        "selected_duration_seconds": report.selected_duration_seconds,
        "scene_count": report.scene_count,
        "selected_count": report.selected_count,
        "coverage_ratio": report.coverage_ratio,
        "average_final_score": report.average_final_score,
        "scenes": scenes,
        "validation": {
            "unresolved_scene_ids": list(report.unresolved_scene_ids),
            "low_score_scene_ids": list(report.low_score_scene_ids),
            "source_rotation_issues": list(report.source_rotation_issues),
            "overlap_issues": list(report.overlap_issues),
            "duration_issue": report.duration_issue,
        },
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def write_integration_package(
    output_dir: str | Path,
    project: FootageProject,
    report: AcceptanceReport,
    *,
    allow_incomplete: bool = False,
) -> tuple[Path, Path]:
    if not report.ready and not allow_incomplete:
        raise IntegrationExportError(
            "Project acceptance is not ready; refusing integration export."
        )

    root = Path(output_dir)
    manifest_path = root / "_ai_video_editor_bin_finder_adapter.json"
    acceptance_path = root / "_bin_finder_acceptance.json"
    _atomic_json(
        manifest_path,
        build_ai_video_editor_manifest(project, report),
    )
    _atomic_json(
        acceptance_path,
        report.to_dict(),
    )
    return manifest_path, acceptance_path
