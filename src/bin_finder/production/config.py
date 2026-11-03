"""Local production settings without provider credentials."""
from dataclasses import dataclass, fields
import json
import math
import os
from pathlib import Path

from bin_finder.verification.ollama_vlm import validate_loopback_url


@dataclass(frozen=True)
class ProductionConfig:
    tts_url: str = "http://127.0.0.1:3900"
    tts_model: str = "omnivoice"
    voice: str = "bb142ec0"
    speed: float = 0.9
    language: str = "en"
    seed: int = 7
    tts_timeout_sec: float = 600.0
    tts_block_max_chars: int = 600
    comma_pause: float = 0.25
    stop_pause: float = 0.5
    block_gap: float = 0.4
    end_hold: float = 2.0
    width: int = 1920
    height: int = 1080
    fps: int = 30
    xfade_sec: float = 0.4
    ken_burns: bool = True
    music_path: str | None = None
    music_db: float = -22.0
    duck_db: float = -12.0
    whoosh_path: str | None = None
    whoosh_min_gap_sec: float = 20.0
    pop_path: str | None = None
    leak_path: str | None = None
    subtitles: bool = True
    subscribe_icon: bool = True
    subscribe_interval_sec: float = 120.0
    subscribe_duration_sec: float = 4.0
    subscribe_icon_path: str | None = None
    cache_dir: str = ".cache/production"
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"

    def __post_init__(self) -> None:
        validate_loopback_url(self.tts_url)
        for setting in fields(self):
            value = getattr(self, setting.name)
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Invalid {setting.name}")
        for name in ("speed", "tts_timeout_sec", "subscribe_interval_sec", "subscribe_duration_sec"):
            if getattr(self, name) <= 0:
                raise ValueError(f"Invalid {name}")
        for name in ("tts_block_max_chars", "width", "height", "fps"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                raise ValueError(f"Invalid {name}")
        for name in ("comma_pause", "stop_pause", "block_gap", "end_hold", "xfade_sec", "whoosh_min_gap_sec"):
            if getattr(self, name) < 0:
                raise ValueError(f"Invalid {name}")
        if self.width % 2 or self.height % 2 or self.duck_db > 0:
            raise ValueError("Even video dimensions and nonpositive duck_db are required")

    @classmethod
    def load(cls, project_root: Path) -> "ProductionConfig":
        """Read only production settings, then apply environment overrides."""
        project_root = Path(project_root).resolve()
        config_path = project_root / "config/production.local.json"
        payload = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        defaults = cls()
        values = {}
        for setting in fields(cls):
            name = setting.name
            value = os.environ.get("BIN_FINDER_PROD_" + name.upper(), payload.get(name))
            if value is None:
                continue
            default = getattr(defaults, name)
            if type(default) is bool:
                if str(value).lower() not in ("true", "false", "1", "0"):
                    raise ValueError(f"Invalid {name}")
                value = str(value).lower() in ("true", "1")
            elif type(default) in (int, float):
                value = type(default)(value)
            if name.endswith("_path") or name == "cache_dir":
                value = str((project_root / value).resolve()) if value else None
            values[name] = value
        values.setdefault("cache_dir", str(project_root / defaults.cache_dir))
        return cls(**values)
