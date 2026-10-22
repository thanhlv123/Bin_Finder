"""F016 phase 1: scene/UI snapshots are atomic, versioned and fail closed."""
import json

import pytest

from bin_finder.models import SceneContext, SceneRecord
from bin_finder.session_codec import FORMAT, SessionError, validate_snapshot
from bin_finder.session_store import SessionStore, SessionStoreError


def sample():
    return {
        "format": FORMAT,
        "project_id": "sample-project",
        "scenes": [{
            "scene_id": "scene_001", "order": 1,
            "english_text": "A city at night.", "vietnamese_text": "",
            "target_duration": 5.0,
            "context": {key: ["city"] if key == "location" else []
                        for key in SceneContext.__dataclass_fields__},
        }],
        "final_selections": [], "workflow_refs": [],
        "ui_state": {"script_text": "A city at night.",
                     "current_scene_id": "scene_001"},
    }


def test_scene_and_ui_roundtrip(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    path = store.save(sample())
    assert path.is_file()
    loaded = store.load_active()
    assert loaded == validate_snapshot(sample())
    assert loaded["scenes"][0]["context"]["location"] == ["city"]


def test_unapproved_data_never_becomes_final_approval():
    payload = sample()
    payload["final_selections"] = [{"scene_id": "scene_001"}]
    with pytest.raises(SessionError, match="unvalidated-references"):
        validate_snapshot(payload)


def test_corrupt_version_and_unknown_keys_fail_closed():
    payload = sample()
    payload["format"] = "bin_finder_session_v2"
    with pytest.raises(SessionError):
        validate_snapshot(payload)
    payload = sample()
    payload["provider_payload"] = {"untrusted": "data"}
    with pytest.raises(SessionError):
        validate_snapshot(payload)


def test_reject_duplicate_scene_ids_and_nonfinite_duration():
    payload = sample()
    payload["scenes"].append(dict(payload["scenes"][0]))
    with pytest.raises(SessionError, match="duplicate-scenes"):
        validate_snapshot(payload)
    payload = sample()
    payload["scenes"][0]["target_duration"] = float("nan")
    with pytest.raises(SessionError):
        validate_snapshot(payload)


def test_invalid_save_keeps_previous_snapshot(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    path = store.save(sample())
    original = path.read_bytes()
    payload = sample()
    payload["ui_state"]["unexpected"] = "not-allowlisted"
    with pytest.raises(SessionError):
        store.save(payload)
    assert path.read_bytes() == original
    assert not list(path.parent.glob("*.tmp"))


def test_corrupted_json_and_duplicate_keys_fail_closed(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    path = store.save(sample())
    path.write_text('{"format":"one","format":"two"}', encoding="utf-8")
    with pytest.raises(SessionStoreError):
        store.load_active()


def test_missing_active_session_returns_none(tmp_path):
    assert SessionStore(tmp_path / "sessions").load_active() is None


def test_symlinked_store_root_refused(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink privileges unavailable")
    with pytest.raises(SessionStoreError):
        SessionStore(link).save(sample())


@pytest.mark.parametrize("section", ["script", "scene", "project"])
def test_snapshot_rejects_credentials_and_preserves_previous_data(tmp_path, section):
    store = SessionStore(tmp_path / "sessions")
    baseline = sample()
    store.save(baseline)
    payload = sample()
    if section == "script":
        payload["ui_state"]["script_text"] = "Authorization: Bearer test-credential"
    elif section == "scene":
        payload["scenes"][0]["english_text"] = "api_key=test-credential"
    else:
        payload["project_id"] = "token=test-credential"
    with pytest.raises(SessionError, match="unsafe-snapshot-text"):
        store.save(payload)
    assert store.load_active() == validate_snapshot(baseline)


def test_snapshot_rejects_environment_secret_in_script(tmp_path, monkeypatch):
    monkeypatch.setenv("BIN_FINDER_F016_TEST_SECRET", "unique-test-credential")
    payload = sample()
    payload["ui_state"]["script_text"] = "unique-test-credential"
    with pytest.raises(SessionError, match="unsafe-snapshot-text"):
        SessionStore(tmp_path / "sessions").save(payload)
