"""Deterministic connection ownership, including Windows immediate cleanup."""
import shutil
import sqlite3

import pytest

from bin_finder.analysis.cache import AnalysisCache
from bin_finder.analysis.models import CandidateAnalysis, MediaFingerprint, MediaMetadata
from bin_finder.analysis.scene_detection import ShotDetectionResult
from bin_finder.analysis.service import CandidateAnalysisService


@pytest.fixture
def connections(monkeypatch):
    # Keep strong references so garbage collection cannot hide leaked handles.
    opened = []
    connect = sqlite3.connect

    def tracked(*args, **kwargs):
        connection = connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked)
    return opened


def assert_closed(connections):
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def sample():
    return CandidateAnalysis(
        source_path="clip.mp4", analyzer_version="closure-test",
        fingerprint=MediaFingerprint("a" * 64, 5, 0), metadata=MediaMetadata(),
    )


@pytest.mark.parametrize("operation", ["miss", "put", "hit", "clear"])
def test_cache_operations_close_connections(tmp_path, connections, operation):
    cache = AnalysisCache(tmp_path / "cache" / "analysis.sqlite3")
    analysis = sample()
    if operation in {"hit", "clear"}:
        cache.put(analysis)
    if operation == "put":
        cache.put(analysis)
    elif operation == "clear":
        cache.clear()
        assert cache.get("a" * 64, "", "closure-test") is None
    else:
        result = cache.get("a" * 64, "", "closure-test")
        assert result == (analysis if operation == "hit" else None)
    assert_closed(connections)
    shutil.rmtree(cache.path.parent)
    assert not cache.path.parent.exists()


@pytest.mark.parametrize("failure", ["schema", "get", "put", "clear"])
def test_cache_exception_closes_connections(tmp_path, connections, monkeypatch, failure):
    cache = AnalysisCache(tmp_path / "analysis.sqlite3")
    cache.put(sample())
    original_connect = cache._connect

    def failing_connection():
        connection = original_connect()
        # Fail real SQLite statements without replacing connection lifecycle behavior.
        action = {"schema": sqlite3.SQLITE_CREATE_TABLE, "get": sqlite3.SQLITE_SELECT,
                  "put": sqlite3.SQLITE_INSERT, "clear": sqlite3.SQLITE_DELETE}[failure]
        connection.set_authorizer(lambda code, *args: sqlite3.SQLITE_DENY
                                  if code == action else sqlite3.SQLITE_OK)
        return connection

    monkeypatch.setattr(cache, "_connect", failing_connection)
    with pytest.raises(sqlite3.DatabaseError):
        if failure == "put":
            cache.put(sample())
        elif failure == "clear":
            cache.clear()
        else:
            cache.get("a" * 64, "", "closure-test")
    assert_closed(connections)
    cache.path.unlink()


def test_failed_transaction_rolls_back_and_closes(tmp_path, connections):
    cache = AnalysisCache(tmp_path / "analysis.sqlite3")
    analysis = sample()
    cache.put(analysis)
    with pytest.raises(RuntimeError, match="abort"):
        with cache._connection() as connection:
            connection.execute("DELETE FROM analysis_cache")
            raise RuntimeError("abort")
    assert cache.get("a" * 64, "", "closure-test") == analysis
    assert_closed(connections)


def test_analysis_service_allows_immediate_directory_cleanup(tmp_path, connections):
    class Probe:
        def probe(self, path):
            return MediaMetadata(duration=1.0, width=10, height=10)

    class Detector:
        def detect(self, path, duration):
            return ShotDetectionResult(shots=(), backend="test")

    root = tmp_path / "analysis-run"
    root.mkdir()
    media = root / "clip.mp4"
    media.write_bytes(b"local test fixture")
    service = CandidateAnalysisService(
        cache=AnalysisCache(root / "analysis.sqlite3"), probe=Probe(), detector=Detector(),
    )
    first = service.analyze_path(media)
    assert service.analyze_path(media) == first
    assert_closed(connections)
    # Service and every connection remain referenced during Windows file deletion.
    shutil.rmtree(root)
    assert not root.exists()
