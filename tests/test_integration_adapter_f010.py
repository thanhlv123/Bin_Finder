import json
from pathlib import Path

import pytest

from bin_finder.acceptance import evaluate_project
from bin_finder.integration_adapter import (
    FORMAT,
    IntegrationExportError,
    build_ai_video_editor_manifest,
    write_integration_package,
)
from bin_finder.models import FootageProject, SceneRecord, SelectedClipRecord


def project(scene_count=12, missing=False):
    scenes = [
        SceneRecord(
            scene_id=f"scene_{i:03d}",
            order=i,
            english_text=f"Script scene {i}",
            vietnamese_text=f"Cảnh {i}",
            target_duration=5.0,
        )
        for i in range(1, scene_count + 1)
    ]
    clips = []
    for i in range(1, scene_count + 1):
        if missing and i == scene_count:
            continue
        clips.append(
            SelectedClipRecord(
                clip_id=f"clip_{i:03d}",
                scene_id=f"scene_{i:03d}",
                scene_order=i,
                provider="local",
                source_id=f"source_{i:03d}",
                title=f"Footage {i}",
                local_file=f"D:/footage/scene_{i:03d}.mp4",
                start=10.0,
                end=15.0,
                duration=5.0,
                semantic_score=0.88,
                vlm_score=0.91,
                final_score=0.90,
                rights_status="owned",
            )
        )
    return FootageProject("CUBA_VIDEO_001", Path("D:/out"), scenes, clips)


def test_manifest_has_stable_contract_and_scene_linkage():
    item = project()
    report = evaluate_project(item)
    manifest = build_ai_video_editor_manifest(item, report)

    assert manifest["format"] == FORMAT
    assert manifest["ready"] is True
    assert manifest["scene_count"] == 12
    first = manifest["scenes"][0]
    assert first["scene_id"] == "scene_001"
    assert first["scene_order"] == 1
    assert first["footage"]["clip_id"] == "clip_001"
    assert first["footage"]["source_start_seconds"] == 10.0
    assert first["footage"]["source_end_seconds"] == 15.0
    assert first["footage"]["rights_status"] == "owned"


def test_manifest_keeps_unresolved_scene_with_null_footage():
    item = project(missing=True)
    report = evaluate_project(item)
    manifest = build_ai_video_editor_manifest(item, report)

    assert manifest["ready"] is False
    assert manifest["scenes"][-1]["footage"] is None
    assert manifest["validation"]["unresolved_scene_ids"] == ["scene_012"]


def test_write_integration_package_is_atomic_and_readable(tmp_path: Path):
    item = project()
    report = evaluate_project(item)

    manifest_path, acceptance_path = write_integration_package(
        tmp_path,
        item,
        report,
    )

    assert manifest_path.name == "_ai_video_editor_bin_finder_adapter.json"
    assert acceptance_path.name == "_bin_finder_acceptance.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    assert manifest["format"] == FORMAT
    assert acceptance["ready"] is True
    assert not list(tmp_path.glob("*.tmp"))


def test_incomplete_project_is_not_exported_by_default(tmp_path: Path):
    item = project(missing=True)
    report = evaluate_project(item)

    with pytest.raises(IntegrationExportError):
        write_integration_package(tmp_path, item, report)

    assert not (tmp_path / "_ai_video_editor_bin_finder_adapter.json").exists()


def test_incomplete_export_requires_explicit_override(tmp_path: Path):
    item = project(missing=True)
    report = evaluate_project(item)

    manifest_path, _ = write_integration_package(
        tmp_path,
        item,
        report,
        allow_incomplete=True,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["ready"] is False
