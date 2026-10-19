from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Protocol

from bin_finder.analysis.cache import AnalysisCache
from bin_finder.analysis.fingerprint import fingerprint_file
from bin_finder.analysis.models import (
    ANALYZER_VERSION,
    CandidateAnalysis,
    MediaMetadata,
)
from bin_finder.analysis.probe import FFprobeMediaProbe, MediaProbeError
from bin_finder.analysis.scene_detection import FfmpegSceneDetector, ShotDetectionResult
from bin_finder.analysis.transcript import load_transcript_sidecar
from bin_finder.models import CandidateRecord


class MediaProbeLike(Protocol):
    def probe(self, path: str | Path) -> MediaMetadata: ...


class SceneDetectorLike(Protocol):
    def detect(self, path: str | Path, duration: float) -> ShotDetectionResult: ...


class CandidateAnalysisService:
    def __init__(
        self,
        cache: AnalysisCache | None = None,
        probe: MediaProbeLike | None = None,
        detector: SceneDetectorLike | None = None,
        analyzer_version: str = ANALYZER_VERSION,
    ):
        self.cache = cache or AnalysisCache()
        self.probe = probe or FFprobeMediaProbe()
        self.detector = detector or FfmpegSceneDetector()
        self.analyzer_version = analyzer_version

    def analyze_path(self, path: str | Path, *, force: bool = False) -> CandidateAnalysis:
        media_path = Path(path).expanduser().resolve()
        if not media_path.exists() or not media_path.is_file():
            raise FileNotFoundError(str(media_path))

        fingerprint = fingerprint_file(media_path)
        if not force:
            cached = self.cache.get(fingerprint.sha256, self.analyzer_version)
            if cached is not None:
                return replace(cached, source_path=str(media_path), fingerprint=fingerprint)

        warnings: list[str] = []
        try:
            metadata = self.probe.probe(media_path)
        except MediaProbeError as exc:
            metadata = MediaMetadata()
            warnings.append(str(exc))

        transcript_source, transcript = load_transcript_sidecar(media_path)
        if transcript_source is None:
            warnings.append("Không tìm thấy transcript sidecar SRT/VTT.")

        detection = self.detector.detect(media_path, metadata.duration)
        if detection.warning:
            warnings.append(detection.warning)

        analysis = CandidateAnalysis(
            source_path=str(media_path),
            analyzer_version=self.analyzer_version,
            fingerprint=fingerprint,
            metadata=metadata,
            transcript=transcript,
            shots=detection.shots,
            transcript_source=str(transcript_source) if transcript_source else "",
            detector_backend=detection.backend,
            warnings=tuple(dict.fromkeys(warnings)),
        )
        self.cache.put(analysis)
        return analysis

    def analyze_candidate(
        self,
        candidate: CandidateRecord,
        *,
        force: bool = False,
    ) -> CandidateAnalysis | None:
        if candidate.provider != "local":
            return None
        candidate_path = Path(candidate.preview_url or candidate.source_url)
        if not candidate_path.exists() or not candidate_path.is_file():
            return None
        return self.analyze_path(candidate_path, force=force)
