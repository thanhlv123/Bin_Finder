from pathlib import Path

from bin_finder.analysis.cache import AnalysisCache
from bin_finder.analysis.models import MediaMetadata, ShotSegment
from bin_finder.analysis.scene_detection import ShotDetectionResult
from bin_finder.analysis.service import CandidateAnalysisService
from bin_finder.models import CandidateRecord


class FakeProbe:
    def __init__(self):
        self.calls = 0

    def probe(self, path):
        self.calls += 1
        return MediaMetadata(
            duration=8.0,
            width=1920,
            height=1080,
            fps=30.0,
            codec="h264",
            has_audio=True,
        )


class FakeDetector:
    def __init__(self):
        self.calls = 0

    def detect(self, path, duration):
        self.calls += 1
        return ShotDetectionResult(
            shots=(
                ShotSegment(1, 0.0, 3.0),
                ShotSegment(2, 3.0, duration),
            ),
            backend="fake-scene",
        )


def test_analysis_service_reuses_content_cache_after_media_and_sidecar_rename(tmp_path: Path):
    media = tmp_path / "clip.mp4"
    sidecar = tmp_path / "clip.srt"
    media.write_bytes(b"authorized local media")
    sidecar.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nHavana mechanic\n",
        encoding="utf-8",
    )
    probe = FakeProbe()
    detector = FakeDetector()
    service = CandidateAnalysisService(
        cache=AnalysisCache(tmp_path / "cache.sqlite3"),
        probe=probe,
        detector=detector,
        analyzer_version="f003-test",
    )

    first = service.analyze_path(media)
    renamed = tmp_path / "renamed.mp4"
    renamed_sidecar = tmp_path / "renamed.srt"
    media.rename(renamed)
    sidecar.rename(renamed_sidecar)
    second = service.analyze_path(renamed)

    assert probe.calls == 1
    assert detector.calls == 1
    assert first.fingerprint.sha256 == second.fingerprint.sha256
    assert first.transcript_sha256 == second.transcript_sha256
    assert second.source_path.endswith("renamed.mp4")
    assert second.transcript_source.endswith("renamed.srt")
    assert first.transcript[0].text == "Havana mechanic"
    assert len(first.shots) == 2


def test_transcript_change_invalidates_cached_analysis(tmp_path: Path):
    media = tmp_path / "clip.mp4"
    sidecar = tmp_path / "clip.srt"
    media.write_bytes(b"authorized local media")
    sidecar.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nFirst transcript\n",
        encoding="utf-8",
    )
    probe = FakeProbe()
    detector = FakeDetector()
    service = CandidateAnalysisService(
        cache=AnalysisCache(tmp_path / "cache.sqlite3"),
        probe=probe,
        detector=detector,
        analyzer_version="f003-test",
    )

    first = service.analyze_path(media)
    sidecar.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nChanged transcript\n",
        encoding="utf-8",
    )
    second = service.analyze_path(media)

    assert first.transcript_sha256 != second.transcript_sha256
    assert second.transcript[0].text == "Changed transcript"
    assert probe.calls == 2
    assert detector.calls == 2


def test_analyze_candidate_only_accepts_local_media(tmp_path: Path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"local")
    service = CandidateAnalysisService(
        cache=AnalysisCache(tmp_path / "cache.sqlite3"),
        probe=FakeProbe(),
        detector=FakeDetector(),
    )
    remote = CandidateRecord(
        candidate_id="x",
        scene_id="scene_001",
        provider="youtube",
        source_id="youtube:x",
        title="remote",
        duration=0,
        score=0,
        preview_url=str(media),
    )
    local = CandidateRecord(
        candidate_id="y",
        scene_id="scene_001",
        provider="local",
        source_id="local:y",
        title="local",
        duration=0,
        score=0,
        preview_url=str(media),
    )

    assert service.analyze_candidate(remote) is None
    assert service.analyze_candidate(local) is not None
