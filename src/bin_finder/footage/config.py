"""Project-scoped discovery settings (no credentials)."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class FootageConfig:
    sources: list[str] = field(default_factory=lambda: ["pexels", "pixabay", "commons", "coverr"])
    youtube_enabled: bool = False
    youtube_reuse: bool = False
    youtube_vlm_model: str = "qwen3-vl:4b-instruct"
    youtube_min_frame_score: float = 0.6
    videos_per_cue: int = 6
    frames_per_video: int = 8
    window_seconds: int = 8
    max_workers: int = 4
    cc_only: bool = False
    yt_dlp: str = "yt-dlp"
    ffmpeg: str = "ffmpeg"
    cache_dir: str = ".cache/footage/youtube"
    usage_dir: str = ""
    per_query_limit: int = 8
    max_candidates_per_cue: int = 30
    youtube_max_candidates_per_cue: int = 3
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
        for name in ("youtube_enabled", "youtube_reuse", "cc_only", "exclude_unusable"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"Invalid footage {name}")
        for name in ("per_query_limit", "max_candidates_per_cue", "youtube_max_candidates_per_cue", "min_width", "min_height", "videos_per_cue", "frames_per_video", "window_seconds", "max_workers"):
            value = getattr(self, name)
            if type(value) is not int or value < (0 if name in ("min_width", "min_height") else 1):
                raise ValueError(f"Invalid footage {name}")
        for name in ("yt_dlp", "ffmpeg", "cache_dir", "usage_dir", "youtube_vlm_model"):
            if not isinstance(getattr(self, name), str) or (name != "usage_dir" and not getattr(self, name)):
                raise ValueError(f"Invalid footage {name}")
        if type(self.youtube_min_frame_score) not in (int, float) or not 0 <= self.youtube_min_frame_score <= 1:
            raise ValueError("Invalid footage youtube_min_frame_score")
        if self.youtube_reuse:
            object.__setattr__(self, "youtube_enabled", True)
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
            elif name in {"youtube_enabled", "youtube_reuse", "cc_only", "exclude_unusable"}:
                if raw.lower() not in {"true", "false", "1", "0", "yes", "no"}:
                    raise ValueError(f"Invalid footage {name}")
                values[name] = raw.lower() in {"true", "1", "yes"}
            elif isinstance(getattr(defaults, name), int):
                values[name] = int(raw)
            elif isinstance(getattr(defaults, name), float):
                values[name] = float(raw)
            else:
                values[name] = raw
        return cls(**values)
