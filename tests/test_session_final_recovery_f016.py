"""F016 explicit final selection roundtrip and fail-closed recovery."""
from dataclasses import replace
import hashlib

import pytest

from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.models import SelectedClipRecord
from bin_finder.session_codec import SessionError, selection_to_data
from bin_finder.session_recovery import restore_session
from bin_finder.session_store import SessionStore
from test_session_recovery_f016 import sample


def approved_clip(path, provider="local"):
    path.write_bytes(b"F016 local media fixture")
    return SelectedClipRecord(
        clip_id="clip_" + hashlib.sha256(b"explicit-f014-approval").hexdigest(),
        scene_id="scene_001", scene_order=1, provider=provider,
        source_id="source-001", title="Local footage",
        local_file=str(path), start=10.0, end=15.0, duration=5.0,
        semantic_score=.9, vlm_score=.8, final_score=.9,
        rights_status="owned", creator="fixture",
        source_url="https://example.org/watch?token=SECRET",
        source_metadata={
            "media_sha256": fingerprint_file(path).sha256,
            "license_basis": "owned", "duplicate_group": "",
            "proposal_unit_id": "unit-001",
            "verification_provider": "fixture",
            "raw_provider_response": {"token": "must-never-persist"},
        },
    )


def saved_payload(tmp_path, provider="local"):
    media = tmp_path / "media.mp4"
    clip = approved_clip(media, provider)
    payload = sample()
    payload["final_selections"] = [selection_to_data(clip)]
    store = SessionStore(tmp_path / "sessions")
    store.save(payload)
    return store, media


def test_explicit_local_approval_survives_restart_with_rehashed_identity(tmp_path):
    store, _ = saved_payload(tmp_path)
    loaded = store.load_active()
    restored = restore_session(loaded)
    assert len(restored.final_selections) == 1
    clip = restored.final_selections[0]
    assert clip.scene_id == "scene_001" and clip.final_score == .9
    assert clip.source_url == ""
    assert restored.unresolved == ()
    assert "raw_provider_response" not in str(loaded)
    assert "token" not in str(loaded).lower()


def test_changed_source_never_restores_approval(tmp_path):
    store, media = saved_payload(tmp_path)
    media.write_bytes(b"replaced media")
    restored = restore_session(store.load_active())
    assert restored.final_selections == ()
    assert restored.unresolved == (("scene_001", "media-identity-changed"),)


def test_missing_source_never_restores_approval(tmp_path):
    store, media = saved_payload(tmp_path)
    media.unlink()
    restored = restore_session(store.load_active())
    assert restored.final_selections == ()
    assert restored.unresolved == (("scene_001", "local-media-unavailable"),)


def test_remote_requires_original_f012_provenance(tmp_path):
    store, _ = saved_payload(tmp_path, "pexels")
    restored = restore_session(store.load_active())
    assert restored.final_selections == ()
    assert restored.unresolved == (("scene_001", "remote-provenance-required"),)


def test_symlink_media_refused(tmp_path):
    store, media = saved_payload(tmp_path)
    link = tmp_path / "alias.mp4"
    try:
        link.symlink_to(media)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privileges unavailable")
    payload = store.load_active()
    payload["final_selections"][0]["local_file"] = str(link)
    store.save(payload)
    assert restore_session(store.load_active()).final_selections == ()


def test_unknown_fields_and_forged_candidate_never_saved(tmp_path):
    store, _ = saved_payload(tmp_path)
    original = store.load_active()
    original["final_selections"][0]["authorization"] = "Bearer secret"
    with pytest.raises(SessionError, match="unvalidated-references"):
        store.save(original)
    assert "authorization" not in store.load_active()["final_selections"][0]


@pytest.mark.parametrize("field,value", [
    ("final_score", float("nan")),
    ("duration", 2.0),
    ("scene_order", 2),
    ("local_file", "https://example.com/a.mp4?signature=secret"),
])
def test_invalid_approval_evidence_rejected(tmp_path, field, value):
    store, _ = saved_payload(tmp_path)
    payload = store.load_active()
    payload["final_selections"][0][field] = value
    with pytest.raises(SessionError):
        store.save(payload)


def test_nonfinal_candidate_cannot_be_serialized():
    with pytest.raises(SessionError, match="final-record-required"):
        selection_to_data({"scene_id": "scene_001"})


def test_secret_in_title_is_rejected(tmp_path, monkeypatch):
    media = tmp_path / "media.mp4"
    clip = approved_clip(media)
    monkeypatch.setenv("BIN_FINDER_TEST_API_KEY", "secret_fixture_value")
    with pytest.raises(SessionError, match="unsafe-selection-text"):
        selection_to_data(replace(clip, title="secret_fixture_value"))
