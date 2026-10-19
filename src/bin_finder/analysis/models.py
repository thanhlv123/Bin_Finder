from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


ANALYZER_VERSION = "f003-v1"


@dataclass(frozen=True)
class MediaFingerprint:
    sha256: str
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True)
class MediaMetadata:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    has_audio: bool = False

    @property
    def resolution(self) -> str:
        if self.width > 0 and self.height > 0:
            return f"{self.width}x{self.height}"
        return ""


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ShotSegment:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class CandidateAnalysis:
    source_path: str
    analyzer_version: str
    fingerprint: MediaFingerprint
    metadata: MediaMetadata
    transcript: tuple[TranscriptSegment, ...] = ()
    shots: tuple[ShotSegment, ...] = ()
    transcript_source: str = ""
    detector_backend: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def cache_key(self) -> str:
        return f"{self.fingerprint.sha256}:{self.analyzer_version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "analyzer_version": self.analyzer_version,
            "fingerprint": asdict(self.fingerprint),
            "metadata": asdict(self.metadata),
            "transcript": [asdict(item) for item in self.transcript],
            "shots": [asdict(item) for item in self.shots],
            "transcript_source": self.transcript_source,
            "detector_backend": self.detector_backend,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CandidateAnalysis":
        return cls(
            source_path=str(payload.get("source_path") or ""),
            analyzer_version=str(payload.get("analyzer_version") or ANALYZER_VERSION),
            fingerprint=MediaFingerprint(**payload["fingerprint"]),
            metadata=MediaMetadata(**payload.get("metadata", {})),
            transcript=tuple(
                TranscriptSegment(**item) for item in payload.get("transcript", [])
            ),
            shots=tuple(ShotSegment(**item) for item in payload.get("shots", [])),
            transcript_source=str(payload.get("transcript_source") or ""),
            detector_backend=str(payload.get("detector_backend") or ""),
            warnings=tuple(str(item) for item in payload.get("warnings", [])),
        )
