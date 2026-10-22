"""F016 restore fails closed on over-long paths (Windows MAX_PATH / WinError 206)."""
import errno
import os
from pathlib import Path

import pytest

from bin_finder import session_recovery
from bin_finder.session_recovery import restore_session
from test_session_final_recovery_f016 import saved_payload

REASON = (("scene_001", "local-media-path-too-long"),)


def _raise_for(target, error, original):
    def patched(path, *args, **kwargs):
        if Path(path) == Path(target):
            raise error
        return original(path, *args, **kwargs)
    return patched


@pytest.mark.parametrize("error", [
    OSError(errno.ENOENT, "The filename or extension is too long", None, 206),
    OSError(errno.ENAMETOOLONG, "File name too long"),
], ids=["winerror-206", "enametoolong"])
def test_filesystem_path_error_becomes_unresolved(tmp_path, monkeypatch, error):
    store, media = saved_payload(tmp_path)
    if error.errno == errno.ENOENT and getattr(error, "winerror", None) != 206:
        pytest.skip("winerror attribute is Windows-only")
    monkeypatch.setattr(session_recovery.os, "lstat",
                        _raise_for(media, error, os.lstat))
    restored = restore_session(store.load_active())
    assert restored.final_selections == ()
    assert restored.unresolved == REASON


def test_hashing_path_error_never_validates_media(tmp_path, monkeypatch):
    store, media = saved_payload(tmp_path)
    error = OSError(errno.ENAMETOOLONG, "File name too long")
    monkeypatch.setattr(session_recovery, "fingerprint_file",
                        _raise_for(media, error, session_recovery.fingerprint_file))
    restored = restore_session(store.load_active())
    assert restored.final_selections == ()
    assert restored.unresolved == REASON


@pytest.mark.skipif(os.name != "nt", reason="Windows MAX_PATH semantics")
def test_real_over_limit_windows_path_is_not_shortened(tmp_path):
    store, _ = saved_payload(tmp_path)
    payload = store.load_active()
    long_path = tmp_path / ("d" * 120) / ("e" * 120) / "media.mp4"
    assert len(str(long_path)) >= session_recovery.WINDOWS_MAX_PATH
    payload["final_selections"][0]["local_file"] = str(long_path)
    store.save(payload)
    loaded = store.load_active()
    restored = restore_session(loaded)
    assert restored.final_selections == ()
    assert restored.unresolved == REASON
    # Evidence is retained verbatim for later review, never truncated.
    assert loaded["final_selections"][0]["local_file"] == str(long_path)


def test_short_missing_path_keeps_unavailable_reason(tmp_path):
    store, media = saved_payload(tmp_path)
    media.unlink()
    restored = restore_session(store.load_active())
    assert restored.unresolved == (("scene_001", "local-media-unavailable"),)
