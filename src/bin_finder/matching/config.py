"""Matching settings; no provider credentials are read or serialized."""
from dataclasses import dataclass, field, fields, asdict
import json
import os
import math
from pathlib import Path


@dataclass(frozen=True)
class MatchConfig:
    top_k: int = 10
    vlm_top_n: int = 3
    vlm_enabled: bool = True
    auto_select_threshold: float = 0.6
    min_text_score: float = 0.15
    min_vlm_score: float = 0.7
    source_cooldown: int = 2
    no_adjacent_reuse: bool = True
    thumbnail_max_bytes: int = 2_000_000
    thumbnail_hosts: list[str] = field(
        default_factory=lambda: [
            'images.pexels.com', 'cdn.pixabay.com', 'pixabay.com',
            'upload.wikimedia.org', 'cdn.coverr.co',
        ],
    )
    timeout_sec: float = 30.0

    def __post_init__(self):
        for name in ('top_k', 'thumbnail_max_bytes', 'source_cooldown'):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(name)
        if type(self.vlm_top_n) is not int or self.vlm_top_n < 0:
            raise ValueError('vlm_top_n')
        for name in ('auto_select_threshold', 'min_text_score', 'min_vlm_score'):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(name)
        if not math.isfinite(self.timeout_sec) or self.timeout_sec <= 0:
            raise ValueError('timeout')
        for name in ('vlm_enabled', 'no_adjacent_reuse'):
            if type(getattr(self, name)) is not bool:
                raise ValueError('boolean')
        if not isinstance(self.thumbnail_hosts, list):
            raise ValueError('hosts')
        for host in self.thumbnail_hosts:
            if not isinstance(host, str) or not host or '/' in host or ':' in host:
                raise ValueError('hosts')

    @classmethod
    def load(cls, project_root):
        path = Path(project_root) / 'config/matching.local.json'
        data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        values = {}
        defaults = cls()
        for config_field in fields(cls):
            value = os.environ.get(
                'BIN_FINDER_MATCH_' + config_field.name.upper(), data.get(config_field.name),
            )
            if value is None:
                continue
            default = getattr(defaults, config_field.name)
            if isinstance(value, str):
                if type(default) is bool:
                    if value.lower() not in ('true', 'false', '1', '0'):
                        raise ValueError(config_field.name)
                    value = value.lower() in ('true', '1')
                elif type(default) is int:
                    value = int(value)
                elif type(default) is float:
                    value = float(value)
                elif isinstance(default, list):
                    if value.lstrip().startswith('['):
                        value = json.loads(value)
                    else:
                        value = [host.strip() for host in value.split(',')]
            values[config_field.name] = value
        return cls(**values)

    def summary(self):
        return asdict(self)
