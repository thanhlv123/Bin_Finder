"""Portable R1 narration and visual planning records."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Cue:
    cue_id: str
    chapter: str
    text: str
    word_count: int
    est_duration_sec: float

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


@dataclass(frozen=True)
class ShotBrief:
    cue_id: str
    subject: str
    action: str
    setting: str
    shot_type: str
    camera_motion: str
    mood: str
    must_show: list[str]
    avoid: list[str]
    queries: dict[str, list[str]]
    origin: str
    notes: str

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)
