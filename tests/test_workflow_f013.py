import io
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bin_finder.acquisition import AcquisitionService, AcquisitionRequest, verified_candidate_path
from bin_finder.analysis.cache import AnalysisCache
from bin_finder.analysis.models import MediaMetadata, ShotSegment
from bin_finder.analysis.scene_detection import ShotDetectionResult
from bin_finder.analysis.service import CandidateAnalysisService
from bin_finder.evaluation import ReviewDecision, ReviewStore
from bin_finder.models import CandidateRecord, SceneRecord, SceneContext, FootageProject
from bin_finder.workflow import WorkflowRequest, WorkflowService, WorkflowStateError, default_work_root


MEDIA = b'\x00\x00\x00\x18ftypmp42' + b'fixture' * 100
SCENE = SceneRecord("s", 1, "ocean", context=SceneContext(subject=("ocean",)))


class Transport:
    def __init__(self):
        self.calls = []
        self.fail = set()

    def open(self, url, timeout):
        self.calls.append(url)
        if url in self.fail:
            raise OSError("Authorization: private-credential https://host/?key=secret")
        response = io.BytesIO(MEDIA)
        response.headers = {"Content-Type": "video/mp4", "Content-Length": str(len(MEDIA))}
        return response


class Probe:
    def __init__(self):
        self.calls = 0
        self.fail = False

    def probe(self, path):
        self.calls += 1
        if self.fail:
            raise RuntimeError("private-credential")
        return MediaMetadata(duration=6, width=1920, height=1080)


@pytest.fixture
def setup(tmp_path):
    transport, probe = Transport(), Probe()
    acquisition = AcquisitionService(tmp_path / "media", transport=transport,
                                     probe=SimpleNamespace(executable=""))
    detector = SimpleNamespace(detect=lambda path, duration: ShotDetectionResult(
        (ShotSegment(1, 0, duration),), "fixture"))
    analysis = CandidateAnalysisService(AnalysisCache(tmp_path / "analysis.sqlite3"), probe, detector)
    service = WorkflowService(tmp_path / "work", acquisition=acquisition, analysis=analysis)
    return SimpleNamespace(service=service, transport=transport, probe=probe, analysis=analysis,
                           acquisition=acquisition, root=tmp_path)


def candidate(number="7", **changes):
    return replace(CandidateRecord(number, "s", "pexels", "pexels:" + number, "ocean", 6, .8,
        preview_url=f"https://media.example/{number}.mp4?token=private-credential",
        source_url="https://pexels.com/video/7", creator="Author",
        source_metadata={"asset_id": number, "Authorization": "private-credential"}), **changes)


def review(c, **changes):
    return replace(ReviewDecision(c.scene_id, c.candidate_id, "accepted", provider=c.provider,
                                  source_id=c.source_id), **changes)


def request(*candidates, authorize=True, reviews=None):
    return WorkflowRequest((SCENE,), candidates,
        tuple(review(c) for c in candidates) if reviews is None else reviews, authorize)


@pytest.mark.parametrize("authorized,decision,allowed,code", [
    (True, "accepted", True, ""), (False, "accepted", False, "authorization_required"),
    (True, "rejected", False, "review_required"), (True, "waitlist", False, "review_required")])
def test_authorization(setup, authorized, decision, allowed, code):
    c = candidate()
    result = setup.service.run(request(c, authorize=authorized, reviews=(review(c, decision=decision),)))
    assert (result.items[0].stage == "analyzed") == allowed
    assert len(setup.transport.calls) == int(allowed)
    assert result.items[0].code == code


@pytest.mark.parametrize("field,value", [("scene_id", "other"), ("candidate_id", "other"),
    ("provider", "pixabay"), ("source_id", "pexels:other")])
def test_current_review_identity_is_required(setup, field, value):
    c = candidate()
    result = setup.service.run(request(c, reviews=(review(c, **{field: value}),)))
    assert result.items[0].code == "review_required"
    assert not setup.transport.calls


def test_handoff_provenance_cache_and_resume(setup):
    c = candidate()
    first = setup.service.run(request(c)).items[0]
    assert first.stage == "analyzed"
    assert verified_candidate_path(first.candidate) == first.local_path
    assert first.analysis.source_path == str(first.local_path)
    for field in ("scene_id", "candidate_id", "provider", "source_id", "source_url", "creator", "source_metadata"):
        assert getattr(first.candidate, field) == getattr(c, field)
    # New service instance, original candidate, no new authorization.
    resumed_service = WorkflowService(setup.service.root, acquisition=setup.acquisition, analysis=setup.analysis)
    second = resumed_service.run(request(c, authorize=False)).items[0]
    assert second.stage == "analyzed" and second.acquisition_reused
    assert second.analysis.cache_key == first.analysis.cache_key
    assert setup.probe.calls == 1 and len(setup.transport.calls) == 1
    # Independent run reuses F012 cache through its public acquisition API.
    independent = WorkflowService(setup.root / "other", acquisition=setup.acquisition, analysis=setup.analysis)
    assert independent.run(request(c)).items[0].acquisition_reused
    assert len(setup.transport.calls) == 1 and setup.probe.calls == 1


def test_preacquired_candidate_needs_no_download_authorization(setup):
    c = candidate()
    acquired = setup.acquisition.acquire(AcquisitionRequest(c, review(c), True))
    assert setup.service.run(request(acquired.candidate, authorize=False)).items[0].stage == "analyzed"
    assert len(setup.transport.calls) == 1


@pytest.mark.parametrize("damage", ["media", "manifest", "missing_manifest"])
def test_manifest_verified_before_analysis(setup, damage):
    c = candidate()
    acquired = setup.acquisition.acquire(AcquisitionRequest(c, review(c), True))
    if damage == "media":
        acquired.local_path.write_bytes(b"corrupt")
    elif damage == "manifest":
        acquired.manifest_path.write_text("{}")
    else:
        acquired.manifest_path.unlink()
    item = setup.service.run(request(acquired.candidate)).items[0]
    assert item.code == "invalid_acquisition" and setup.probe.calls == 0


def test_remote_url_never_analyzed(setup):
    c = candidate(provider="youtube", source_id="youtube:7", preview_url=str(setup.root / "local.mp4"))
    (setup.root / "local.mp4").write_bytes(MEDIA)
    item = setup.service.run(request(c)).items[0]
    assert item.stage == "failed" and setup.probe.calls == 0


def test_local_analysis_and_changed_bytes_fail_closed(setup):
    path = setup.root / "local.mp4"
    path.write_bytes(MEDIA)
    c = candidate(provider="local", source_id="local:7", preview_url=str(path))
    assert setup.service.run(request(c, authorize=False, reviews=())).items[0].stage == "analyzed"
    path.write_bytes(b"changed")
    assert setup.service.run(request(c, authorize=False)).items[0].code == "stale_state"


def test_resume_acquired_after_analysis_failure(setup):
    c = candidate()
    setup.probe.fail = True
    first = setup.service.run(request(c)).items[0]
    assert first.code == "analysis_failed" and first.local_path.is_file()
    setup.probe.fail = False
    second = setup.service.run(request(c, authorize=False)).items[0]
    assert second.stage == "analyzed" and second.acquisition_reused
    assert len(setup.transport.calls) == 1


@pytest.mark.parametrize("damage", ["signature", "local_path", "media_sha256", "stage", "shape", "reference", "analysis_cache_key"])
def test_stale_run_item_fails_closed(setup, damage):
    c = candidate()
    result = setup.service.run(request(c))
    payload = json.loads(result.state_path.read_text())
    key = next(iter(payload["items"]))
    if damage == "shape":
        payload["items"][key] = []
    elif damage == "reference":
        payload["items"][key].pop("acquisition_manifest")
    else:
        payload["items"][key][damage] = "invalid"
    result.state_path.write_text(json.dumps(payload))
    item = setup.service.run(request(c)).items[0]
    assert item.stage == "failed"
    assert len(setup.transport.calls) == 1 and setup.probe.calls == 1


def test_atomic_state_and_write_failure(setup, monkeypatch):
    from bin_finder.workflow import state
    original = state.os.replace
    observations = []
    def replace_file(source, destination):
        if Path(destination).name == "workflow.json":
            assert json.loads(Path(source).read_text())["format"] == state.FORMAT
            observations.append(source)
        return original(source, destination)
    with monkeypatch.context() as patch:
        patch.setattr(state.os, "replace", replace_file)
        result = setup.service.run(request(candidate()))
    assert observations and not list(setup.service.root.glob("*.tmp"))
    saved = result.state_path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(state.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("private-credential")))
        with pytest.raises(WorkflowStateError, match="persisted"):
            setup.service.run(request(candidate()))
    assert result.state_path.read_bytes() == saved


def test_corrupt_run_and_concurrent_run_fail_safely(setup):
    setup.service.root.mkdir()
    state = setup.service.root / "workflow.json"
    state.write_text("invalid")
    with pytest.raises(WorkflowStateError, match="safely"):
        setup.service.run(request(candidate()))
    state.unlink()
    (setup.service.root / "workflow.lock").touch()
    with pytest.raises(WorkflowStateError, match="already in use"):
        setup.service.run(request(candidate()))


def test_multi_item_acquisition_failure_retry_and_order(setup):
    a, b = candidate("a"), candidate("b")
    setup.transport.fail.add(a.preview_url)
    first = setup.service.run(request(b, a))
    assert [i.candidate.candidate_id for i in first.items] == ["a", "b"]
    assert [i.stage for i in first.items] == ["failed", "analyzed"]
    setup.transport.fail.clear()
    second = setup.service.run(request(b, a))
    assert all(i.stage == "analyzed" for i in second.items)
    assert len(setup.transport.calls) == 3 and setup.probe.calls == 1  # same bytes reuse F003
    assert len(second.by_scene["s"]) == 2


def test_multi_item_analysis_failure_isolated(setup, monkeypatch):
    original = setup.analysis.analyze_candidate
    def analyze(c):
        if c.candidate_id == "a":
            raise RuntimeError("private-credential")
        return original(c)
    monkeypatch.setattr(setup.analysis, "analyze_candidate", analyze)
    result = setup.service.run(request(candidate("b"), candidate("a")))
    assert [i.stage for i in result.items] == ["failed", "analyzed"]
    assert result.items[0].code == "analysis_failed"


@pytest.mark.parametrize("when", ["before", "acquiring", "analyzing", "after_analysis", "after_first"])
def test_cooperative_cancellation(setup, monkeypatch, when):
    stop = [when == "before"]
    original = setup.analysis.analyze_candidate
    if when == "after_analysis":
        def analyze(c):
            result = original(c)
            stop[0] = True
            return result
        monkeypatch.setattr(setup.analysis, "analyze_candidate", analyze)
    def progress(event):
        if event.stage == when or (when == "after_first" and event.stage == "analyzed"):
            stop[0] = True
    result = setup.service.run(request(candidate("a"), candidate("b")), progress=progress,
                               cancelled=lambda: stop[0])
    assert result.cancelled and result.items[1].stage == "cancelled"
    assert result.items[0].stage == ("analyzed" if when == "after_first" else "cancelled")
    payload = json.loads(result.state_path.read_text())
    assert any(item["stage"] == "cancelled" for item in payload["items"].values())
    if when in {"before", "analyzing"}:
        assert setup.probe.calls == 0
    assert not list(setup.acquisition.root.glob(".partial-*"))


def test_downstream_keeps_review_and_readiness_authoritative(setup):
    from bin_finder.acceptance import evaluate_project
    from bin_finder.integration_adapter import build_ai_video_editor_manifest, write_integration_package, IntegrationExportError
    from bin_finder.diversity import DiversityCandidate, SourceDiversitySelector
    from bin_finder.verification.reranker import VerificationReranker
    from bin_finder.clips.planner import SmartClipPlanner
    c = candidate()
    store = ReviewStore(setup.root / "reviews.json")
    store.record_decision(review(c))
    before = store.path.read_bytes()
    item = setup.service.run(request(c, reviews=store.decisions())).items[0]
    assert item.ranked and item.downstream["verification"] == "not_configured"
    assert all(unit.unit.source_path == str(item.local_path) for unit in item.ranked)
    verified = VerificationReranker().rerank(SCENE, list(item.ranked))
    assert SmartClipPlanner().propose_many(verified)
    diversity = DiversityCandidate.from_candidate_record(item.candidate, scene_order=1)
    assert SourceDiversitySelector().select([diversity]).selected
    assert store.path.read_bytes() == before
    project = FootageProject("p", setup.root, [SCENE])
    report = evaluate_project(project)
    assert not report.ready
    assert build_ai_video_editor_manifest(project, report)["scenes"][0]["footage"] is None
    with pytest.raises(IntegrationExportError):
        write_integration_package(setup.root / "export", project, report)


def test_configured_downstream_and_fallback(setup):
    from bin_finder.verification.reranker import VerificationReranker
    from bin_finder.clips.planner import SmartClipPlanner
    setup.service.verifier = VerificationReranker()
    setup.service.planner = SmartClipPlanner()
    item = setup.service.run(request(candidate())).items[0]
    assert item.proposals and item.downstream["verification"] == "completed"
    def fail(*args):
        raise RuntimeError("private-credential")
    setup.service.verifier = VerificationReranker(SimpleNamespace(verify=fail))
    item = setup.service.run(request(candidate())).items[0]
    assert item.stage == "analyzed" and not item.proposals
    assert item.downstream["verification"] == "incomplete"


def test_security_safe_state_and_storage(setup, monkeypatch):
    monkeypatch.setenv("BIN_FINDER_PEXELS_API_KEY", "private-credential")
    monkeypatch.setenv("BIN_FINDER_PIXABAY_API_KEY", "other-private-credential")
    c = candidate()
    setup.transport.fail.add(c.preview_url)
    result = setup.service.run(request(c))
    text = result.state_path.read_text()
    assert "private-credential" not in text and "Authorization" not in text
    assert "https://" not in text and "raw_response" not in text
    assert "private-credential" not in result.items[0].message
    assert not default_work_root("project").is_relative_to(Path.cwd())
    assert not result.state_path.is_relative_to(Path.cwd())


def test_smoke_requires_approval_and_skips_missing_credentials(monkeypatch):
    from bin_finder.workflow_smoke import run
    from bin_finder.provider_config import ProviderConfig
    monkeypatch.setattr(ProviderConfig, "load", lambda: ProviderConfig())
    assert set(run().values()) == {"SKIPPED_NOT_APPROVED"}
    assert set(run(approve_test_acquisition=True).values()) == {"SKIPPED_NO_CREDENTIAL"}


def test_partial_acquisition_cancellation_and_unknown_progress(setup):
    c = candidate()
    stop, events = [False], []
    original = setup.transport.open
    def open_response(*args):
        response = original(*args)
        response.headers.pop("Content-Length")
        return response
    setup.transport.open = open_response
    def progress(event):
        events.append(event)
        if event.stage == "acquiring" and len([e for e in events if e.stage == "acquiring"]) == 3:
            stop[0] = True  # F012 has written the first chunk, but has not published it.
    result = setup.service.run(request(c, candidate("8")), progress=progress, cancelled=lambda: stop[0])
    assert all(i.stage == "cancelled" and i.analysis is None for i in result.items)
    assert all(e.percent is None for e in events)
    assert not list(setup.acquisition.root.iterdir())
    assert len(setup.transport.calls) == 1 and setup.probe.calls == 0


def test_stale_signature_remains_quarantined_on_retry(setup):
    c = candidate()
    setup.service.run(request(c))
    changed = replace(c, preview_url="https://media.example/new.mp4")
    for _ in range(2):
        assert setup.service.run(request(changed)).items[0].code == "stale_state"
    assert len(setup.transport.calls) == 1


def test_revoked_review_blocks_resume(setup):
    c = candidate()
    setup.service.run(request(c))
    item = setup.service.run(request(c, reviews=(review(c, decision="rejected"),))).items[0]
    assert item.code == "review_required" and setup.probe.calls == 1
    assert setup.service.run(request(c, authorize=False)).items[0].stage == "analyzed"


def test_transcript_cache_invalidation_stays_with_f003(setup):
    c = candidate()
    first = setup.service.run(request(c)).items[0]
    first.local_path.with_suffix(".srt").write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nOcean waves\n", encoding="utf-8")
    second = setup.service.run(request(c, authorize=False)).items[0]
    assert second.stage == "analyzed" and setup.probe.calls == 2
    assert second.analysis.cache_key != first.analysis.cache_key
    assert len(setup.transport.calls) == 1


def test_unsupported_media_not_marked_analyzed(setup, monkeypatch):
    monkeypatch.setattr(setup.probe, "probe", lambda path: MediaMetadata())
    item = setup.service.run(request(candidate())).items[0]
    assert item.stage == "failed" and item.code == "unsupported_media"


def test_resume_acquired_snapshot(setup):
    c = candidate()
    first = setup.service.run(request(c))
    payload = json.loads(first.state_path.read_text())
    entry = next(iter(payload["items"].values()))
    entry["stage"] = "acquired"
    entry.pop("analysis_cache_key")
    first.state_path.write_text(json.dumps(payload))
    second = setup.service.run(request(c, authorize=False))
    assert second.items[0].stage == "analyzed" and setup.probe.calls == 1
    assert len(setup.transport.calls) == 1


def test_item_state_write_failure_preserves_other_items(setup, monkeypatch):
    from bin_finder.workflow.state import RunState
    original = RunState.write
    failed = [False]
    def write(store):
        if not failed[0] and any(i.get("stage") == "analyzing" for i in store.items.values()):
            failed[0] = True
            raise WorkflowStateError("Workflow state could not be persisted.")
        return original(store)
    monkeypatch.setattr(RunState, "write", write)
    result = setup.service.run(request(candidate("a"), candidate("b")))
    assert result.items[0].stage == "failed" and result.items[0].code == "state_write_failed"
    assert result.items[1].stage == "analyzed"
    payload = json.loads(result.state_path.read_text())
    assert sorted(i["stage"] for i in payload["items"].values()) == ["analyzed", "failed"]
