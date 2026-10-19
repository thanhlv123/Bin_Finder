from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProviderConfig:
    youtube_api_key: str = field(default="", repr=False)
    pexels_api_key: str = field(default="", repr=False)
    pixabay_api_key: str = field(default="", repr=False)
    storyblocks_public_key: str = field(default="", repr=False)
    storyblocks_secret_key: str = field(default="", repr=False)
    storyblocks_project_id: str = ""
    storyblocks_user_id: str = ""
    local_library_path: str = ""

    @classmethod
    def load(cls, project_root: Path | None = None) -> "ProviderConfig":
        root = project_root or Path.cwd()
        config_path = root / "config" / "providers.local.json"
        payload: dict[str, Any] = {}
        if config_path.exists():
            try:
                loaded = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (OSError, json.JSONDecodeError):
                payload = {}

        def value(env_name: str, json_name: str) -> str:
            env_value = os.environ.get(env_name, "").strip()
            if env_value:
                return env_value
            raw = payload.get(json_name, "")
            return str(raw).strip() if raw is not None else ""

        return cls(
            youtube_api_key=value("BIN_FINDER_YOUTUBE_API_KEY", "youtube_api_key"),
            pexels_api_key=value("BIN_FINDER_PEXELS_API_KEY", "pexels_api_key"),
            pixabay_api_key=value("BIN_FINDER_PIXABAY_API_KEY", "pixabay_api_key"),
            storyblocks_public_key=value("BIN_FINDER_STORYBLOCKS_PUBLIC_KEY", "storyblocks_public_key"),
            storyblocks_secret_key=value("BIN_FINDER_STORYBLOCKS_SECRET_KEY", "storyblocks_secret_key"),
            storyblocks_project_id=value("BIN_FINDER_STORYBLOCKS_PROJECT_ID", "storyblocks_project_id"),
            storyblocks_user_id=value("BIN_FINDER_STORYBLOCKS_USER_ID", "storyblocks_user_id"),
            local_library_path=value("BIN_FINDER_LOCAL_LIBRARY", "local_library_path"),
        )
