import json
from pathlib import Path

from bin_finder.provider_config import ProviderConfig


def test_provider_config_loads_local_file_and_env_overrides(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "providers.local.json").write_text(
        json.dumps({"youtube_api_key": "file-youtube", "local_library_path": "D:/clips"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BIN_FINDER_YOUTUBE_API_KEY", "env-youtube")

    config = ProviderConfig.load(tmp_path)

    assert config.youtube_api_key == "env-youtube"
    assert config.local_library_path == "D:/clips"
    assert config.pexels_api_key == ""


def test_invalid_provider_config_is_treated_as_unconfigured(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "providers.local.json").write_text("{not-json", encoding="utf-8")

    config = ProviderConfig.load(tmp_path)

    assert config.youtube_api_key == ""
    assert config.storyblocks_secret_key == ""
