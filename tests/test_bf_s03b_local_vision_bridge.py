"""BF-S03B Phase 1: second permission boundary and adapter contract, offline."""
from __future__ import annotations

from dataclasses import replace

import pytest

from bin_finder.models import CandidateRecord
from bin_finder.search.slot_candidates import CandidateHit, SlotSearchResult
from bin_finder.search.slot_metadata_rank import SlotMetadataRanker
from bin_finder.search.slot_local_vision_gate import (
    LocalMediaForReview, LocalVisionGateError, LocalVisionGateResult,
    prepare_local_vision,
)
from bin_finder.search.slot_local_vision_bridge import verify_local_vision
from bin_finder.search.slot_search_smoke import synthetic_example
from bin_finder.verification.models import VerificationDimensions, VerificationResult
from bin_finder.verification.ollama_vlm import VlmConfig, VlmConfigError


class FakeVerifier:
    def __init__(self, result=None, fail=False):
        self.calls = []
        self.result = result
        self.fail = fail

    def verify(self, scene, units):
        self.calls.append((scene, units))
        if self.fail:
            raise RuntimeError("PRIVATE_SOURCE_PATH_SHOULD_NOT_PRINT")
        return [self.result]


def _prepared(tmp_path):
    _, plan = synthetic_example()
    slot = plan.slots[0]
    source = tmp_path / "local.mp4"
    source.write_bytes(b"fake local fixture - not sampled")
    hit = CandidateHit(
        slot_id=slot.slot_id, beat_id=slot.beat_id,
        scene_ids=slot.scene_ids, matched_axes=("subject",),
        returned_order=0,
        candidate=CandidateRecord(
            candidate_id="scene_001:pexels:10020348",
            scene_id=slot.scene_ids[0], provider="pexels",
            source_id="pexels:10020348",
            title="Fishing boat sailing in sea", duration=10,
            score=0, rights_status="unknown", resolution="1920x1080",
        ),
    )
    rank = SlotMetadataRanker().rank(plan, SlotSearchResult(slot.slot_id, (hit,), ()))
    mapped = LocalMediaForReview(
        provider="pexels", source_id="pexels:10020348",
        local_file=str(source), start=1, end=5,
    )
    gate = prepare_local_vision(
        rank, (mapped,), allowed_root=tmp_path,
        approve_local_inspection=True,
    )
    assert gate.status == "local-ready-for-inference-approval"
    return plan, gate


def _response(unit_id="slot1:review:1", *,
              subject=.9, action=.75, time=None, conflict=.1, confidence=.8):
    return VerificationResult(
        unit_id=unit_id,
        provider="ollama-vlm:test-local",
        dimensions=VerificationDimensions(
            subject_match=subject, action_match=action, time_match=time,
            context_conflict=conflict,
        ),
        confidence=confidence,
        explanation="Untrusted model prose; not shown in reports.",
    )


def test_default_requires_separate_inference_approval_no_verifier_calls(tmp_path):
    plan, gate = _prepared(tmp_path)
    fake = FakeVerifier(_response())
    result = verify_local_vision(plan, gate, _test_verifier=fake)
    assert result.status == "local-inference-approval-required"
    assert result.attempted_model_calls == 0
    assert result.provider_calls == result.downloaded_media == 0
    assert result.assessments == ()
    assert fake.calls == []


def test_second_approval_invokes_only_one_explicit_local_unit(tmp_path):
    plan, gate = _prepared(tmp_path)
    fake = FakeVerifier(_response())
    run = verify_local_vision(plan, gate, approve_local_inference=True,
                              _test_verifier=fake)
    assert len(fake.calls) == 1
    scene, units = fake.calls[0]
    assert len(units) == 1
    assert units[0].source_path == str(gate.prepared[0].source_file)
    assert (units[0].start, units[0].end) == (1, 5)
    assert scene.english_text == plan.slots[0].visual_brief
    assert scene.context.objects == plan.slots[0].must_show
    assert scene.context.avoid == plan.slots[0].must_not_show
    assert run.attempted_model_calls == 1
    assert run.provider_calls == run.downloaded_media == 0
    assert run.timeline_approved is False
    a = run.assessments[0]
    assert a.status == "vision-provisional-human-review"
    assert a.human_review_required is True
    assert a.dimensions.action_match == .75
    assert "time-of-day-not-assessed" in a.reasons
    assert "temporal-action-requires-human-playback" in a.reasons
    assert str(gate.prepared[0].source_file) not in repr(run)


def test_missing_vision_response_preserves_unknown_no_auto_fallback(tmp_path):
    plan, gate = _prepared(tmp_path)
    result = verify_local_vision(plan, gate, approve_local_inference=True,
                                 _test_verifier=FakeVerifier(None))
    assert result.assessments[0].status == "vision-unavailable-or-abstained"
    assert result.assessments[0].dimensions is None
    assert result.timeline_approved is False


def test_model_failure_does_not_leak_exception_or_fake_verification(tmp_path):
    plan, gate = _prepared(tmp_path)
    result = verify_local_vision(plan, gate, approve_local_inference=True,
                                 _test_verifier=FakeVerifier(fail=True))
    assert "PRIVATE_SOURCE_PATH_SHOULD_NOT_PRINT" not in repr(result)
    assert result.assessments[0].status == "vision-unavailable-or-abstained"


def test_unknown_action_and_subject_do_not_become_verified(tmp_path):
    plan, gate = _prepared(tmp_path)
    outcome = verify_local_vision(
        plan, gate, approve_local_inference=True,
        _test_verifier=FakeVerifier(_response(subject=None, action=None)),
    )
    item = outcome.assessments[0]
    assert item.status == "vision-inconclusive-human-review"
    assert "subject-not-assessed" in item.reasons
    assert "action-not-assessed" in item.reasons
    assert outcome.timeline_approved is False


def test_must_not_show_conflict_requires_human_review(tmp_path):
    plan, gate = _prepared(tmp_path)
    run = verify_local_vision(
        plan, gate, approve_local_inference=True,
        _test_verifier=FakeVerifier(_response(conflict=.85)),
    )
    assert "possible-must-not-show-conflict" in run.assessments[0].reasons
    assert run.assessments[0].human_review_required


def test_no_approved_local_media_never_contacts_model(tmp_path):
    plan, gate = _prepared(tmp_path)
    bad = replace(gate, status="manual-opt-in-required", prepared=())
    fake = FakeVerifier(_response())
    r = verify_local_vision(plan, bad, approve_local_inference=True,
                            _test_verifier=fake)
    assert r.status == "no-approved-local-media"
    assert fake.calls == []


@pytest.mark.parametrize("url", [
    "http://example.com:11434", "https://localhost:11434",
    "http://127.0.0.1:11434/path", "http://127.0.0.1.evil.com",
])
def test_remote_or_untrusted_model_endpoints_blocked(tmp_path, url):
    plan, gate = _prepared(tmp_path)
    fake = FakeVerifier(_response())
    with pytest.raises(VlmConfigError):
        verify_local_vision(
            plan, gate, approve_local_inference=True,
            config=VlmConfig(url=url), _test_verifier=fake,
        )
    assert fake.calls == []


def test_wrong_slot_and_wrong_types_blocked(tmp_path):
    plan, gate = _prepared(tmp_path)
    with pytest.raises(LocalVisionGateError, match="invalid-vision-slot"):
        verify_local_vision(plan, replace(gate, slot_id="other"),
                            approve_local_inference=True)
    with pytest.raises(LocalVisionGateError, match="invalid-vision-bridge-input"):
        verify_local_vision(plan, gate, approve_local_inference=1)


def test_frame_sampler_and_vlm_come_from_existing_f021_code():
    from bin_finder.verification.frame_sampler import sample_times, FrameSamplingPolicy
    from bin_finder.verification.ollama_vlm import VlmConfig, validate_loopback_url
    assert sample_times(0, 10, 3) == (2.0, 5.0, 8.0)
    assert FrameSamplingPolicy().max_frames == 6
    assert VlmConfig(num_ctx=8192, num_predict=4096).validate() is None
    assert validate_loopback_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434"
