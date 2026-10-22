"""F016 F013 workflow references are historical hints, never authority."""
from pathlib import Path

import pytest

from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.models import CandidateRecord
from bin_finder.session_codec import SessionError, validate_snapshot
from bin_finder.session_recovery import restore_session
from bin_finder.session_store import SessionStore
from bin_finder import session_workflow
from bin_finder.workflow import WorkflowItemResult, WorkflowResult
from bin_finder.workflow.state import RunState, digest
from test_session_recovery_f016 import sample


def fixture_workflow(tmp_path, monkeypatch):
    media = tmp_path / "media.mp4"
    media.write_bytes(b"F016 historical workflow fixture")
    project_id = "sample-project"
    root = tmp_path / "workflows" / digest(project_id)[:24]
    monkeypatch.setattr(session_workflow, "default_work_root", lambda _: root)
    candidate = CandidateRecord("candidate-001", "scene_001", "local",
                                "local:asset-001", "Fixture", 10.0, .9)
    identity = [candidate.scene_id, candidate.candidate_id,
                candidate.provider, candidate.source_id]
    state = RunState(root)
    state.items = {digest(identity): {
        "scene_id": candidate.scene_id, "candidate_id": candidate.candidate_id,
        "provider": candidate.provider, "source_id": candidate.source_id,
        "signature": digest(["opaque-signed-urls"]),
        "stage": "analyzed", "local_path": str(media),
        "media_sha256": fingerprint_file(media).sha256,
        "analysis_cache_key": "historical-cache-key",
    }}
    state.write()
    item = WorkflowItemResult(candidate, stage="analyzed", local_path=media)
    return state, media, WorkflowResult((item,), state.path)


def test_capture_persist_and_restore_non_authoritative_reference(tmp_path, monkeypatch):
    state, media, result = fixture_workflow(tmp_path, monkeypatch)
    refs = session_workflow.capture_workflow_refs("sample-project", result)
    assert len(refs) == 1
    assert set(refs[0]) == {
        "scene_id", "candidate_id", "provider", "source_id",
        "signature", "media_sha256"}
    payload = sample()
    payload["workflow_refs"] = list(refs)
    store = SessionStore(tmp_path / "sessions")
    store.save(payload)
    restored = restore_session(store.load_active())
    assert restored.workflow_refs == refs
    assert restored.final_selections == ()
    assert "local_path" not in str(store.load_active())
    assert "opaque-signed-urls" not in str(store.load_active())


def test_stale_workflow_state_or_media_cannot_restore_reference(tmp_path, monkeypatch):
    state, media, result = fixture_workflow(tmp_path, monkeypatch)
    refs = session_workflow.capture_workflow_refs("sample-project", result)
    payload = sample()
    payload["workflow_refs"] = list(refs)
    media.write_bytes(b"changed")
    assert restore_session(payload).workflow_refs == ()
    media.write_bytes(b"F016 historical workflow fixture")
    entry = next(iter(state.items.values()))
    entry["signature"] = digest(["changed-identity"])
    state.write()
    assert restore_session(payload).workflow_refs == ()


def test_workflow_reference_does_not_accept_unvalidated_or_credential_data():
    payload = sample()
    payload["workflow_refs"] = [{"scene_id": "scene_001"}]
    with pytest.raises(SessionError, match="invalid-workflow-reference"):
        validate_snapshot(payload)
    payload = sample()
    payload["workflow_refs"] = [{
        "scene_id": "scene_001", "candidate_id": "Bearer credential",
        "provider": "local", "source_id": "local:asset",
        "signature": "a" * 64, "media_sha256": "b" * 64,
    }]
    with pytest.raises(SessionError, match="unsafe-snapshot-text"):
        validate_snapshot(payload)


def test_workflow_ref_cannot_cross_project_or_become_approval(tmp_path, monkeypatch):
    state, media, result = fixture_workflow(tmp_path, monkeypatch)
    assert session_workflow.capture_workflow_refs("different-project", result) == ()
    refs = session_workflow.capture_workflow_refs("sample-project", result)
    payload = sample()
    payload["workflow_refs"] = list(refs)
    payload["project_id"] = "different-project"
    restored = restore_session(payload)
    assert restored.workflow_refs == ()
    assert restored.final_selections == ()
