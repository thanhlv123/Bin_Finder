"""Project-local planning settings. Credentials never enter plan documents."""
from dataclasses import dataclass, field, fields
from pathlib import Path
import json
import math
import os


@dataclass(frozen=True)
class BriefConfig:
    provider: str = "auto"
    ollama_endpoint: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3-vl:4b-instruct"
    api_base_url: str = ""
    api_model: str = ""
    api_key: str = field(default="", repr=False)
    timeout_sec: float = 60.0
    batch_size: int = 6
    sources: list[str] = field(default_factory=lambda: ["pexels", "pixabay", "commons", "coverr", "youtube", "storyblocks"])
    style_hint: str = ""

    def __post_init__(self):
        if self.provider not in {"auto", "heuristic", "ollama", "openai_compatible"}:
            raise ValueError("invalid planning provider")
        if not math.isfinite(self.timeout_sec) or self.timeout_sec <= 0 or self.batch_size < 1:
            raise ValueError("planning timeout and batch size must be positive")
        if not isinstance(self.sources, list) or not self.sources or any(not isinstance(s, str) or not s.strip() for s in self.sources):
            raise ValueError("sources must be nonempty strings")

    @classmethod
    def load(cls, project_root):
        path = Path(project_root) / "config" / "planning.local.json"
        data = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        values = {}
        for f in fields(cls):
            value = os.environ.get("BIN_FINDER_PLANNING_" + f.name.upper(), data.get(f.name))
            if value is not None:
                if f.name == "sources" and isinstance(value, str):
                    value = json.loads(value) if value.lstrip().startswith("[") else [s.strip() for s in value.split(",") if s.strip()]
                if f.name == "batch_size":
                    value = int(value)
                if f.name == "timeout_sec":
                    value = float(value)
                values[f.name] = value
        return cls(**values)
