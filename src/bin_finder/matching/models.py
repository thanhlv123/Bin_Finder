"""Portable matching output, independent of acquisition and GUI."""
from dataclasses import dataclass, asdict


@dataclass
class SelectionPlan:
    version: str
    footage_sha256: str
    brief_sha256: str
    script_sha256: str
    config: dict
    cues: list[dict]
    stats: dict

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)
