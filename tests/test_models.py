from pathlib import Path

from bin_finder.models import FootageProject, SceneRecord, SelectedClipRecord


def _clip(clip_id: str, scene_id: str, order: int, source_id: str, start: float, end: float):
    return SelectedClipRecord(
        clip_id=clip_id,
        scene_id=scene_id,
        scene_order=order,
        provider="youtube",
        source_id=source_id,
        title=clip_id,
        local_file=f"{clip_id}.mp4",
        start=start,
        end=end,
        duration=end - start,
        semantic_score=.9,
        vlm_score=.9,
        final_score=.9,
        rights_status="approved",
    )


def test_source_rotation_flags_adjacent_same_source():
    project = FootageProject("demo", Path("out"))
    project.selected_clips = [
        _clip("c1", "scene_001", 1, "video_A", 0, 5),
        _clip("c2", "scene_002", 2, "video_A", 20, 25),
    ]
    assert project.validate_rotation()


def test_source_rotation_allows_return_after_other_source():
    project = FootageProject("demo", Path("out"))
    project.selected_clips = [
        _clip("c1", "scene_001", 1, "video_A", 0, 5),
        _clip("c2", "scene_002", 2, "video_B", 0, 5),
        _clip("c3", "scene_003", 3, "video_A", 20, 25),
    ]
    assert project.validate_rotation() == []


def test_overlap_is_forbidden_within_same_source():
    project = FootageProject("demo", Path("out"))
    project.selected_clips = [
        _clip("c1", "scene_001", 1, "video_A", 10, 15),
        _clip("c2", "scene_003", 3, "video_A", 14, 19),
    ]
    assert project.validate_overlap()


def test_manifest_keeps_scene_id_and_clip_id_contract():
    project = FootageProject(
        "demo",
        Path("out"),
        scenes=[SceneRecord("scene_001", 1, "Hello")],
        selected_clips=[_clip("clip_0001", "scene_001", 1, "video_A", 10, 15)],
    )
    manifest = project.to_manifest()
    assert manifest["clips"][0]["clip_id"] == "clip_0001"
    assert manifest["clips"][0]["scene_id"] == "scene_001"
    assert manifest["format"] == "bin_finder_footage_manifest_v1"
