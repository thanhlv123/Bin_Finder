from pathlib import Path

import pytest

from bin_finder.acceptance import AcceptancePolicy, evaluate_project
from bin_finder.models import FootageProject, SceneRecord, SelectedClipRecord


def make_project(
    *,
    scene_count=12,
    missing_scene=None,
    low_score_scene=None,
    duplicate_adjacent=False,
    overlap=False,
):
    scenes = [
        SceneRecord(
            scene_id=f"scene_{index:03d}",
            order=index,
            english_text=f"Scene {index}",
            target_duration=5.0,
        )
        for index in range(1, scene_count + 1)
    ]
    clips = []
    for index in range(1, scene_count + 1):
        if index == missing_scene:
            continue
        source_id = f"source_{index:03d}"
        if duplicate_adjacent and index == 2:
            source_id = "source_001"
        start = float(index * 10)
        if overlap and index == 3:
            source_id = "source_001"
            start = 12.0
        score = 0.4 if index == low_score_scene else 0.9
        clips.append(
            SelectedClipRecord(
                clip_id=f"clip_{index:03d}",
                scene_id=f"scene_{index:03d}",
                scene_order=index,
                provider="local",
                source_id=source_id,
                title=f"Clip {index}",
                local_file=f"D:/clips/clip_{index:03d}.mp4",
                start=start,
                end=start + 5.0,
                duration=5.0,
                semantic_score=0.9,
                vlm_score=0.9,
                final_score=score,
                rights_status="owned",
            )
        )
    return FootageProject("TEST_PROJECT", Path("D:/out"), scenes, clips)


def test_ready_project_passes_default_acceptance():
    report = evaluate_project(make_project())
    assert report.ready is True
    assert report.coverage_ratio == 1.0
    assert report.scene_count == 12
    assert report.selected_count == 12
    assert report.expected_duration_seconds == 60.0
    assert report.average_final_score == 0.9


def test_missing_scene_is_reported_and_blocks_ready():
    report = evaluate_project(make_project(missing_scene=4))
    assert report.ready is False
    assert report.unresolved_scene_ids == ("scene_004",)
    assert report.coverage_ratio == pytest.approx(11 / 12, abs=1e-6)


def test_low_score_scene_is_reported():
    report = evaluate_project(make_project(low_score_scene=5))
    assert report.ready is False
    assert report.low_score_scene_ids == ("scene_005",)
    scene = next(item for item in report.scenes if item.scene_id == "scene_005")
    assert scene.reasons == ("low-final-score",)


def test_adjacent_source_reuse_blocks_ready():
    report = evaluate_project(make_project(duplicate_adjacent=True))
    assert report.ready is False
    assert report.source_rotation_issues


def test_same_source_overlap_blocks_ready():
    report = evaluate_project(make_project(overlap=True))
    assert report.ready is False
    assert report.overlap_issues


def test_duration_outside_one_to_three_minutes_is_reported():
    report = evaluate_project(make_project(scene_count=5))
    assert report.ready is False
    assert report.duration_issue == "expected-duration-below-minimum"


def test_policy_can_relax_duration_for_research_case():
    report = evaluate_project(
        make_project(scene_count=5),
        AcceptancePolicy(min_duration_seconds=0, max_duration_seconds=180),
    )
    assert report.ready is True


def test_invalid_policy_is_rejected():
    with pytest.raises(ValueError):
        evaluate_project(
            make_project(),
            AcceptancePolicy(min_final_score=1.1),
        )
