"""ZB-03A offline state tests. No Qt, AI, providers or user data."""
from dataclasses import replace

import pytest

from bin_finder.draft_timeline import (
    DraftCandidate, DraftTimelineError, build_draft_timeline,
    local_candidate_for_path,
)
from bin_finder.timeline_review_demo import build_demo, main


@pytest.mark.parametrize("genre", ["travel", "history", "economy"])
def test_demo_is_only_mock_candidates_and_scene_order_is_unchanged(genre):
    scenes, plan, draft = build_demo(genre)
    assert len(scenes) == 4
    assert draft.scene_ids == tuple(scene.scene_id for scene in scenes)
    assert len(draft.items) == len(plan.shots)
    assert draft.plan_id == plan.plan_id
    assert all(
        item.narration_end_estimate > item.narration_start_estimate
        for item in draft.items
    )
    assert any(len(item.scene_ids) > 1 for item in draft.items)
    for item in draft.items:
        if item.strategy == "search":
            assert item.review_status == "proposed"
            assert item.candidates
            assert all(c.origin == "synthetic" for c in item.candidates)
        else:
            assert item.review_status == "needs_editorial_resolution"
            assert item.candidates == ()
            assert item.selected_candidate_id is None
    assert not any(item.reviewed or item.locked for item in draft.items)


def test_review_replacement_resets_review_and_does_not_touch_locked_shots():
    _scenes, _plan, draft = build_demo()
    first, second = draft.items[0], draft.items[2]
    original = draft
    reviewed = draft.mark_reviewed(first.shot_id)
    assert reviewed.item(first.shot_id).review_status == "reviewed"
    locked = reviewed.set_lock(first.shot_id, True)
    assert locked.item(first.shot_id).review_status == "locked"
    with pytest.raises(DraftTimelineError, match="shot-locked"):
        locked.choose(first.shot_id, first.candidates[1].candidate_id)
    with pytest.raises(DraftTimelineError, match="shot-locked"):
        locked.set_note(first.shot_id, "unapproved replacement")
    with pytest.raises(DraftTimelineError, match="shot-locked"):
        locked.add_candidate(first.shot_id, DraftCandidate("demo_new", "New mock"))
    assert original.item(first.shot_id).review_status == "proposed"
    assert original.item(first.shot_id).locked is False
    unlocked = locked.set_lock(first.shot_id, False)
    replaced = unlocked.choose(first.shot_id, first.candidates[1].candidate_id)
    assert replaced.item(first.shot_id).review_status == "proposed"
    assert replaced.item(first.shot_id).reviewed is False
    assert replaced.item(second.shot_id) == original.item(second.shot_id)


def test_lock_always_requires_explicit_layout_review():
    _, _, draft = build_demo()
    shot = draft.items[0]
    with pytest.raises(DraftTimelineError, match="review-required-before-lock"):
        draft.set_lock(shot.shot_id, True)
    with pytest.raises(DraftTimelineError, match="invalid-lock-value"):
        draft.set_lock(shot.shot_id, 1)
    no_selection = draft.choose(shot.shot_id, None)
    assert no_selection.item(shot.shot_id).review_status == "missing"
    with pytest.raises(DraftTimelineError, match="candidate-not-selected"):
        no_selection.mark_reviewed(shot.shot_id)


def test_transition_and_hold_remain_unresolved_not_faked_media():
    for genre in ("travel", "history", "economy"):
        _scenes, _plan, draft = build_demo(genre)
        for item in draft.items:
            if item.strategy == "search":
                continue
            with pytest.raises(DraftTimelineError, match="shot-does-not-search"):
                draft.choose(item.shot_id, "any")
            with pytest.raises(DraftTimelineError, match="shot-does-not-search"):
                draft.add_candidate(item.shot_id, DraftCandidate("a1", "Mock"))
            with pytest.raises(DraftTimelineError, match="candidate-not-selected"):
                draft.mark_reviewed(item.shot_id)
            with pytest.raises(DraftTimelineError, match="review-required-before-lock"):
                draft.set_lock(item.shot_id, True)


def test_explicit_local_clip_reference_is_not_approval(tmp_path):
    source = tmp_path / "synthetic source.MP4"
    source.write_bytes(b"FAKE BYTES, NOT A REAL VIDEO")
    candidate = local_candidate_for_path(str(source))
    assert candidate.origin == "local"
    assert candidate.title == source.name
    _, _, draft = build_demo()
    sid = draft.items[0].shot_id
    added = draft.add_candidate(sid, candidate)
    chosen = added.choose(sid, candidate.candidate_id)
    assert chosen.item(sid).review_status == "proposed"
    assert chosen.item(sid).reviewed is False
    assert chosen.item(sid).locked is False
    assert not any(item.reviewed for item in draft.items)
    assert source.read_bytes() == b"FAKE BYTES, NOT A REAL VIDEO"


def test_invalid_local_file_path_and_type_rejected(tmp_path):
    with pytest.raises(DraftTimelineError, match="local-file-not-regular"):
        local_candidate_for_path(str(tmp_path / "missing.mp4"))
    invalid = tmp_path / "script.ps1"
    invalid.write_text("Write-Host do-not-execute")
    with pytest.raises(DraftTimelineError, match="unsupported-local-format"):
        local_candidate_for_path(str(invalid))
    _, _, draft = build_demo()
    with pytest.raises(DraftTimelineError, match="invalid-candidate"):
        draft.add_candidate(draft.items[0].shot_id, {"candidate_id": "x"})


def test_candidate_ids_are_explicit_not_model_links():
    _, _, draft = build_demo()
    first = draft.items[0]
    with pytest.raises(DraftTimelineError, match="unknown-candidate"):
        draft.choose(first.shot_id, "made_up_asset")
    with pytest.raises(DraftTimelineError, match="duplicate-candidate"):
        draft.add_candidate(first.shot_id, first.candidates[0])
    with pytest.raises(DraftTimelineError, match="unknown-shot"):
        draft.item("unknown")
    with pytest.raises(DraftTimelineError, match="invalid-candidate-id"):
        DraftCandidate(candidate_id="https://example.com?token=PRIVATE", title="Mock")


def test_review_note_never_changes_other_shot_and_is_only_in_memory():
    _, _, draft = build_demo()
    first = draft.items[0]
    current = draft.set_note(first.shot_id, "Cần tìm cảnh gần hơn")
    assert draft.item(first.shot_id).note == ""
    assert current.item(first.shot_id).note == "Cần tìm cảnh gần hơn"
    with pytest.raises(DraftTimelineError, match="invalid-review-note"):
        current.set_note(first.shot_id, "x" * 501)


def test_estimates_are_not_fabricated_precise_clip_timing():
    scenes, plan, draft = build_demo()
    first = draft.items[0]
    assert first.scene_ids == ("scene_001", "scene_002")
    assert first.narration_start_estimate == 0.0
    assert first.narration_end_estimate == (
        scenes[0].target_duration + scenes[1].target_duration
    )
    assert not hasattr(first, "media_start")
    assert not hasattr(first, "media_end")
    too_long = [replace(scenes[0], target_duration=float("nan")), *scenes[1:]]
    with pytest.raises(DraftTimelineError, match="invalid-narration-duration"):
        build_draft_timeline(plan, too_long)


def test_headless_demo_does_not_instantiate_qt(capsys):
    for genre in ("travel", "history", "economy"):
        assert main(["--genre", genre, "--headless"]) == 0
        out = capsys.readouterr().out
        assert "SYNTHETIC_DRAFT_ONLY" in out
        assert "ZB03A_NO_VIDEO_EXPORT: True" in out
