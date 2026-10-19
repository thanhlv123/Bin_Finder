from pathlib import Path

from bin_finder.analysis.cache import AnalysisCache
from bin_finder.analysis.models import (
    CandidateAnalysis,
    MediaFingerprint,
    MediaMetadata,
    ShotSegment,
    TranscriptSegment,
)


def sample_analysis(path: str = "D:/clips/a.mp4") -> CandidateAnalysis:
    return CandidateAnalysis(
        source_path=path,
        analyzer_version="f003-test",
        fingerprint=MediaFingerprint("a" * 64, 123, 456),
        metadata=MediaMetadata(10.0, 1920, 1080, 30.0, "h264", True),
        transcript=(TranscriptSegment(1.0, 2.0, "hello"),),
        shots=(ShotSegment(1, 0.0, 10.0),),
        transcript_source="D:/clips/a.srt",
        transcript_sha256="b" * 64,
        detector_backend="ffmpeg-scene",
        warnings=("warning",),
    )


def test_analysis_cache_round_trip(tmp_path: Path):
    cache = AnalysisCache(tmp_path / "analysis.sqlite3")
    analysis = sample_analysis()
    cache.put(analysis)

    loaded = cache.get(
        analysis.fingerprint.sha256,
        analysis.transcript_sha256,
        analysis.analyzer_version,
    )

    assert loaded == analysis
    assert loaded.cache_key == analysis.cache_key


def test_analysis_cache_version_and_transcript_isolation(tmp_path: Path):
    cache = AnalysisCache(tmp_path / "analysis.sqlite3")
    analysis = sample_analysis()
    cache.put(analysis)

    assert cache.get(
        analysis.fingerprint.sha256,
        analysis.transcript_sha256,
        "different-version",
    ) is None
    assert cache.get(
        analysis.fingerprint.sha256,
        "c" * 64,
        analysis.analyzer_version,
    ) is None


def test_analysis_cache_clear(tmp_path: Path):
    cache = AnalysisCache(tmp_path / "analysis.sqlite3")
    analysis = sample_analysis()
    cache.put(analysis)
    cache.clear()
    assert cache.get(
        analysis.fingerprint.sha256,
        analysis.transcript_sha256,
        analysis.analyzer_version,
    ) is None
