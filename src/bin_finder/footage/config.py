"""Project-scoped discovery settings (no credentials)."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class FootageConfig:
    sources: list[str] = field(default_factory=lambda: ["pexels", "pixabay", "commons", "coverr"])
    youtube_enabled: bool = False
    per_query_limit: int = 8
    max_candidates_per_cue: int = 30
    min_width: int = 1280
    min_height: int = 720
    orientation: str = "landscape"
    exclude_unusable: bool = True

    def enabled_sources(self):
        sources = [s for s in self.sources if s != "youtube"]
        if self.youtube_enabled:
            sources.append("youtube")
        return list(dict.fromkeys(sources))

    def __post_init__(self):
        if not isinstance(self.sources, list) or any(not isinstance(s, str) or not s for s in self.sources):
            raise ValueError("Invalid footage sources")
        for name in ("youtube_enabled", "exclude_unusable"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"Invalid footage {name}")
        for name in ("per_query_limit", "max_candidates_per_cue", "min_width", "min_height"):
            value = getattr(self, name)
            if type(value) is not int or value < (1 if "limit" in name or name == "max_candidates_per_cue" else 0):
                raise ValueError(f"Invalid footage {name}")
        if self.orientation not in {"any", "landscape", "portrait", "square"}:
            raise ValueError("Invalid footage orientation")

    @classmethod
    def load(cls, project_root=None):
        path = Path(project_root or Path.cwd()) / "config" / "footage.local.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(data, dict):
            raise ValueError("Invalid footage configuration")
        defaults = cls()
        values = {}
        for name in cls.__dataclass_fields__:
            raw = os.environ.get("BIN_FINDER_FOOTAGE_" + name.upper())
            if raw is None:
                values[name] = data.get(name, getattr(defaults, name))
            elif name == "sources":
                values[name] = [s.strip() for s in raw.split(",") if s.strip()]
            elif name in {"youtube_enabled", "exclude_unusable"}:
                if raw.lower() not in {"true", "false", "1", "0", "yes", "no"}:
                    raise ValueError(f"Invalid footage {name}")
                values[name] = raw.lower() in {"true", "1", "yes"}
            elif isinstance(getattr(defaults, name), int):
                values[name] = int(raw)
            else:
                values[name] = raw
        return cls(**values)
