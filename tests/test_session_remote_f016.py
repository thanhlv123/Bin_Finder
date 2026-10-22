"""F016 remote F012 cache proof regression tests."""
import hashlib
import json
from dataclasses import replace

from bin_finder.acquisition.service import FORMAT as F012_FORMAT, cache_key
from bin_finder.models import CandidateRecord
from bin_finder import session_remote
from bin_finder.session_codec import selection_to_data
from bin_finder.session_recovery import restore_session
from test_session_final_recovery_f016 import approved_clip
from test_session_recovery_f016 import sample


def make_case(tmp_path, monkeypatch):
    root = tmp_path / "cache" / "media"
    monkeypatch.setattr(session_remote, "default_cache_root", lambda: root)
    url = "https://example.test/media.mp4?signed=fixture"
    candidate = CandidateRecord("c1", "scene_001", "pexels", "pexels:123",
                                "Remote", 20.0, .9, preview_url=url)
    folder = root / cache_key(candidate)
    folder.mkdir(parents=True)
    media = folder / "media.mp4"
    clip = replace(approved_clip(media, provider="pexels"), source_id=candidate.source_id)
    rendition = hashlib.sha256(url.encode()).hexdigest()
    manifest = {
        "format": F012_FORMAT, "cache_version": 1, "cache_key": folder.name,
        "provider": "pexels", "source_id": candidate.source_id,
        "usage_authorization": "user_authorized_acquisition",
        "local_path": str(media), "size_bytes": media.stat().st_size,
        "byte_limit": 1000000, "sha256": clip.source_metadata["media_sha256"],
        "rendition_identifier": rendition,
        "selected_rendition": {"identifier": rendition, "width": 1280, "height": 720},
    }
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    payload = sample()
    payload["final_selections"] = [selection_to_data(clip)]
    return payload, media, path, manifest


def test_remote_provenance_validated_without_persisting_signed_url(tmp_path, monkeypatch):
    payload, media, path, manifest = make_case(tmp_path, monkeypatch)
    restored = restore_session(payload)
    assert len(restored.final_selections) == 1
    assert restored.unresolved == ()
    assert restored.final_selections[0].source_url == ""
    assert "signed=fixture" not in json.dumps(payload)


def test_remote_tampered_provenance_never_reapproves(tmp_path, monkeypatch):
    payload, media, path, manifest = make_case(tmp_path, monkeypatch)
    manifest["usage_authorization"] = "unknown"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert restore_session(payload).unresolved == (("scene_001", "remote-provenance-required"),)
    manifest["usage_authorization"] = "user_authorized_acquisition"
    manifest["sha256"] = "0" * 64
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert restore_session(payload).final_selections == ()
    path.unlink()
    assert restore_session(payload).final_selections == ()
