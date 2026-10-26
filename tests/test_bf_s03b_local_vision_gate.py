"""BF-S03B local-clip safety gate tests; fake media, zero calls to FFmpeg/VLM."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from bin_finder.models import CandidateRecord
from bin_finder.search.slot_candidates import CandidateHit, SlotSearchResult
from bin_finder.search.slot_metadata_rank import SlotMetadataRanker
from bin_finder.search.slot_local_vision_gate import (
    LocalMediaForReview, LocalVisionGateError, LocalVisionPolicy,
    prepare_local_vision,
)
from bin_finder.search.slot_search_smoke import synthetic_example


def _ranked():
    _, plan = synthetic_example()
    slot = plan.slots[0]
    hits = tuple(
        CandidateHit(
            slot_id=slot.slot_id, beat_id=slot.beat_id,
            scene_ids=slot.scene_ids, matched_axes=("subject",),
            returned_order=i,
            candidate=CandidateRecord(
                candidate_id="scene_001:pexels:" + str(i),
                scene_id=slot.scene_ids[0], provider="pexels",
                source_id="pexels:" + str(i),
                title="Fishing boat at harbor", duration=12.0, score=0.0,
                resolution="1920x1080", rights_status="unknown",
            ),
        ) for i in range(7)
    )
    return SlotMetadataRanker().rank(
        plan, SlotSearchResult(slot.slot_id, hits, ())
    )


def _item(filename: Path, identifier: int = 0):
    return LocalMediaForReview(
        provider="pexels", source_id="pexels:" + str(identifier),
        local_file=str(filename), start=1.0, end=6.0,
    )


def test_manual_opt_in_required_even_when_candidate_is_ranked(tmp_path):
    result = prepare_local_vision(
        _ranked(), (_item(tmp_path / "not-present.mp4"),), allowed_root=tmp_path
    )
    assert result.status == "manual-opt-in-required"
    assert result.model_calls == result.provider_calls == 0
    assert result.prepared == ()
    assert result.not_prepared_count == 1


def test_approved_valid_local_file_is_prepared_not_verified(tmp_path):
    target = tmp_path / "video.mp4"
    target.write_bytes(b"safe tiny media fixture")
    original = (_item(target),)
    result = prepare_local_vision(
        _ranked(), original, allowed_root=tmp_path,
        approve_local_inspection=True,
    )
    assert result.status == "local-ready-for-inference-approval"
    assert len(result.prepared) == 1
    unit = result.prepared[0]
    assert unit.source_file == target.resolve()
    assert unit.status == "local-sample-ready-not-verified"
    assert unit.start == 1 and unit.end == 6
    assert result.model_calls == result.provider_calls == 0
    assert str(target) not in repr(unit)  # Avoid accidental path logging
    assert original[0].local_file == str(target)


def test_external_file_is_rejected_even_when_it_exists(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    foreign = tmp_path / "private.mp4"
    foreign.write_bytes(b"another fixture")
    result = prepare_local_vision(
        _ranked(), (_item(foreign),), allowed_root=root,
        approve_local_inspection=True,
    )
    assert result.status == "no-safe-local-media"
    assert result.not_prepared_count == 1


def test_remote_url_and_nonexistent_local_file_are_not_downloaded(tmp_path):
    items = (
        LocalMediaForReview("pexels", "pexels:0",
                            "https://pexels.com/?key=DO_NOT_SHOW", 0, 5),
        _item(tmp_path / "notfound.mp4", identifier=1),
    )
    result = prepare_local_vision(
        _ranked(), items, allowed_root=tmp_path,
        approve_local_inspection=True,
    )
    assert result.status == "no-safe-local-media"
    assert result.not_prepared_count == 2
    assert result.provider_calls == 0
    assert "DO_NOT_SHOW" not in repr(result)


def test_symlink_file_is_rejected_without_reading(tmp_path):
    real = tmp_path / "safe.mp4"
    real.write_bytes(b"media")
    link = tmp_path / "alias.mp4"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("Windows symlink creation requires Developer Mode")
    result = prepare_local_vision(
        _ranked(), (_item(link),), allowed_root=tmp_path,
        approve_local_inspection=True,
    )
    assert result.status == "no-safe-local-media"
    assert result.prepared == ()


def test_unranked_candidate_is_rejected_before_filesystem_access(tmp_path):
    with pytest.raises(LocalVisionGateError, match="unranked-candidate-rejected"):
        prepare_local_vision(
            _ranked(), (_item(tmp_path / "clip.mp4", identifier=9999),),
            allowed_root=tmp_path, approve_local_inspection=True,
        )


def test_cap_and_duplicate_keys_rejected(tmp_path):
    a = _item(tmp_path / "a.mp4")
    with pytest.raises(LocalVisionGateError, match="invalid-local-media-list"):
        prepare_local_vision(
            _ranked(), (a, a), allowed_root=tmp_path,
            approve_local_inspection=True,
        )
    items = tuple(_item(tmp_path / f"{i}.mp4", i) for i in range(6))
    with pytest.raises(LocalVisionGateError, match="invalid-local-media-list"):
        prepare_local_vision(
            _ranked(), items, allowed_root=tmp_path,
            approve_local_inspection=True,
        )


@pytest.mark.parametrize("extension", (".json", ".exe", ".jpg", ".txt"))
def test_nonvideo_extension_rejected(tmp_path, extension):
    file = tmp_path / ("clip" + extension)
    file.write_bytes(b"not video")
    result = prepare_local_vision(
        _ranked(), (_item(file),), allowed_root=tmp_path,
        approve_local_inspection=True,
    )
    assert result.status == "no-safe-local-media"


@pytest.mark.parametrize("start,end", [
    (-1, 3), (4, 3), (0, 0), (0, 121), (float("nan"), 5),
    (0, float("inf")), ("bad", 3),
])
def test_invalid_timeline_range_is_rejected(tmp_path, start, end):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"clip")
    requested = replace(_item(clip), start=start, end=end)
    result = prepare_local_vision(
        _ranked(), (requested,), allowed_root=tmp_path,
        approve_local_inspection=True,
    )
    assert result.status == "no-safe-local-media"


def test_empty_local_list_does_not_infer_top_five_files(tmp_path):
    result = prepare_local_vision(
        _ranked(), (), allowed_root=tmp_path,
        approve_local_inspection=True,
    )
    assert result.status == "no-manual-media-selected"
    assert result.prepared == ()


def test_invalid_settings_do_not_inspect_video(tmp_path):
    for policy in (
        LocalVisionPolicy(max_candidates=6),
        LocalVisionPolicy(max_clip_seconds=0),
        LocalVisionPolicy(max_file_bytes=5),
    ):
        with pytest.raises(LocalVisionGateError, match="invalid-local-vision-policy"):
            prepare_local_vision(
                _ranked(), (), allowed_root=tmp_path,
                approve_local_inspection=True, policy=policy,
            )


def test_explicit_root_must_exist(tmp_path):
    with pytest.raises(LocalVisionGateError, match="unsafe-media-root"):
        prepare_local_vision(
            _ranked(), (_item(tmp_path / "clip.mp4"),),
            allowed_root=tmp_path / "missing",
            approve_local_inspection=True,
        )
