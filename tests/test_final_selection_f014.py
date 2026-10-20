import json
from dataclasses import replace

import pytest

from bin_finder.acceptance import evaluate_project
from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.analysis.models import CandidateAnalysis, MediaMetadata, ShotSegment
from bin_finder.clips import ClipProposal
from bin_finder.final_selection import (
    FinalSelectionError, FinalSelectionService, build_final_project, handoff_final_project,
)
from bin_finder.integration_adapter import IntegrationExportError, build_ai_video_editor_manifest
from bin_finder.models import CandidateRecord, SceneContext, SceneRecord
from bin_finder.retrieval import RankedSegment, RetrievalScores, RetrievalUnit
from bin_finder.verification import VerificationDimensions, VerificationResult, VerifiedSegment
from bin_finder.workflow import WorkflowItemResult


@pytest.fixture
def make_item(tmp_path):
    def make(index=1, source=None, start=0, final=.9):
        source = source or f"source{index}"
        path = tmp_path / f"{source}.mp4"
        path.write_bytes(b"offline media identity fixture")
        scene = SceneRecord(f"s{index}", index, "ocean", context=SceneContext(subject=("ocean",)))
        candidate = CandidateRecord(f"c{index}", scene.scene_id, "local", source, "ocean", 60, .11,
            "owned", source_url=str(path), preview_url=str(path), creator="creator",
            source_metadata={"license_basis": "owned", "duplicate_group": ""})
        analysis = CandidateAnalysis(str(path), "f003-v1", fingerprint_file(path),
            MediaMetadata(60, 1280, 720), shots=(ShotSegment(1, start, start + 5),))
        unit = RetrievalUnit(f"u{index}", str(path), start, start + 5, metadata_text="ocean")
        rank = RankedSegment(unit, RetrievalScores(.8, .8, .8, None, .82))
        verification = VerificationResult(unit.unit_id, "fixture-verifier", VerificationDimensions(subject_match=.95))
        verified = VerifiedSegment(rank, verification, .95, final, "verified")
        proposal = ClipProposal(unit.unit_id, str(path), start, start + 5, final, True, "whole-shot")
        return scene, WorkflowItemResult(candidate, "analyzed", local_path=path, analysis=analysis,
            ranked=(rank,), verified=(verified,), proposals=(proposal,))
    return make


def approve(service, scene, item, scenes, clips=()):
    option = service.options(scene, item)[0]
    return service.approve(scene, item, option.clip_id, scenes, clips, human_approved=True)


def test_valid_option_has_real_scores_and_provenance(make_item):
    scene, item = make_item()
    clip = approve(FinalSelectionService(), scene, item, [scene]).selections[0]
    assert (clip.semantic_score, clip.vlm_score, clip.final_score) == (.82, .95, .9)
    assert clip.rights_status == "owned"
    assert clip.creator == "creator"
    assert clip.source_metadata["license_basis"] == "owned"
    assert clip.source_metadata["verification_provider"] == "fixture-verifier"


@pytest.mark.parametrize("stage", ["pending", "acquired", "analyzing", "failed"])
def test_not_analyzed_rejected(make_item, stage):
    scene, item = make_item()
    with pytest.raises(FinalSelectionError, match="analysis-required"):
        FinalSelectionService().options(scene, replace(item, stage=stage))


@pytest.mark.parametrize("change", ["no_proposal", "rejected", "path", "unit_path", "range", "short",
    "fallback", "no_verification", "no_rank", "rank_mismatch", "unit_mismatch", "no_score", "nan_score"])
def test_invalid_evidence_has_no_options(make_item, change, tmp_path):
    scene, item = make_item()
    proposal, verified = item.proposals[0], item.verified[0]
    if change == "no_proposal": item.proposals = ()
    if change == "rejected": item.proposals = (replace(proposal, accepted=False),)
    if change == "path": item.proposals = (replace(proposal, source_path=str(tmp_path / "other")),)
    if change == "unit_path": item.ranked = (replace(item.ranked[0], unit=replace(item.ranked[0].unit, source_path="other")),)
    if change == "range": item.proposals = (replace(proposal, end=70),)
    if change == "short": item.proposals = (replace(proposal, end=2),)
    if change == "fallback": item.verified = (replace(verified, status="provider-fallback"),)
    if change == "no_verification": item.verified = ()
    if change == "no_rank": item.ranked = ()
    if change == "rank_mismatch": item.verified = (replace(verified, segment=replace(verified.segment, scores=replace(verified.segment.scores, final=.1))),)
    if change == "unit_mismatch": item.verified = (replace(verified, verification=replace(verified.verification, unit_id="wrong")),)
    if change == "no_score": item.verified = (replace(verified, verification_score=None),)
    if change == "nan_score": item.verified = (replace(verified, final_score=float("nan")),)
    assert FinalSelectionService().options(scene, item) == ()


def test_missing_or_changed_media_fails_closed(make_item):
    scene, item = make_item()
    item.local_path.write_bytes(b"changed")
    with pytest.raises(FinalSelectionError, match="media-identity"):
        FinalSelectionService().options(scene, item)
    item.local_path.unlink()
    with pytest.raises(FinalSelectionError, match="local-media"):
        FinalSelectionService().options(scene, item)


@pytest.mark.parametrize("change", ["no_analysis", "analysis_path", "unsupported_metadata"])
def test_analysis_must_match_local_media(make_item, change):
    scene, item = make_item()
    if change == "no_analysis": item.analysis = None
    if change == "analysis_path": item.analysis = replace(item.analysis, source_path="different.mp4")
    if change == "unsupported_metadata": item.analysis = replace(item.analysis, metadata=MediaMetadata())
    with pytest.raises(FinalSelectionError):
        FinalSelectionService().options(scene, item)


def test_remote_only_and_unverified_acquisition_fail(make_item):
    scene, item = make_item()
    remote = replace(item.candidate, provider="pexels", preview_url="https://example.com/video.mp4")
    with pytest.raises(FinalSelectionError):
        FinalSelectionService().options(scene, replace(item, candidate=remote))
    with pytest.raises(FinalSelectionError):
        FinalSelectionService().options(scene, replace(item, local_path=None))


def test_preparation_is_explicit_and_reuses_existing_evidence(make_item):
    scene, item = make_item()
    service = FinalSelectionService()
    assert service.prepare(scene, item).verified is item.verified
    bare = replace(item, verified=(), proposals=())
    assert not service.options(scene, bare)
    prepared = service.prepare(scene, bare)
    assert service.options(scene, prepared)
    assert not bare.verified and not bare.proposals
    assert bare.downstream["verification"] == "not_configured"
    rejected = replace(item, proposals=(replace(item.proposals[0], accepted=False),))
    assert not service.options(scene, service.prepare(scene, rejected))


def test_no_explicit_approval_and_stable_replacement(make_item):
    scene, item = make_item()
    service = FinalSelectionService()
    option = service.options(scene, item)[0]
    assert option == service.options(scene, item)[0]
    assert not hasattr(option, "clip")
    assert not service.approve(scene, item, option.clip_id, [scene]).accepted
    first = approve(service, scene, item, [scene])
    repeated = approve(service, scene, item, [scene], first.selections)
    assert repeated.selections == first.selections
    other_scene, other_item = make_item(source="replacement")
    replaced = approve(service, other_scene, other_item, [scene], first.selections)
    assert replaced.accepted and len(replaced.selections) == 1
    assert replaced.selections[0].clip_id != option.clip_id
    assert replaced.selections[0].scene_id == scene.scene_id


@pytest.mark.parametrize("index,start,expected", [(2, 10, "source-cooldown"), (3, 0, "source-overlap"), (3, 10, "approved")])
def test_diversity_retains_previous_human_choices(make_item, index, start, expected):
    service = FinalSelectionService()
    s1, a = make_item(1, "A")
    s2, b = make_item(2, "B")
    s3, c = make_item(index, "A", start)
    scenes = [s1, s2] if index == 2 else [s1, s2, s3]
    first = approve(service, s1, a, scenes)
    second = approve(service, s2, b, scenes, first.selections)
    result = approve(service, s3, c, scenes, second.selections)
    assert result.reason == expected
    if not result.accepted:
        assert result.selections == second.selections
    else:
        assert result.selections[:2] == second.selections


def test_duplicate_and_quality_drop_guardrails(make_item):
    service = FinalSelectionService()
    s1, a = make_item()
    s2, b = make_item(2)
    a.candidate = replace(a.candidate, source_metadata={"duplicate_group": "same"})
    b.candidate = replace(b.candidate, source_metadata={"duplicate_group": "same"})
    first = approve(service, s1, a, [s1, s2])
    assert approve(service, s2, b, [s1, s2], first.selections).reason == "duplicate-reuse"
    rank = replace(a.ranked[0], unit=replace(a.ranked[0].unit, unit_id="lower"))
    low = replace(a.verified[0], segment=rank, verification=replace(a.verified[0].verification, unit_id="lower"), final_score=.4)
    a.ranked += (rank,)
    a.verified += (low,)
    a.proposals += (replace(a.proposals[0], unit_id="lower", score=.4),)
    option = next(o for o in service.options(s1, a) if o.unit_id == "lower")
    result = service.approve(s1, a, option.clip_id, [s1, s2], first.selections, human_approved=True)
    assert result.reason == "quality-drop-guardrail"
    assert result.selections == first.selections


def test_new_earlier_scene_cannot_displace_later_final_choice(make_item):
    service = FinalSelectionService()
    earlier, a = make_item(1, "A", 10)
    later, b = make_item(2, "A", 0)
    previous = approve(service, later, b, [earlier, later])
    result = approve(service, earlier, a, [earlier, later], previous.selections)
    assert not result.accepted
    assert result.selections == previous.selections


def test_project_readiness_and_explicit_handoff(make_item, tmp_path):
    service, scenes, selections = FinalSelectionService(), [], ()
    items = [make_item(i) for i in range(1, 13)]
    scenes = [s for s, _ in items]
    project = build_final_project("project", scenes, selections, tmp_path / "export")
    assert evaluate_project(project).unresolved_scene_ids == tuple(s.scene_id for s in scenes)
    with pytest.raises(TypeError):
        build_final_project("project", scenes, [items[0][1].candidate], tmp_path)
    with pytest.raises(IntegrationExportError):
        handoff_final_project("project", scenes, (), tmp_path / "export")
    for scene, item in items:
        result = approve(service, scene, item, scenes, selections)
        assert result.accepted
        selections = result.selections
    assert not (tmp_path / "export").exists()  # Approval never hands off.
    project = build_final_project("project", scenes, selections, tmp_path / "export")
    report = evaluate_project(project)
    assert report.ready
    assert build_ai_video_editor_manifest(project, report)["ready"]
    paths = handoff_final_project("project", scenes, selections, tmp_path / "export")
    assert all(p.is_file() for p in paths)
    assert json.loads(paths[0].read_text(encoding="utf-8"))["ready"]
    low = (replace(selections[0], final_score=.2), *selections[1:])
    assert evaluate_project(build_final_project("project", scenes, low, tmp_path)).low_score_scene_ids == ("s1",)
    with pytest.raises(IntegrationExportError):
        handoff_final_project("project", scenes, low, tmp_path / "low")
    rotation = (selections[0], replace(selections[1], source_id=selections[0].source_id), *selections[2:])
    r = evaluate_project(build_final_project("project", scenes, rotation, tmp_path))
    assert not r.ready and r.source_rotation_issues and r.overlap_issues


def test_security_allowlist_and_source_tree_guard(make_item, monkeypatch, tmp_path):
    scene, item = make_item()
    monkeypatch.setenv("BIN_FINDER_TEST_API_KEY", "private-test-value")
    item.candidate = replace(item.candidate, title="private-test-value", creator="private-test-value",
        source_metadata={"Authorization": "Bearer private-test-value", "raw_response": {"key": "private-test-value"},
                         "license_url": "https://example.com/license?token=private-test-value"})
    clip = approve(FinalSelectionService(), scene, item, [scene]).selections[0]
    assert "private-test-value" not in json.dumps(clip.__dict__)
    assert "Authorization" not in clip.source_metadata and "raw_response" not in clip.source_metadata
    assert clip.source_metadata["license_url"] == "https://example.com/license"
    from pathlib import Path
    with pytest.raises(FinalSelectionError, match="output-inside-source-tree"):
        handoff_final_project("project", [scene], [clip], Path(__file__).resolve().parents[1] / "forbidden")
