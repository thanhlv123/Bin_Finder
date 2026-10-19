from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClipPolicy:
    target_duration: float = 5.0
    min_duration: float = 3.5
    max_duration: float = 7.0
    allow_short_shots: bool = False

    def validate(self) -> None:
        if self.min_duration <= 0:
            raise ValueError("min_duration must be positive.")
        if self.max_duration < self.min_duration:
            raise ValueError("max_duration must be >= min_duration.")
        if not self.min_duration <= self.target_duration <= self.max_duration:
            raise ValueError("target_duration must be inside min/max bounds.")


@dataclass(frozen=True)
class ClipProposal:
    unit_id: str
    source_path: str
    start: float
    end: float
    score: float
    accepted: bool
    reason: str
    anchor_time: float | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class ExtractionResult:
    output_path: str
    bytes_written: int
    duration: float
